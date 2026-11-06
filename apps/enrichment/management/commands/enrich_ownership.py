"""Management command to enrich vessel ownership, management and particulars from Kpler."""
import json
import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone

from apps.common.constants import CLOSED_STAGES
from apps.opportunities.models import Opportunity
from apps.vessels.models import Vessel
from integrations.kpler.exceptions import (
    AuthenticationError,
    CallLimitError,
    KplerAccessError,
    KplerError,
    ProviderRequestError,
)
from integrations.kpler.graphql import _validate_and_dedup_imos, fetch_vessels
from integrations.kpler.vessel_parser import parse_vessel_node
from services.enrichment_service import enrich_vessel

logger = logging.getLogger("vessel_intel")


class Command(BaseCommand):
    help = "Enrich vessel particulars, owners, and managers via Kpler Vessels GraphQL API or fixture file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--imo",
            action="append",
            dest="imos",
            type=str,
            help="Specific IMO to enrich (repeatable, e.g. --imo 9146297 --imo 9308766).",
        )
        parser.add_argument(
            "--max-imos",
            dest="max_imos",
            type=int,
            default=50,
            help="Maximum IMOs to query in a single run (default 50).",
        )
        parser.add_argument(
            "--refresh-days",
            dest="refresh_days",
            type=int,
            default=30,
            help="Age in days beyond which to re-check ownership (default 30).",
        )
        parser.add_argument(
            "--from-file",
            dest="from_file",
            type=str,
            help="Load raw GraphQL response JSON from file instead of calling API.",
        )
        parser.add_argument(
            "--live",
            action="store_true",
            help="Allow live network calls to Kpler GraphQL API.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate run without making network calls or persisting changes.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes to the database (required for live calls or modifying records).",
        )
        parser.add_argument(
            "--pause-seconds",
            dest="pause_seconds",
            type=int,
            default=2,
            help="Seconds to pause between consecutive live batches (default 2).",
        )

    def handle(self, *args, **options):
        from_file = options.get("from_file")
        live = options.get("live", False)
        dry_run_flag = options.get("dry_run", False)
        apply_flag = options.get("apply", False)

        # Mode determination:
        # If live: dry-run is default unless --apply is passed
        # If from-file: dry-run if --dry-run passed; applies if not dry-run or --apply
        if from_file:
            is_dry_run = dry_run_flag and not apply_flag
        elif live:
            is_dry_run = dry_run_flag or not apply_flag
        else:
            self.stderr.write(
                "Error: You must specify either --from-file <path> or --live."
            )
            return

        if from_file:
            self._handle_from_file(from_file, is_dry_run)
            return

        if live:
            self._handle_live(options, is_dry_run)

    def _handle_from_file(self, file_path_str: str, is_dry_run: bool):
        path = Path(file_path_str)
        if not path.is_absolute():
            # Check relative to cwd
            if not path.exists():
                # Check relative to repo root
                repo_root = Path(__file__).resolve().parent.parent.parent.parent
                candidate = repo_root / path
                if candidate.exists():
                    path = candidate

        if not path.exists():
            self.stderr.write(f"Error: Fixture file not found: {file_path_str}")
            return

        self.stdout.write(f"Loading Kpler fixture from {path} (dry-run: {is_dry_run})...")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self.stderr.write(f"Error reading JSON from {path}: {exc}")
            return

        # Extract nodes
        nodes = []
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], dict):
                vessels_data = data["data"].get("vessels") or {}
                nodes = vessels_data.get("nodes") or []
            elif "nodes" in data:
                nodes = data["nodes"]
        elif isinstance(data, list):
            nodes = data

        self.stdout.write(f"Parsed {len(nodes)} vessel node(s) from fixture.")

        if is_dry_run:
            self.stdout.write(self.style.WARNING("=== [DRY-RUN] No database modifications will be persisted ==="))
            for idx, node in enumerate(nodes[:10], start=1):
                parsed = parse_vessel_node(node)
                p_name = parsed["particulars"]["name"] or "Unknown"
                party_count = len(parsed["parties"])
                self.stdout.write(f"  {idx}. IMO {parsed['imo']} - {p_name} ({party_count} parties found)")
            self.stdout.write(self.style.SUCCESS(f"[DRY-RUN complete] Total nodes evaluated: {len(nodes)}"))
            return

        total_vessels_updated = 0
        total_companies_created = 0
        total_relationships_created = 0
        total_relationships_closed = 0
        total_leads_rescored = 0
        errors = 0

        for node in nodes:
            try:
                parsed = parse_vessel_node(node)
                res = enrich_vessel(parsed, source="kpler:file")
                if res:
                    total_vessels_updated += 1
                    total_companies_created += res["created_companies"]
                    total_relationships_created += res["created_relationships"]
                    total_relationships_closed += res["closed_relationships"]
                    total_leads_rescored += res["rescored_opportunities"]
            except Exception as exc:
                errors += 1
                logger.error("Error enriching vessel node: %s", exc)

        self.stdout.write(self.style.SUCCESS("\n=== Ownership Enrichment Summary (From File) ==="))
        self.stdout.write(f"IMOs requested / processed : {len(nodes)}")
        self.stdout.write(f"Vessels updated            : {total_vessels_updated}")
        self.stdout.write(f"Companies created          : {total_companies_created}")
        self.stdout.write(f"Relationships created      : {total_relationships_created}")
        self.stdout.write(f"Relationships closed       : {total_relationships_closed}")
        self.stdout.write(f"Leads rescored             : {total_leads_rescored}")
        self.stdout.write(f"Errors                     : {errors}")

    def _handle_live(self, options: dict, is_dry_run: bool):
        # 1. Live mode flag check
        enabled = getattr(settings, "KPLER_OWNERSHIP_ENABLED", False)
        if not enabled:
            self.stderr.write(
                "Live Kpler ownership enrichment is disabled (KPLER_OWNERSHIP_ENABLED is false). "
                "Exiting without making network calls."
            )
            return

        # 2. Monthly quota guard
        cap = getattr(settings, "KPLER_OWNERSHIP_MONTHLY_IMO_CAP", 400)
        now = timezone.now()
        checked_this_month = Vessel.objects.filter(
            ownership_checked_at__year=now.year,
            ownership_checked_at__month=now.month,
        ).count()

        if checked_this_month >= cap:
            self.stdout.write(
                self.style.WARNING(
                    f"Monthly quota limit reached ({checked_this_month}/{cap} IMOs enriched in current calendar month). Stopping."
                )
            )
            return

        # 3. Select candidate IMOs
        max_imos = options.get("max_imos", 50)
        refresh_days = options.get("refresh_days", 30)
        imos_opt = options.get("imos")

        if imos_opt:
            clean_imos = _validate_and_dedup_imos(imos_opt)
        else:
            cutoff = now - timedelta(days=refresh_days)
            raw_imos = (
                Opportunity.objects.filter(vessel__imo__isnull=False)
                .exclude(stage__in=CLOSED_STAGES)
                .filter(
                    models.Q(vessel__ownership_checked_at__isnull=True)
                    | models.Q(vessel__ownership_checked_at__lt=cutoff)
                )
                .order_by("-score")
                .values_list("vessel__imo", flat=True)
            )
            seen = set()
            clean_imos = []
            for imo in raw_imos:
                if imo and len(imo) == 7 and imo.isdigit() and imo not in seen:
                    seen.add(imo)
                    clean_imos.append(imo)
            clean_imos = clean_imos[:max_imos]

        if not clean_imos:
            self.stdout.write("No candidate vessels found needing ownership enrichment.")
            return

        # Guard against exceeding remaining monthly quota
        remaining_cap = cap - checked_this_month
        if len(clean_imos) > remaining_cap:
            self.stdout.write(
                self.style.WARNING(
                    f"Capping request from {len(clean_imos)} to {remaining_cap} IMOs to stay within monthly cap of {cap}."
                )
            )
            clean_imos = clean_imos[:remaining_cap]

        if is_dry_run:
            self.stdout.write(self.style.WARNING("=== [DRY-RUN] Live network calls disabled (pass --apply to execute) ==="))
            self.stdout.write(f"Total candidate IMOs that would be queried: {len(clean_imos)}")
            self.stdout.write(f"Current monthly usage: {checked_this_month}/{cap} IMOs")
            self.stdout.write("First 10 IMOs:")
            for idx, imo in enumerate(clean_imos[:10], start=1):
                v = Vessel.objects.filter(imo=imo).first()
                v_name = v.name if v else "Unknown"
                self.stdout.write(f"  {idx}. IMO {imo} - {v_name}")
            return

        # 4. Execute live batches
        pause_seconds = options.get("pause_seconds", 2)
        batch_size = 20
        batches = [clean_imos[i : i + batch_size] for i in range(0, len(clean_imos), batch_size)]

        self.stdout.write(f"Processing {len(clean_imos)} IMOs in {len(batches)} batch(es)...")

        total_vessels_updated = 0
        total_companies_created = 0
        total_relationships_created = 0
        total_relationships_closed = 0
        total_leads_rescored = 0
        errors = 0

        for b_idx, batch in enumerate(batches, start=1):
            self.stdout.write(f"Batch {b_idx}/{len(batches)}: Querying {len(batch)} IMO(s)...")
            try:
                nodes = fetch_vessels(batch)
            except KplerAccessError as exc:
                self.stderr.write(self.style.ERROR(f"Kpler Access Error: {exc}"))
                self.stderr.write("Stopping run immediately. Nothing saved for this batch.")
                break
            except AuthenticationError as exc:
                self.stderr.write(self.style.ERROR(f"Authentication Error: {exc}"))
                self.stderr.write("Stopping run immediately. Nothing saved for this batch.")
                break
            except CallLimitError as exc:
                self.stderr.write(self.style.ERROR(f"Rate Limit Error: {exc}"))
                self.stderr.write("Stopping run immediately. Nothing saved for this batch.")
                break
            except KplerError as exc:
                self.stderr.write(self.style.ERROR(f"Provider Error: {exc}"))
                self.stderr.write("Stopping run immediately. Nothing saved for this batch.")
                break
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Unexpected Error: {exc}"))
                self.stderr.write("Stopping run immediately. Nothing saved for this batch.")
                break

            returned_imos = set()
            for node in nodes:
                try:
                    parsed = parse_vessel_node(node)
                    if parsed.get("imo"):
                        returned_imos.add(parsed["imo"])
                    res = enrich_vessel(parsed, source="kpler:live")
                    if res:
                        total_vessels_updated += 1
                        total_companies_created += res["created_companies"]
                        total_relationships_created += res["created_relationships"]
                        total_relationships_closed += res["closed_relationships"]
                        total_leads_rescored += res["rescored_opportunities"]
                except Exception as exc:
                    errors += 1
                    logger.error("Error saving enriched vessel: %s", exc)

            # Mark ownership checked for any IMO in batch that wasn't returned in provider nodes
            missing_imos = set(batch) - returned_imos
            if missing_imos:
                Vessel.objects.filter(imo__in=missing_imos).update(ownership_checked_at=timezone.now())

            if b_idx < len(batches):
                time.sleep(pause_seconds)

        self.stdout.write(self.style.SUCCESS("\n=== Live Ownership Enrichment Summary ==="))
        self.stdout.write(f"IMOs requested             : {len(clean_imos)}")
        self.stdout.write(f"Vessels updated            : {total_vessels_updated}")
        self.stdout.write(f"Companies created          : {total_companies_created}")
        self.stdout.write(f"Relationships created      : {total_relationships_created}")
        self.stdout.write(f"Relationships closed       : {total_relationships_closed}")
        self.stdout.write(f"Leads rescored             : {total_leads_rescored}")
        self.stdout.write(f"Errors                     : {errors}")

