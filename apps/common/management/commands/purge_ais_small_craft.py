"""Remove vessels (and their leads) that an older AIS ingest created without a known size.

Dry-run by default. A vessel is removed only if ALL of these hold:
  * GRT is unknown;
  * every observation of it came from kpler:ais_latest;
  * it has no company relationships;
  * every lead on it is still at stage "detected" with no notes and no stage changes.
Anything else is kept and counted as protected.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.common.constants import SOURCE_KPLER_AIS_LATEST, STAGE_DETECTED
from apps.vessels.models import Vessel


def is_removable(vessel):
    if vessel.grt is not None:
        return False
    sources = set(vessel.observations.values_list("source", flat=True).distinct())
    if sources != {SOURCE_KPLER_AIS_LATEST}:
        return False
    if vessel.relationships.exists():
        return False
    for opp in vessel.opportunities.all():
        if opp.stage != STAGE_DETECTED or opp.notes.exists() or opp.stage_changes.exists():
            return False
    return True


class Command(BaseCommand):
    help = "Remove AIS-created vessels/leads with unknown size and no human work. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually delete. Without it nothing changes.")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        candidates = Vessel.objects.filter(
            grt__isnull=True, observations__source=SOURCE_KPLER_AIS_LATEST
        ).distinct()
        removable, protected = [], 0
        for v in candidates.iterator():
            if is_removable(v):
                removable.append(v.pk)
            else:
                protected += 1
        from apps.opportunities.models import Opportunity
        leads = Opportunity.objects.filter(vessel_id__in=removable).count()
        deleted = 0
        if apply and removable:
            with transaction.atomic():
                for i in range(0, len(removable), 500):
                    deleted += Vessel.objects.filter(pk__in=removable[i:i + 500]).delete()[0]
        self.stdout.write(f"Mode: {'APPLY' if apply else 'DRY-RUN (nothing deleted)'}")
        self.stdout.write(f"Candidates (AIS, size unknown): {len(removable) + protected}")
        self.stdout.write(f"Protected (kept): {protected}")
        self.stdout.write(f"Vessels to remove: {len(removable)}")
        self.stdout.write(f"Leads to remove: {leads}")
        if apply:
            self.stdout.write(f"Rows deleted (all tables): {deleted}")
        else:
            self.stdout.write("Re-run with --apply to delete.")
