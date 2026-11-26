"""
One-off cleanup of the INVENTED data that an early test fixture wrote into the
local database (fake vessels, fake companies, fake relationships).

The first version of ``kpler_sample.json`` was synthetic (made-up vessels such as
PACIFIC EXPLORER, NORDIC STAR, EASTERN PHOENIX and SEA BREEZE). Running
``enrich_ownership --from-file`` with it created fake rows and overwrote values on
one real vessel (IMO 9146297, really BLPL FAITH).

Order to use:
    1. python manage.py purge_fake_fixture_data --dry-run          (default; shows everything)
    2. python manage.py purge_fake_fixture_data --apply
    3. python manage.py enrich_ownership --from-file <path>/kpler_sample_trimmed.json
       (restores the real values on IMO 9146297 and IMO 9308766)
    4. python manage.py purge_fake_fixture_data --dry-run          (should find nothing)

Safety rules:
    - Only objects that match the known fake data EXACTLY are touched (fake IMO and
      MMSI and name; fake company names with source "kpler:file").
    - A fake vessel is deleted only if nothing else refers to it (no observations,
      no opportunities). Otherwise it is listed and left alone.
    - A fake company is deleted only if every relationship it has is one of the
      fake relationships being removed. A company a person linked elsewhere is kept.
    - Real vessels are never deleted. On a real vessel only the two survey dates
      that equal the invented values are cleared.
    - Dry-run by default. Idempotent.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.companies.models import Company
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel

FAKE_SOURCE = "kpler:file"

FAKE_COMPANY_NAMES = {
    "Bergen Marine AS",
    "Eastern Orient Holding Ltd",
    "Global Chartering Inc",
    "Nordic Tankers KS",
    "Pacific Holdings Corp",
    "Pacific Maritime Ltd",
    "Pacific Operations SA",
    "Pacific Shipmanagement Ltd",
    "Phoenix Shipping Lines Co",
}

# Vessels that exist only because of the fake fixture: (imo, mmsi, name)
FAKE_VESSELS_TO_DELETE = [
    ("9456789", "356123000", "EASTERN PHOENIX"),
    ("9876543", "636123000", "SEA BREEZE"),
]

# Real IMOs that the fake run touched. Their values are restored by running the
# real enrichment; here we only clear survey dates that equal the invented ones
# (Kpler has no dates for IMO 9146297, so "null never overwrites" would keep them).
FAKE_SURVEY_DATES = {
    "9146297": ("2023-05-15", "2023-05-20"),
}

# Real vessels the fake run renamed or re-valued; reported if still wrong.
FAKE_NAMES_ON_REAL_VESSELS = {
    "9146297": "PACIFIC EXPLORER",
    "9308766": "NORDIC STAR",
}


class Command(BaseCommand):
    help = "Remove the invented rows written by the early synthetic Kpler fixture (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", default=False,
                            help="Delete the listed rows in one transaction. Default is dry-run.")
        parser.add_argument("--dry-run", action="store_true", default=False,
                            help="Explicit dry-run (default).")

    def handle(self, *args, **options):
        apply_changes = options["apply"] and not options["dry_run"]
        mode = "APPLY" if apply_changes else "DRY-RUN (nothing is changed)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Purge fake fixture data [{mode}] ==="))

        # ---- fake vessels ----------------------------------------------------
        vessels_delete = []
        for imo, mmsi, name in FAKE_VESSELS_TO_DELETE:
            vessel = Vessel.objects.filter(imo=imo, mmsi=mmsi, name=name).first()
            if not vessel:
                continue
            blockers = []
            if vessel.observations.exists():
                blockers.append(f"{vessel.observations.count()} observation(s)")
            if vessel.opportunities.exists():
                blockers.append(f"{vessel.opportunities.count()} opportunity(ies)")
            if blockers:
                self.stdout.write(self.style.WARNING(
                    f"  KEEP vessel id {vessel.pk} {name} (IMO {imo}): referenced by {', '.join(blockers)}"))
            else:
                vessels_delete.append(vessel)
                self.stdout.write(f"  Vessel to delete: id {vessel.pk} {name} (IMO {imo}, MMSI {mmsi})")

        # ---- fake relationships and companies --------------------------------
        rels = list(
            VesselRelationship.objects
            .filter(source=FAKE_SOURCE, company__name__in=FAKE_COMPANY_NAMES)
            .select_related("company", "vessel")
        )
        rel_ids = {r.pk for r in rels}
        for r in rels:
            self.stdout.write(
                f"  Relationship to delete: id {r.pk} vessel {r.vessel.pk} ({r.vessel.name}) | "
                f"{r.role} | {r.company.name} | current={r.is_current}"
            )

        companies_delete = []
        for company in Company.objects.filter(name__in=FAKE_COMPANY_NAMES):
            other = [
                x for x in company.vessel_relationships.all()
                if x.pk not in rel_ids and x.vessel_id not in {v.pk for v in vessels_delete}
            ]
            if other:
                self.stdout.write(self.style.WARNING(
                    f"  KEEP company id {company.pk} {company.name}: "
                    f"{len(other)} relationship(s) that are not part of the fake set"))
            else:
                companies_delete.append(company)
                self.stdout.write(f"  Company to delete: id {company.pk} {company.name}")

        # ---- fake survey dates on real vessels ---------------------------------
        date_fixes = []
        for imo, (dock, survey) in FAKE_SURVEY_DATES.items():
            vessel = Vessel.objects.filter(imo=imo).first()
            if not vessel:
                continue
            fields = []
            if vessel.last_dry_dock and str(vessel.last_dry_dock) == dock:
                fields.append("last_dry_dock")
            if vessel.last_renewal_survey and str(vessel.last_renewal_survey) == survey:
                fields.append("last_renewal_survey")
            if fields:
                date_fixes.append((vessel, fields))
                self.stdout.write(
                    f"  Clear invented dates on vessel id {vessel.pk} ({vessel.name}): {', '.join(fields)}")

        # ---- real vessels still carrying fake values ----------------------------
        pending_restore = []
        for imo, fake_name in FAKE_NAMES_ON_REAL_VESSELS.items():
            vessel = Vessel.objects.filter(imo=imo, name=fake_name).first()
            if vessel:
                pending_restore.append(vessel)
                self.stdout.write(self.style.WARNING(
                    f"  Vessel id {vessel.pk} (IMO {imo}) still has the invented name {fake_name}. "
                    f"Run: python manage.py enrich_ownership --from-file "
                    f"integrations/kpler/tests/fixtures/kpler_sample_trimmed.json"))

        total = len(vessels_delete) + len(rels) + len(companies_delete) + len(date_fixes)
        if not total and not pending_restore:
            self.stdout.write(self.style.SUCCESS("Nothing to clean up."))
            return

        if apply_changes and total:
            with transaction.atomic():
                VesselRelationship.objects.filter(pk__in=rel_ids).delete()
                for company in companies_delete:
                    company.delete()
                for vessel in vessels_delete:
                    vessel.delete()
                for vessel, fields in date_fixes:
                    for f in fields:
                        setattr(vessel, f, None)
                    vessel.save(update_fields=fields + ["updated_at"])
            self.stdout.write(self.style.SUCCESS(
                f"[APPLY complete] {len(rels)} relationship(s), {len(companies_delete)} company(ies), "
                f"{len(vessels_delete)} vessel(s) deleted; dates cleared on {len(date_fixes)} vessel(s)."))
        elif total:
            self.stdout.write(self.style.WARNING(
                f"[DRY-RUN] Would delete {len(rels)} relationship(s), {len(companies_delete)} company(ies), "
                f"{len(vessels_delete)} vessel(s); clear dates on {len(date_fixes)} vessel(s). "
                f"Run with --apply."))
