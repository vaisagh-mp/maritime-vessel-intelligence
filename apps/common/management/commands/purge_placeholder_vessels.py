"""Remove vessels whose MMSI starts with 99 and that nobody is using.

MMSI 99xxxxxxx is reserved for aids to navigation (buoys, beacons). Separately,
enrichment creates a placeholder MMSI "99<imo>" when it meets an IMO it has no
vessel for. Both kinds are noise on the board.

A vessel is removed only if it has NO leads and NO company relationships.
Anything with a lead or a relationship is kept and counted as protected, so
ownership data or human work is never lost. With --include-untouched-leads a
vessel that has leads is also removed, but only if every lead is still at
"detected" with no notes and no stage changes, and it has no relationships. Observations of a removed vessel go
with it. Dry-run by default.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.common.constants import STAGE_DETECTED
from apps.vessels.models import Vessel


def leads_untouched(vessel):
    """True if every lead is still 'detected' with no notes and no stage changes."""
    return all(
        o.stage == STAGE_DETECTED and not o.notes.exists() and not o.stage_changes.exists()
        for o in vessel.opportunities.all()
    )


class Command(BaseCommand):
    help = "Remove unused MMSI-99 vessels (aids to navigation / placeholders). Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-untouched-leads", action="store_true",
            help="Also remove vessels whose leads are all still 'detected' with no notes or stage changes.",
        )
        parser.add_argument("--apply", action="store_true", help="Actually delete. Without it nothing changes.")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        removable, protected = [], []
        for v in Vessel.objects.filter(mmsi__startswith="99").iterator():
            has_leads = v.opportunities.exists()
            if v.relationships.exists() or (
                has_leads and not (opts["include_untouched_leads"] and leads_untouched(v))
            ):
                protected.append(v)
            else:
                removable.append(v.pk)
        deleted = 0
        if apply and removable:
            with transaction.atomic():
                for i in range(0, len(removable), 500):
                    deleted += Vessel.objects.filter(pk__in=removable[i:i + 500]).delete()[0]
        self.stdout.write(f"Mode: {'APPLY' if apply else 'DRY-RUN (nothing deleted)'}")
        self.stdout.write(f"MMSI-99 vessels found: {len(removable) + len(protected)}")
        self.stdout.write(f"Protected (has a lead or a relationship, kept): {len(protected)}")
        for v in protected[:20]:
            self.stdout.write(f"  kept: id={v.pk} MMSI={v.mmsi} IMO={v.imo} name={v.name}")
        self.stdout.write(f"Vessels to remove: {len(removable)}")
        if apply:
            self.stdout.write(f"Rows deleted (all tables): {deleted}")
        else:
            self.stdout.write("Re-run with --apply to delete.")
