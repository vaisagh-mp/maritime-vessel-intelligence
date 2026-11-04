"""One-off, idempotent clean-up of the live Port table for the Kpler pilot.

    python manage.py setup_pilot_ports            # dry run: shows what would change
    python manage.py setup_pilot_ports --apply    # makes the changes

What it does:
  1. Port Rashid: un_locode AEPRA -> AEDXB (the correct UN/LOCODE).
  2. Only the pilot ports (Singapore SGSIN, Fujairah AEFJR) stay active; every
     other port is set inactive. Nothing is deleted.
  3. Vessels whose imo is a placeholder ("0", "") are set to NULL.
  4. Reports (never deletes) suspected junk vessels: aids to navigation
     (MMSI starting 99). Delete these by hand through the admin.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.ports.models import Port
from apps.vessels.models import Vessel

PILOT_LOCODES = {"SGSIN", "AEFJR"}
LOCODE_FIXES = {"AEPRA": "AEDXB"}  # old -> correct
PILOT_MARINETRAFFIC_PORT_IDS = {"SGSIN": 290, "AEFJR": 790}


class Command(BaseCommand):
    help = "Fix Port Rashid's UN/LOCODE, restrict active ports to the pilot, set MarineTraffic IDs, clean placeholder IMOs."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (default is a dry run).")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        mode = "APPLYING" if apply else "DRY RUN (use --apply to write)"
        self.stdout.write(self.style.WARNING(f"setup_pilot_ports: {mode}"))

        with transaction.atomic():
            self._fix_locodes(apply)
            self._set_active_ports(apply)
            self._set_marinetraffic_port_ids(apply)
            self._clean_imos(apply)
            self._report_junk()
            if not apply:
                transaction.set_rollback(True)

    def _fix_locodes(self, apply):
        for old, new in LOCODE_FIXES.items():
            port = Port.objects.filter(un_locode=old).first()
            if port is None:
                self.stdout.write(f"  locode: no port with {old} (nothing to fix)")
                continue
            if Port.objects.filter(un_locode=new).exclude(pk=port.pk).exists():
                self.stdout.write(self.style.ERROR(
                    f"  locode: {port.name} has {old} but another port already uses {new}; "
                    "resolve by hand in the admin."))
                continue
            self.stdout.write(f"  locode: {port.name}: {old} -> {new}")
            if apply:
                port.un_locode = new
                port.save(update_fields=["un_locode", "updated_at"])

    def _set_active_ports(self, apply):
        found = set(Port.objects.filter(un_locode__in=PILOT_LOCODES).values_list("un_locode", flat=True))
        for missing in sorted(PILOT_LOCODES - found):
            self.stdout.write(self.style.ERROR(
                f"  active: pilot port {missing} does not exist in the Port table; add it in the admin."))
        for port in Port.objects.all():
            should_be_active = port.un_locode in PILOT_LOCODES
            if port.active != should_be_active:
                self.stdout.write(f"  active: {port} -> {'ACTIVE' if should_be_active else 'inactive'}")
                if apply:
                    port.active = should_be_active
                    port.save(update_fields=["active", "updated_at"])

    def _set_marinetraffic_port_ids(self, apply):
        for locode, mt_id in PILOT_MARINETRAFFIC_PORT_IDS.items():
            port = Port.objects.filter(un_locode=locode).first()
            if port is None:
                continue
            if port.marinetraffic_port_id != mt_id:
                self.stdout.write(f"  marinetraffic_port_id: {port.name} ({locode}) -> {mt_id}")
                if apply:
                    port.marinetraffic_port_id = mt_id
                    port.save(update_fields=["marinetraffic_port_id", "updated_at"])

    def _clean_imos(self, apply):
        bad = Vessel.objects.filter(imo__in=["0", ""])
        count = bad.count()
        self.stdout.write(f"  imo: {count} vessel(s) with a placeholder IMO -> NULL")
        if apply and count:
            bad.update(imo=None)

    def _report_junk(self):
        junk = Vessel.objects.filter(mmsi__startswith="99")
        self.stdout.write(f"  junk: {junk.count()} suspected aid-to-navigation vessel(s) (MMSI 99*), "
                          "not deleted; remove via the admin:")
        for v in junk[:20]:
            self.stdout.write(f"        id={v.pk} MMSI={v.mmsi} name={v.name!r}")
