"""
apps/common/management/commands/ingest_ais_latest.py

Fetch Kpler AIS Latest for one or more ports (area filter from Port.ais_filter)
and turn the result into vessel positions and anchorage leads.

What it does with each vessel found inside the area:
  * anchored (navStatus 1, or speed at or below AIS_ANCHORAGE_MAX_SOG):
        vessel is created if new, a position is recorded, and a lead is created or
        updated in the Anchorage / port column.
  * moored (navStatus 5) or moving:
        only vessels already in the database get a new position. New vessels are
        NOT created, so moored ships do not flood the database.
"""
import json
import logging
from typing import Any, Dict, List

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.common.constants import PORT_AREA_ANCHORAGE, SOURCE_KPLER_AIS_LATEST
from apps.enrichment.models import EnrichmentLog
from apps.observations.models import VesselObservation
from apps.ports.models import Port
from apps.vessels.models import Vessel
from integrations.kpler.ais import fetch_ais_latest, get_ais_api_key
from integrations.kpler.ais_parser import parse_ais_latest
from integrations.kpler.exceptions import KplerError
from services.observation_service import record_observation_from_data
from services.opportunity_service import apply_lead
from services.vessel_service import upsert_vessel

logger = logging.getLogger("vessel_intel")

ENDPOINT = "kpler:ais_latest"


def _sanitize(text: Any) -> str:
    clean = str(text)
    for name in ("KPLER_AIS_API_KEY", "KPLER_API_KEY", "MARINETRAFFIC_API_KEY"):
        key = getattr(settings, name, "") or ""
        if key and key in clean:
            clean = clean.replace(key, "{api_key}")
    return clean


