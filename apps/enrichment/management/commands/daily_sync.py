"""
Daily data sync, meant to run once a day from a scheduler (02:00 UTC).

  1. MarineTraffic Expected Arrivals: one extended call per active port
     (SGSIN, AEFJR), skipped for a port already fetched in the last day.
     A 429 is retried once after a wait.
  2. Kpler AIS Latest per port (only when INGEST_REFRESH_AIS_ENABLED is on).
  3. Kpler owners and managers for today's share of the monthly IMO allowance,
     taken from the priority queue (anchorage first, then score, then size).
     The share kept for the "Look up owner" button is never spent here.

Nothing is sent to any company. Use --dry-run to see the plan without any call.
"""
import time
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.enrichment.refresh import (
    MAX_ERROR_CHARS, MODE, _run_ais_step, parse_ownership_report, parse_report, sanitize,
)
from apps.ports.models import Port
from services import quota_service
from services.ownership_queue import ownership_queue


class Command(BaseCommand):
    help = "Daily sync: arrivals per port, optional AIS, and today's share of owner lookups."

    def add_arguments(self, parser):
        parser.add_argument("--port", action="append", dest="ports", help="UN/LOCODE (repeatable). Default: all active ports with a MarineTraffic id.")
        parser.add_argument("--dry-run", action="store_true", help="Show the plan; make no call and change nothing.")
        parser.add_argument("--skip-arrivals", action="store_true")
        parser.add_argument("--skip-ownership", action="store_true")
        parser.add_argument("--retry-wait", dest="retry_wait", type=int, default=120, help="Seconds to wait before the one retry after a 429.")
        parser.add_argument("--port-pause", dest="port_pause", type=int, default=120, help="Seconds to wait between ports.")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        now = timezone.now()
        self.stdout.write(f"Daily sync {now:%Y-%m-%d %H:%M} UTC{' (dry run)' if dry else ''}")
        ports = self._ports(opts["ports"])
        failures = 0

        if not opts["skip_arrivals"]:
            for i, port in enumerate(ports):
                if i and not dry and opts["port_pause"] > 0:
                    time.sleep(opts["port_pause"])
                failures += self._arrivals(port, dry, opts["retry_wait"])
                self._ais(port, dry)

        if not opts["skip_ownership"]:
            failures += self._ownership(dry, now)

        self.stdout.write("Done." if not failures else f"Done with {failures} problem(s).")
        if failures:
            raise CommandError(f"{failures} step(s) failed. See the lines above.")

    # ------------------------------------------------------------------
    def _ports(self, codes):
        qs = Port.objects.filter(active=True, marinetraffic_port_id__isnull=False)
        if codes:
            qs = qs.filter(un_locode__in=codes)
        return list(qs.order_by("un_locode"))

    def _arrivals(self, port, dry, retry_wait):
        code = port.un_locode
        if not quota_service.arrivals_allowed(code):
            nxt = quota_service.arrivals_next_allowed(code)
            self.stdout.write(f"[{code}] Arrivals skipped: fetched recently, next allowed {nxt:%Y-%m-%d %H:%M} UTC.")
            return 0
        if dry:
            self.stdout.write(f"[{code}] Would fetch expected arrivals (1 extended call).")
            return 0
        for attempt in (1, 2):
            out = StringIO()
            try:
                call_command("ingest_expected_arrivals", mode=MODE, live=True, ports=[code],
                             stdout=out, stderr=StringIO())
            except CommandError as exc:
                msg = sanitize(exc)[:MAX_ERROR_CHARS]
                if attempt == 1 and "429" in msg:
                    self.stdout.write(f"[{code}] Provider says too many calls (429). Retrying once in {retry_wait}s.")
                    time.sleep(max(0, retry_wait))
                    continue
                self.stderr.write(f"[{code}] Arrivals failed: {msg}")
                return 1
            s = parse_report(out.getvalue())
            self.stdout.write(
                f"[{code}] Arrivals: {s.get('raw_rows', 0)} read, {s.get('vessels_created', 0)} new vessels, "
                f"{s.get('opportunities_created', 0)} new leads, {s.get('opportunities_updated', 0)} updated.")
            return 0
        return 1

    def _ais(self, port, dry):
        if dry or not getattr(settings, "INGEST_REFRESH_AIS_ENABLED", True):
            return
        s = {}
        _run_ais_step(port.un_locode, s)
        if s.get("ais_error"):
            self.stderr.write(f"[{port.un_locode}] AIS problem: {s['ais_error']}")
        elif s.get("ais_skipped"):
            self.stdout.write(f"[{port.un_locode}] AIS skipped: {s['ais_skipped']}.")
        else:
            self.stdout.write(f"[{port.un_locode}] AIS: {s.get('ais_in_anchorage', 0)} in anchorage, {s.get('ais_opportunities_created', 0)} new leads.")

    def _ownership(self, dry, now):
        if not getattr(settings, "KPLER_OWNERSHIP_ENABLED", False):
            self.stdout.write("Owner lookup skipped: switched off (KPLER_OWNERSHIP_ENABLED).")
            return 0
        st = quota_service.ownership_status(now)
        budget = st["auto_budget_today"]
        self.stdout.write(
            f"Owner lookups this period: {st['used']}/{st['cap']} used; today's sync share {budget}, "
            f"{st['manual_left_today']} kept for the button.")
        if budget <= 0:
            self.stdout.write("Owner lookup skipped: nothing left in today's share.")
            return 0
        imos = ownership_queue(budget, now=now)
        if not imos:
            self.stdout.write("Owner lookup skipped: no vessel needs a lookup.")
            return 0
        if dry:
            self.stdout.write(f"Would look up {len(imos)} IMO(s): {', '.join(imos)}")
            return 0
        out, err = StringIO(), StringIO()
        try:
            call_command("enrich_ownership", live=True, apply=True, imos=imos, max_imos=len(imos),
                         pause_seconds=0, stdout=out, stderr=err)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(f"Owner lookup failed: {sanitize(exc)[:MAX_ERROR_CHARS]}")
            return 1
        problem = err.getvalue().strip().splitlines()
        s = parse_ownership_report(out.getvalue())
        self.stdout.write(f"Owner lookup: {len(imos)} requested. {s}")
        if problem:
            self.stderr.write(f"Owner lookup problem: {sanitize(problem[0])[:MAX_ERROR_CHARS]}")
            return 1
        return 0
