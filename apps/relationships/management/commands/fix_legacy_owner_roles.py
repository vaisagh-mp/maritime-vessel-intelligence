"""One-off cleanup command to close duplicate legacy 'owner' relationships created by Kpler enrichment."""
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.common.constants import (
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
)
from apps.relationships.models import VesselRelationship

logger = logging.getLogger("vessel_intel")


class Command(BaseCommand):
    help = (
        "Closes legacy 'owner' relationship rows created by Kpler that now have a matching "
        "'registered_owner' row for the same vessel and company."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Persist changes to the database. Default is dry-run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Run in dry-run mode without modifying the database (default).",
        )

    def handle(self, *args, **options):
        apply_changes = options.get("apply", False) and not options.get("dry_run", False)
        mode = "APPLY" if apply_changes else "DRY-RUN (no changes persisted)"

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Fix Legacy Owner Roles [{mode}] ==="))

        # Query candidates: current relationships with source starting with/containing 'kpler' and role 'owner'
        legacy_candidates = VesselRelationship.objects.filter(
            role=RELATIONSHIP_ROLE_OWNER,
            is_current=True,
            source__icontains="kpler",
        ).select_related("vessel", "company")

        duplicates_to_close = []
        for rel in legacy_candidates:
            has_matching_reg_owner = VesselRelationship.objects.filter(
                vessel=rel.vessel,
                company=rel.company,
                role=RELATIONSHIP_ROLE_REGISTERED_OWNER,
                is_current=True,
            ).exists()

            if has_matching_reg_owner:
                duplicates_to_close.append(rel)

        total_found = len(duplicates_to_close)
        self.stdout.write(
            f"Found {total_found} legacy Kpler 'owner' relationship(s) with matching 'registered_owner'."
        )

        for idx, rel in enumerate(duplicates_to_close, start=1):
            v_name = rel.vessel.name if rel.vessel else f"Vessel #{rel.vessel_id}"
            c_name = rel.company.name if rel.company else f"Company #{rel.company_id}"
            self.stdout.write(
                f"  {idx}. Rel ID {rel.id}: Vessel {rel.vessel_id} ({v_name}) | "
                f"Company {rel.company_id} ({c_name}) | source={rel.source}"
            )

        if not duplicates_to_close:
            self.stdout.write(self.style.SUCCESS("No duplicate legacy owner relationships found to close."))
            return

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY-RUN] {total_found} relationship(s) would be closed (is_current=False, end_date=today). "
                    "Run with --apply to execute."
                )
            )
            return

        today = timezone.now().date()
        closed_count = 0
        with transaction.atomic():
            for rel in duplicates_to_close:
                rel.is_current = False
                rel.end_date = today
                rel.save(update_fields=["is_current", "end_date", "updated_at"])
                closed_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n[APPLY complete] Successfully closed {closed_count} legacy duplicate 'owner' relationship(s)."
            )
        )

