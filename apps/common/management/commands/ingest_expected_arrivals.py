"""
apps/common/management/commands/ingest_expected_arrivals.py

Management command to ingest MarineTraffic / Kpler Expected Arrivals data
into Vessel, VesselObservation, and Opportunity models via provider-agnostic services.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.common.constants import SOURCE_MARINETRAFFIC_EXPECTED_ARRIVALS
from apps.enrichment.models import EnrichmentLog
from apps.enrichment.models import record_arrivals_fetch
from apps.ports.models import Port
from integrations.kpler.arrivals_parser import parse_arrivals
from integrations.kpler.exceptions import (
    AuthenticationError,
    CallLimitError,
    ParameterError,
    ProviderRequestError,
    ServiceNotInContractError,
)
from integrations.kpler.expected_arrivals import fetch_expected_arrivals
from services.observation_service import record_observation_from_data
from services.opportunity_service import apply_lead
from services.vessel_service import upsert_vessel

logger = logging.getLogger("vessel_intel")

PORT_HOME_NAMES = {
    "SGSIN": ["SINGAPORE"],
    "AEFJR": ["FUJAIRAH"],
}


def _sanitize_text(text: str) -> str:
    """Strip any active API keys from error messages and logs."""
    from django.conf import settings

    mt_key = getattr(settings, "MARINETRAFFIC_API_KEY", "") or ""
    kpler_key = getattr(settings, "KPLER_API_KEY", "") or ""
    sanitized = str(text)
    if mt_key and mt_key in sanitized:
        sanitized = sanitized.replace(mt_key, "{api_key}")
    if kpler_key and kpler_key in sanitized:
        sanitized = sanitized.replace(kpler_key, "{api_key}")
    return sanitized



class Command(BaseCommand):
    help = (
        "Fetch and ingest MarineTraffic / Kpler Expected Arrivals into Vessel, "
        "VesselObservation, and Opportunity tables."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--port",
            action="append",
            dest="ports",
            help="UN/LOCODE of port to process (repeatable, e.g. --port SGSIN). Default: all active ports with MT ID.",
        )
        parser.add_argument(
            "--mode",
            choices=["arrivals", "inport"],
            required=True,
            help="Query mode: 'arrivals' (expected arrivals) or 'inport' (currently in port).",
        )
        parser.add_argument(
            "--live",
            action="store_true",
            help="Allow live network calls to MarineTraffic / Kpler API.",
        )
        parser.add_argument(
            "--from-file",
            dest="from_file",
            type=str,
            help="Load raw JSON from file instead of calling API (valid with exactly one --port).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Execute parser and simulate database ingestion without persisting changes.",
        )
        parser.add_argument(
            "--pause-seconds",
            dest="pause_seconds",
            type=int,
            default=120,
            help="Seconds to pause between consecutive live API calls (default: 120).",
        )
        parser.add_argument(
            "--horizon-hours",
            dest="horizon_hours",
            type=int,
            default=72,
            help="Horizon in hours for inbound opportunity eligibility (default: 72).",
        )

    def handle(self, *args, **options):
        live = options["live"]
        from_file = options.get("from_file")
        mode = options["mode"]
        dry_run = options["dry_run"]
        pause_seconds = options["pause_seconds"]
        horizon_hours = options["horizon_hours"]
        requested_ports = options.get("ports")

        # Validation: must specify either --live or --from-file
        if not live and not from_file:
            raise CommandError("Either --live or --from-file PATH must be specified.")

        # Validation: --from-file requires exactly one --port
        if from_file:
            if not requested_ports or len(requested_ports) != 1:
                raise CommandError("--from-file requires exactly one --port to be specified.")

        # Resolve ports to process
        ports_to_process: List[Port] = []
        if requested_ports:
            for unlocode in requested_ports:
                port = Port.objects.filter(un_locode=unlocode.strip().upper()).first()
                if port is None:
                    raise CommandError(f"Port with UN/LOCODE '{unlocode}' not found.")
                if not port.marinetraffic_port_id:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping port {port.un_locode}: missing marinetraffic_port_id"
                        )
                    )
                    continue
                ports_to_process.append(port)
        else:
            # Default: active ports with MT ID
            all_active = Port.objects.filter(active=True).order_by("id")
            for port in all_active:
                if not port.marinetraffic_port_id:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping active port {port.un_locode}: missing marinetraffic_port_id"
                        )
                    )
                    continue
                ports_to_process.append(port)

        if not ports_to_process:
            self.stdout.write(self.style.WARNING("No eligible ports to process."))
            return

        # Prepare port metadata dicts for parser
        all_port_dicts: Dict[str, Dict[str, Any]] = {}
        for p in Port.objects.filter(marinetraffic_port_id__isnull=False):
            all_port_dicts[p.un_locode] = {
                "port_id": str(p.marinetraffic_port_id),
                "unlocode": p.un_locode,
                "home_names": PORT_HOME_NAMES.get(p.un_locode, [p.name.upper()]),
            }

        finished_ports: List[str] = []

        for idx, port in enumerate(ports_to_process):
            port_dict = all_port_dicts.get(
                port.un_locode,
                {
                    "port_id": str(port.marinetraffic_port_id),
                    "unlocode": port.un_locode,
                    "home_names": PORT_HOME_NAMES.get(port.un_locode, [port.name.upper()]),
                },
            )
            other_ports = [
                d for code, d in all_port_dicts.items() if code != port.un_locode
            ]

            # Pause between live calls (never before the first, never after the last)
            if live and idx > 0 and pause_seconds > 0:
                self.stdout.write(f"Pausing for {pause_seconds}s before next provider call...")
                time.sleep(pause_seconds)

            rows: List[Dict[str, Any]] = []

            if from_file:
                try:
                    with open(from_file, "r", encoding="utf-8") as f:
                        file_data = json.load(f)
                    if isinstance(file_data, dict):
                        if "payload" in file_data and isinstance(file_data["payload"], list):
                            rows = file_data["payload"]
                        elif "data" in file_data and isinstance(file_data["data"], list):
                            rows = file_data["data"]
                        else:
                            rows = []
                    elif isinstance(file_data, list):
                        rows = file_data
                    else:
                        rows = []
                except Exception as exc:
                    raise CommandError(f"Failed to load file '{from_file}': {exc}")
            else:
                # Live API call
                try:
                    rows = fetch_expected_arrivals(port_dict["port_id"], mode=mode)
                    EnrichmentLog.objects.create(
                        port=port,
                        vessel=None,
                        success=True,
                        credits_spent=0,
                        endpoint_called="marinetraffic:expected_arrivals",
                        error_message="",
                    )
                except (
                    CallLimitError,
                    AuthenticationError,
                    ServiceNotInContractError,
                    ParameterError,
                    ProviderRequestError,
                ) as exc:
                    clean_msg = _sanitize_text(str(exc))
                    logger.error("Provider error for port %s: %s", port.un_locode, clean_msg)
                    EnrichmentLog.objects.create(
                        port=port,
                        vessel=None,
                        success=False,
                        credits_spent=0,
                        endpoint_called="marinetraffic:expected_arrivals",
                        error_message=clean_msg,
                    )
                    finished_str = ", ".join(finished_ports) if finished_ports else "None"
                    self.stdout.write(
                        self.style.ERROR(f"Ports finished before failure: {finished_str}")
                    )
                    raise CommandError(f"Provider error for port {port.un_locode}: {clean_msg}")
                except ValueError as exc:
                    clean_msg = _sanitize_text(str(exc))
                    logger.error("Client parameter error for port %s: %s", port.un_locode, clean_msg)
                    finished_str = ", ".join(finished_ports) if finished_ports else "None"
                    self.stdout.write(
                        self.style.ERROR(f"Ports finished before failure: {finished_str}")
                    )
                    raise CommandError(f"Client error: {clean_msg}")


            # Parse and clean rows
            parse_result = parse_arrivals(
                rows,
                port=port_dict,
                other_ports=other_ports,
                window_days=14,
            )

            accepted_items = parse_result.accepted
            skipped_not_in_port = 0
            if mode == "inport":
                filtered_items = []
                for item in accepted_items:
                    area = item["observation"]["port_area"]
                    if area in ("in_port", "anchorage"):
                        filtered_items.append(item)
                    else:
                        skipped_not_in_port += 1
                accepted_items = filtered_items

            port_stats = {
                "raw_rows": len(rows),
                "accepted": len(accepted_items),
                "rejected": len(parse_result.rejected),
                "skipped_not_in_port": skipped_not_in_port,
                "excluded_by_filter": 0,
                "vessels_created": 0,
                "vessels_updated": 0,
                "observations_created": 0,
                "opps_created": 0,
                "opps_updated": 0,
                "opps_skipped": 0,
                "inbound_from_other_port": parse_result.stats["flag_counts"].get(
                    "inbound_from_other_port", 0
                ),
                "came_from_target_port": sum(
                    1 for item in accepted_items if item["lead"].get("came_from_target_port")
                ),
                "errors": 0,
            }

            # Ingest accepted items inside transaction
            fetched_items = []
            with transaction.atomic():
                for item in accepted_items:
                    vessel_dict = item["vessel"]
                    obs_dict = item["observation"]
                    lead_dict = item["lead"]
                    imo = vessel_dict.get("imo")

                    try:
                        with transaction.atomic():
                            vessel, v_status = upsert_vessel(vessel_dict)
                            if v_status == "excluded" or vessel is None:
                                port_stats["excluded_by_filter"] += 1
                                continue
                            elif v_status == "created":
                                port_stats["vessels_created"] += 1
                            elif v_status == "updated":
                                port_stats["vessels_updated"] += 1

                            record_observation_from_data(
                                vessel,
                                obs_dict,
                                source=SOURCE_MARINETRAFFIC_EXPECTED_ARRIVALS,
                            )
                            port_stats["observations_created"] += 1

                            opp, opp_status = apply_lead(
                                vessel,
                                port,
                                lead_dict,
                                port_area=obs_dict.get("port_area", ""),
                                horizon_hours=horizon_hours,
                            )
                            if opp_status == "created":
                                port_stats["opps_created"] += 1
                            elif opp_status == "updated":
                                port_stats["opps_updated"] += 1
                            elif opp_status == "skipped":
                                port_stats["opps_skipped"] += 1
                            if opp is not None and opp_status in ("created", "updated"):
                                fetched_items.append((vessel, opp))

                    except Exception as exc:
                        logger.exception("Error processing vessel IMO %s: %s", imo, exc)
                        port_stats["errors"] += 1

                if live and mode == "arrivals" and fetched_items:
                    # Keep a dated list of the vessels this fetch saved (the Latest arrivals page).
                    record_arrivals_fetch(port, fetched_items)

                if dry_run:
                    transaction.set_rollback(True)

            finished_ports.append(port.un_locode)

            # Print report block for this port
            rej_reasons = parse_result.stats.get("rejection_reasons", {})
            rej_summary = ", ".join(f"{k}: {v}" for k, v in rej_reasons.items() if v > 0)
            if not rej_summary:
                rej_summary = "none"

            dry_run_tag = " [DRY-RUN - NO CHANGES PERSISTED]" if dry_run else ""
            inport_extra = f", skipped (not in port/anchorage): {port_stats['skipped_not_in_port']}" if mode == "inport" else ""

            self.stdout.write(
                f"\n=== Port: {port.name} ({port.un_locode}) [Port ID: {port.marinetraffic_port_id}]{dry_run_tag} ==="
            )
            self.stdout.write(f"Raw rows: {port_stats['raw_rows']}")
            self.stdout.write(f"Accepted: {port_stats['accepted']}{inport_extra}")
            self.stdout.write(f"Rejected: {port_stats['rejected']} ({rej_summary})")
            self.stdout.write(f"Excluded by vessel filter: {port_stats['excluded_by_filter']}")
            self.stdout.write(f"Vessels created: {port_stats['vessels_created']}")
            self.stdout.write(f"Vessels updated: {port_stats['vessels_updated']}")
            self.stdout.write(f"Observations created: {port_stats['observations_created']}")
            self.stdout.write(
                f"Opportunities created: {port_stats['opps_created']}, "
                f"updated: {port_stats['opps_updated']}, "
                f"skipped: {port_stats['opps_skipped']}"
            )
            self.stdout.write(f"Inbound from other port: {port_stats['inbound_from_other_port']}")
            self.stdout.write(f"Came from target port: {port_stats['came_from_target_port']}")
            self.stdout.write(f"Errors: {port_stats['errors']}")
            if dry_run:
                self.stdout.write("[DRY-RUN - NO CHANGES PERSISTED]")
