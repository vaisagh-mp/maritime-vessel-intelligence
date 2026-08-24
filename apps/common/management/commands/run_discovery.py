"""
Runs the vessel-arrival discovery scan for every active Port.

Runnable via cron until Celery/Redis is wired in:
    */15 * * * *  cd /path/to/project && .venv/bin/python manage.py run_discovery

Or, once Celery is enabled, schedule tasks.discovery.run_discovery via Celery Beat.
"""
from django.core.management.base import BaseCommand

from tasks.discovery import run_discovery


class Command(BaseCommand):
    help = "Poll DataDocked for every active port and upsert vessels/observations/opportunities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--enrich-new",
            action="store_true",
            help=(
                "Also run enrichment inline for every newly-created vessel from this run. "
                "Off by default — discovery and enrichment stay on separate schedules so a "
                "large batch never fires many paid enrichment calls at once."
            ),
        )

    def handle(self, *args, **options):
        results = run_discovery()

        total_new_vessels = 0
        all_new_vessel_ids = []
        for r in results:
            total_new_vessels += r["new_vessels"]
            all_new_vessel_ids.extend(r["newly_created_vessel_ids"])
            self.stdout.write(
                f"{r['port']}: seen={r['seen']} new_vessels={r['new_vessels']} "
                f"new_opportunities={r['new_opportunities']} excluded={r['excluded']} "
                f"errors={r['errors']}"
            )

        self.stdout.write(self.style.SUCCESS(f"Discovery complete — {total_new_vessels} new vessel(s)."))

        if options["enrich_new"] and all_new_vessel_ids:
            from services.enrichment_service import enrich_vessel

            self.stdout.write(f"Enriching {len(all_new_vessel_ids)} new vessel(s)...")
            for vessel_id in all_new_vessel_ids:
                enrich_vessel(vessel_id)
            self.stdout.write(self.style.SUCCESS("Enrichment complete."))
