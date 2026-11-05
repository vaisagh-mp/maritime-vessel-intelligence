"""
Recompute lead score, band, zone and reason for all open opportunities.

Usage:
    python manage.py rescore_opportunities            # dry run: shows before/after and top 10 changes
    python manage.py rescore_opportunities --apply    # saves changes in an atomic transaction

Rules:
    - Only processes OPEN opportunities (never won or lost).
    - Prints before and after band counts (HOT, HIGH, MEDIUM, LOW).
    - Prints the 10 biggest changes (vessel name, old score, new score).
    - Does not change stage.
    - Does not write stage history.
    - Idempotent: second run changes nothing.
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.common.constants import (
    CLOSED_STAGES,
    PORT_AREA_ANCHORAGE_BOUND,
    ZONE_ANCHORAGE,
    ZONE_ANCHORAGE_BOUND,
)
from apps.opportunities.models import Opportunity
from services.opportunity_service import classify_zone_by_eta
from services.scoring_service import calculate_score_and_reason, get_band


class Command(BaseCommand):
    help = "Recompute score, band, zone, and rationale for all open opportunities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Apply the score updates in a single database transaction. Default is dry-run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Explicitly run in dry-run mode (default).",
        )

    def handle(self, *args, **options):
        apply_changes = options.get("apply", False) and not options.get("dry_run", False)
        mode = "APPLY" if apply_changes else "DRY-RUN (no changes persisted)"

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Rescoring Opportunities [{mode}] ==="))

        open_opps = (
            Opportunity.objects
            .exclude(stage__in=CLOSED_STAGES)
            .select_related("vessel", "port")
            .order_by("id")
        )
        total_open = open_opps.count()
        self.stdout.write(f"Total open opportunities to evaluate: {total_open}\n")

        before_bands = Counter()
        after_bands = Counter()
        changes = []
        updates = []

        for opp in open_opps:
            old_score = opp.score
            old_band = opp.band
            old_zone = opp.zone
            before_bands[old_band] += 1

            # Zone re-evaluation:
            # 1. If latest observation physically observed at anchorage, keep/upgrade to anchorage
            # 2. If latest observation was anchorage_bound, zone is anchorage_bound (unless already anchorage)
            # 3. Else if ETA is known, classify by ETA (unless already anchorage)
            new_zone = old_zone
            latest_obs = opp.vessel.observations.first()
            if latest_obs:
                if latest_obs.port_area == "anchorage":
                    new_zone = ZONE_ANCHORAGE
                elif latest_obs.port_area in ("anchorage_bound", PORT_AREA_ANCHORAGE_BOUND):
                    if old_zone != ZONE_ANCHORAGE:
                        new_zone = ZONE_ANCHORAGE_BOUND
                elif opp.eta is not None and old_zone != ZONE_ANCHORAGE:
                    new_zone = classify_zone_by_eta(opp.eta)
            elif opp.eta is not None and old_zone != ZONE_ANCHORAGE:
                new_zone = classify_zone_by_eta(opp.eta)

            opp.zone = new_zone

            # Recalculate score and reason
            new_score, new_reason = calculate_score_and_reason(opp)
            new_band = get_band(new_score)
            after_bands[new_band] += 1

            delta = abs(new_score - old_score)
            changes.append({
                "id": opp.id,
                "vessel_name": opp.vessel.name or "Unknown",
                "old_score": old_score,
                "new_score": new_score,
                "delta": delta,
                "old_zone": old_zone,
                "new_zone": new_zone,
                "old_band": old_band,
                "new_band": new_band,
            })

            if apply_changes:
                opp.score = new_score
                opp.zone = new_zone
                opp.lead_reason = new_reason
                updates.append(opp)

        # Print Before and After band distribution
        self.stdout.write(self.style.SUCCESS("Before Band Counts:"))
        for band in ["HOT", "HIGH", "MEDIUM", "LOW"]:
            self.stdout.write(f"  {band:<8}: {before_bands.get(band, 0)}")

        self.stdout.write(self.style.SUCCESS("\nAfter Band Counts:"))
        for band in ["HOT", "HIGH", "MEDIUM", "LOW"]:
            self.stdout.write(f"  {band:<8}: {after_bands.get(band, 0)}")

        # Print Top 10 Changes
        changes.sort(key=lambda x: (x["delta"], x["new_score"]), reverse=True)
        top_10 = changes[:10]

        self.stdout.write(self.style.SUCCESS("\nTop 10 Score Changes:"))
        self.stdout.write(f"{'Vessel Name':<30} {'Old Score':<10} {'New Score':<10} {'Change':<8}")
        self.stdout.write("-" * 60)
        for c in top_10:
            diff_str = f"{c['new_score'] - c['old_score']:+d}"
            self.stdout.write(f"{c['vessel_name'][:28]:<30} {c['old_score']:<10} {c['new_score']:<10} {diff_str:<8}")

        # If --apply, save in a single transaction
        if apply_changes and updates:
            with transaction.atomic():
                Opportunity.objects.bulk_update(
                    updates,
                    fields=["score", "zone", "lead_reason", "updated_at"],
                    batch_size=500,
                )
            self.stdout.write(self.style.SUCCESS(f"\nSuccessfully applied updates to {len(updates)} opportunities."))
        else:
            self.stdout.write(self.style.WARNING("\n[DRY-RUN] No records were modified. Run with --apply to persist changes."))

