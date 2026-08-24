"""Manually enrich one vessel by primary key — mirrors the
POST /api/v1/vessels/{id}/enrich/ endpoint for CLI/cron use."""
from django.core.management.base import BaseCommand, CommandError

from services.enrichment_service import enrich_vessel


class Command(BaseCommand):
    help = "Run ETA/location + management enrichment for a single Vessel by id."

    def add_arguments(self, parser):
        parser.add_argument("vessel_id", type=int)

    def handle(self, *args, **options):
        try:
            result = enrich_vessel(options["vessel_id"])
        except Exception as exc:  # noqa: BLE001 — surface any failure to the CLI clearly
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Enriched vessel {options['vessel_id']}: {result}"))