class Command(BaseCommand):
    help = "Fetch Kpler AIS Latest for a port area and ingest anchorage vessels and positions."

    def add_arguments(self, parser):
        parser.add_argument("--port", action="append", dest="ports",
                            help="UN/LOCODE of the port (repeatable). Default: active ports with an ais_filter.")
        parser.add_argument("--live", action="store_true", help="Allow a live call to Kpler AIS Latest.")
        parser.add_argument("--from-file", dest="from_file", type=str,
                            help="Read a saved AIS Latest JSON file instead of calling the API (one --port).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Run everything but roll the database changes back.")
        parser.add_argument("--limit", type=int, default=None,
                            help="Maximum features to request (default AIS_LATEST_LIMIT).")
        parser.add_argument("--horizon-hours", dest="horizon_hours", type=int, default=72)

    def handle(self, *args, **options):
        live = options["live"]
        from_file = options.get("from_file")
        dry_run = options["dry_run"]
        requested = options.get("ports")

        if not live and not from_file:
            raise CommandError("Either --live or --from-file PATH must be specified.")
        if from_file and (not requested or len(requested) != 1):
            raise CommandError("--from-file requires exactly one --port to be specified.")

        ports: List[Port] = []
        if requested:
            for code in requested:
                port = Port.objects.filter(un_locode=code.strip().upper()).first()
                if port is None:
                    raise CommandError(f"Port with UN/LOCODE '{code}' not found.")
                ports.append(port)
        else:
            ports = list(Port.objects.filter(active=True).exclude(ais_filter="").order_by("id"))

        if not ports:
            self.stdout.write(self.style.WARNING("No eligible ports to process."))
            return

        for port in ports:
            self._run_port(port, live=live, from_file=from_file, dry_run=dry_run,
                           limit=options.get("limit"), horizon_hours=options["horizon_hours"])

    # ------------------------------------------------------------------
    def _load_payload(self, port: Port, live: bool, from_file: str, limit):
        if from_file:
            try:
                with open(from_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"Failed to load file '{from_file}': {exc}")
            if isinstance(data, dict) and isinstance(data.get("payload"), dict):
                data = data["payload"]  # raw_store envelope
            return data

        if not (port.ais_filter or "").strip():
            raise CommandError(f"Port {port.un_locode} has no ais_filter. Paste the Kpler area filter first.")
        if not get_ais_api_key():
            raise CommandError("KPLER_AIS_API_KEY / KPLER_API_KEY is not configured.")
        try:
            payload = fetch_ais_latest(port.ais_filter, limit=limit, label=f"{port.un_locode}_latest")
            EnrichmentLog.objects.create(port=port, vessel=None, success=True, credits_spent=0,
                                         endpoint_called=ENDPOINT, error_message="")
            return payload
        except (KplerError, ValueError) as exc:
            clean = _sanitize(exc)
            logger.error("AIS Latest error for port %s: %s", port.un_locode, clean)
            EnrichmentLog.objects.create(port=port, vessel=None, success=False, credits_spent=0,
                                         endpoint_called=ENDPOINT, error_message=clean)
            raise CommandError(f"AIS Latest error for port {port.un_locode}: {clean}")

    def _run_port(self, port: Port, *, live, from_file, dry_run, limit, horizon_hours):
        payload = self._load_payload(port, live, from_file, limit)
        result = parse_ais_latest(
            payload,
            max_age_hours=getattr(settings, "AIS_MAX_POSITION_AGE_HOURS", 24),
            anchor_max_sog=getattr(settings, "AIS_ANCHORAGE_MAX_SOG", 1.0),
            gt_min=getattr(settings, "EXPECTED_ARRIVALS_GT_MIN", 3000),
            gt_max=getattr(settings, "EXPECTED_ARRIVALS_GT_MAX", 500000),
        )

        stats: Dict[str, int] = {
            "vessels_created": 0, "vessels_updated": 0, "excluded": 0,
            "not_recorded": 0, "observations_created": 0, "observations_duplicate": 0,
            "opps_created": 0, "opps_updated": 0, "opps_skipped": 0, "errors": 0,
        }

        with transaction.atomic():
            for item in result.accepted:
                vessel_dict = dict(item["vessel"])
                obs = item["observation"]
                port_area = item["port_area"]
                mmsi = vessel_dict["mmsi"]
                try:
                    with transaction.atomic():
                        existing = None
                        if vessel_dict.get("imo"):
                            existing = Vessel.objects.filter(imo=vessel_dict["imo"]).order_by("id").first()
                        if existing is None:
                            existing = Vessel.objects.filter(mmsi=mmsi).first()

                        # New vessels only when anchored AND the size is known (the parser has
                        # already dropped sizes outside the GT range). Tugs, pleasure craft and
                        # other small boats usually report no size and are never created.
                        if existing is None and (
                            port_area != PORT_AREA_ANCHORAGE or vessel_dict.get("grt") is None
                        ):
                            stats["not_recorded"] += 1
                            continue
                        if existing is not None:
                            # Do not let AIS rename or retype a vessel Expected Arrivals already knows.
                            for key in ("name", "flag", "vessel_type"):
                                vessel_dict.pop(key, None)

                        vessel, status = upsert_vessel(vessel_dict)
                        if status == "excluded" or vessel is None:
                            stats["excluded"] += 1
                            continue
                        stats["vessels_created" if status == "created" else "vessels_updated"] += 1

                        if VesselObservation.objects.filter(
                            vessel=vessel, timestamp=obs["timestamp"], source=SOURCE_KPLER_AIS_LATEST
                        ).exists():
                            stats["observations_duplicate"] += 1
                        else:
                            record_observation_from_data(vessel, obs, source=SOURCE_KPLER_AIS_LATEST)
                            stats["observations_created"] += 1

                        # A lead needs a known size: from AIS, or already stored for the vessel.
                        size_known = vessel_dict.get("grt") is not None or vessel.grt is not None
                        if port_area == PORT_AREA_ANCHORAGE and not size_known:
                            stats["opps_skipped"] += 1
                        elif port_area == PORT_AREA_ANCHORAGE:
                            _, opp_status = apply_lead(vessel, port, item["lead"],
                                                       port_area=port_area, horizon_hours=horizon_hours)
                            key = {"created": "opps_created", "updated": "opps_updated"}.get(opp_status, "opps_skipped")
                            stats[key] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error processing AIS vessel MMSI %s: %s", mmsi, exc)
                    stats["errors"] += 1

            if dry_run:
                transaction.set_rollback(True)

        rs = result.stats
        reasons = ", ".join(f"{k}: {v}" for k, v in rs["rejection_reasons"].items()) or "none"
        tag = " [DRY-RUN - NO CHANGES PERSISTED]" if dry_run else ""
        w = self.stdout.write
        w(f"\n=== AIS Latest: {port.name} ({port.un_locode}){tag} ===")
        w(f"AIS features: {rs['raw_features']}")
        w(f"Accepted: {rs['accepted']}")
        w(f"Rejected: {rs['rejected']} ({reasons})")
        w(f"In anchorage: {rs['in_anchorage']}")
        w(f"Moored in port: {rs['moored']}")
        w(f"Moving in area: {rs['moving']}")
        w(f"Vessels created: {stats['vessels_created']}")
        w(f"Vessels updated: {stats['vessels_updated']}")
        w(f"Excluded by vessel filter: {stats['excluded']}")
        w(f"Not recorded (new vessel, not at anchor or size unknown): {stats['not_recorded']}")
        w(f"Observations created: {stats['observations_created']}")
        w(f"Opportunities created: {stats['opps_created']}, updated: {stats['opps_updated']}, skipped: {stats['opps_skipped']}")
        w(f"Errors: {stats['errors']}")
        if dry_run:
            w("[DRY-RUN - NO CHANGES PERSISTED]")
