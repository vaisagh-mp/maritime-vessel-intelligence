"""
Runs the expected-arrivals discovery scan for every active Port.

Uses DataDocked's port-calls-by-port?search_type=expected endpoint, which
provides a forward-looking list of expected vessels per port — giving genuine
early warning (72h+) unlike the area-scan approach (which only catches vessels
already inside the geofence, ~1–2h out).

Cost: 50 credits per page. Run on its own separate schedule — NOT bundled
with run_discovery. Recommended schedule: daily.

    0 6 * * *  cd /path/to/project && .venv/bin/python manage.py run_expected_arrivals

Or, once Celery is enabled, schedule tasks.expected_arrivals.run_expected_arrivals
via Celery Beat on its own queue, separate from the discovery beat task.
"""
from django.core.management.base import BaseCommand

from tasks.expected_arrivals import run_expected_arrivals


class Command(BaseCommand):
    help = (
        "Poll DataDocked's port-calls-by-port (expected) endpoint for every active "
        "port and upsert vessels/opportunities with ETA-based zone classification. "
        "Run separately from run_discovery — this endpoint costs 50 credits/page."
    )

    def handle(self, *args, **options):
        results = run_expected_arrivals()

        total_new_vessels = 0
        total_new_opportunities = 0
        for r in results:
            total_new_vessels += r["new_vessels"]
            total_new_opportunities += r["new_opportunities"]
            self.stdout.write(
                f"{r['port']}: seen={r['seen']} new_vessels={r['new_vessels']} "
                f"new_opportunities={r['new_opportunities']} excluded={r['excluded']} "
                f"errors={r['errors']}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Expected-arrivals complete — "
                f"{total_new_vessels} new vessel(s), "
                f"{total_new_opportunities} new opportunity(-ies)."
            )
        )
