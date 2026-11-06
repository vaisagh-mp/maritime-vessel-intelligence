"""Orchestrates vessel enrichment — particulars, management and ownership."""
import logging
import re
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from apps.common.constants import (
    CLOSED_STAGES,
    COMPANY_TYPE_MANAGER,
    COMPANY_TYPE_OPERATOR,
    COMPANY_TYPE_OWNER,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
)
from apps.companies.models import Company
from apps.opportunities.models import Opportunity
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from services.opportunity_service import recalculate_score

logger = logging.getLogger("vessel_intel")

_COMMON_SUFFIXES = {
    "LTD",
    "LIMITED",
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "SA",
    "NV",
    "BV",
    "LLC",
    "PLC",
    "CO",
    "COMPANY",
    "GMBH",
    "AG",
    "PTE",
    "KS",
    "AS",
    "OOO",
    "SL",
    "SRL",
}


def normalize_company_name(name: str) -> str:
    """Normalize company name for fuzzy/clean matching:

    Uppercase, strip punctuation, collapse whitespace, strip common legal suffixes.
    """
    if not name:
        return ""
    s = name.upper()
    s = re.sub(r"[.,/#!$%^&*;:{}=\-_`~()'\"]", " ", s)
    tokens = s.split()
    filtered = [t for t in tokens if t not in _COMMON_SUFFIXES]
    return " ".join(filtered) if filtered else " ".join(tokens)


def match_company(name: str, country: Optional[str]) -> Optional[Company]:
    """Match an existing company by normalized name plus country."""
    norm_name = normalize_company_name(name)
    norm_country = (country or "").strip().upper()
    if not norm_name:
        return None

    # Search candidates
    qs = Company.objects.all()
    if norm_country:
        for comp in qs.filter(country__iexact=norm_country):
            if normalize_company_name(comp.name) == norm_name:
                return comp

    # Fallback to any company where country is blank or matches
    for comp in qs:
        if normalize_company_name(comp.name) == norm_name:
            if not norm_country or not comp.country or comp.country.upper() == norm_country:
                return comp

    return None


@transaction.atomic
def enrich_vessel(parsed_or_id: Any, source: str = "kpler") -> Optional[Dict[str, Any]]:
    """Enrich vessel particulars, companies, and relationships from parsed Kpler node.

    Idempotent, one transaction per vessel.
    Also maintains backwards-compatibility for integer vessel_id calls (legacy stub).
    """
    if isinstance(parsed_or_id, (int, str)) and str(parsed_or_id).isdigit():
        vessel_id = int(parsed_or_id)
        Vessel.objects.get(pk=vessel_id)
        logger.info(
            "enrich_vessel called for vessel_id=%s — no provider configured; "
            "Kpler implementation arrives in Steps 4 to 8.",
            vessel_id,
        )
        return {
            "vessel_id": vessel_id,
            "location": None,
            "management": None,
            "status": "no_provider_configured",
        }

    parsed = parsed_or_id
    if not isinstance(parsed, dict):
        return None

    imo = parsed.get("imo")
    particulars = parsed.get("particulars") or {}
    parties = parsed.get("parties") or []

    vessel = None
    if imo:
        vessel = Vessel.objects.filter(imo=imo).first()
    if not vessel and particulars.get("mmsi"):
        vessel = Vessel.objects.filter(mmsi=particulars["mmsi"]).first()

    if not vessel:
        mmsi = particulars.get("mmsi") or (f"99{imo}" if imo else None)
        if mmsi:
            vessel, _ = Vessel.objects.get_or_create(
                mmsi=mmsi,
                defaults={
                    "imo": imo,
                    "name": particulars.get("name") or f"IMO {imo}",
                },
            )
        else:
            logger.warning("Vessel not found for IMO=%s MMSI=%s", imo, particulars.get("mmsi"))
            return None

    # 1. Update Vessel Particulars (static fields overwrite, nulls never overwrite)
    if particulars.get("name"):
        vessel.name = particulars["name"]
    if particulars.get("callsign"):
        vessel.callsign = particulars["callsign"]
    if particulars.get("ship_id"):
        vessel.ship_id = particulars["ship_id"]
    if particulars.get("flag"):
        vessel.flag = particulars["flag"]
    if particulars.get("vessel_type"):
        vessel.vessel_type = particulars["vessel_type"]
    if particulars.get("vessel_size_segment"):
        vessel.vessel_size_segment = particulars["vessel_size_segment"]
    if particulars.get("year_built") is not None:
        vessel.year_built = particulars["year_built"]
    if particulars.get("grt") is not None:
        vessel.grt = particulars["grt"]
    if particulars.get("dwt") is not None:
        vessel.dwt = particulars["dwt"]
    if particulars.get("length") is not None:
        vessel.length = particulars["length"]
    if particulars.get("beam") is not None:
        vessel.beam = particulars["beam"]
    if particulars.get("draught") is not None:
        vessel.draught = particulars["draught"]
    if particulars.get("last_dry_dock"):
        vessel.last_dry_dock = particulars["last_dry_dock"]
    if particulars.get("last_renewal_survey"):
        vessel.last_renewal_survey = particulars["last_renewal_survey"]
    if imo and not vessel.imo:
        vessel.imo = imo

    # Always mark ownership_checked_at even when no parties
    vessel.ownership_checked_at = timezone.now()
    vessel.save()

    created_companies = 0
    updated_companies = 0
    created_relationships = 0
    closed_relationships = 0

    # 2. Match or create companies and link relationships
    for party in parties:
        role = party.get("role")
        party_name = party.get("name")
        if not role or not party_name:
            continue

        party_country = party.get("country")
        company = match_company(party_name, party_country)

        if company:
            # Fill empty fields only (never overwrite user-edited data)
            comp_updated = False
            fields_to_update = []
            if not company.website and party.get("website"):
                company.website = party["website"]
                fields_to_update.append("website")
                comp_updated = True
            if not company.email and party.get("email"):
                company.email = party["email"]
                fields_to_update.append("email")
                comp_updated = True
            if not company.address and party.get("address"):
                company.address = party["address"]
                fields_to_update.append("address")
                comp_updated = True
            if not company.country and party_country:
                company.country = party_country
                fields_to_update.append("country")
                comp_updated = True
            if comp_updated:
                company.save(update_fields=fields_to_update + ["updated_at"])
                updated_companies += 1
        else:
            # Determine company type
            if role in (
                RELATIONSHIP_ROLE_OWNER,
                RELATIONSHIP_ROLE_REGISTERED_OWNER,
                RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
            ):
                company_type = COMPANY_TYPE_OWNER
            elif role == RELATIONSHIP_ROLE_OPERATOR:
                company_type = COMPANY_TYPE_OPERATOR
            else:
                company_type = COMPANY_TYPE_MANAGER

            # Priority rule: medium only when BOTH website and email are present, else low (never high)
            has_both_contacts = bool(party.get("website") and party.get("email"))
            priority = PRIORITY_MEDIUM if has_both_contacts else PRIORITY_LOW

            company = Company.objects.create(
                name=party_name,
                company_type=company_type,
                priority=priority,
                country=party_country or "",
                address=party.get("address") or "",
                website=party.get("website") or "",
                email=party.get("email") or "",
            )
            created_companies += 1

        # 3. Manage relationships
        # Check if there is an existing current relationship for this role
        existing_current = VesselRelationship.objects.filter(
            vessel=vessel, role=role, is_current=True
        ).first()

        start_date = party.get("start_date")
        end_date = party.get("end_date")

        if existing_current:
            if existing_current.company_id == company.id:
                # Same company again: changes nothing
                pass
            else:
                # Different company: close existing relationship and open new
                existing_current.is_current = False
                existing_current.end_date = start_date or end_date or timezone.now().date()
                existing_current.save(update_fields=["is_current", "end_date", "updated_at"])
                closed_relationships += 1

                rel, created = VesselRelationship.objects.update_or_create(
                    vessel=vessel,
                    company=company,
                    role=role,
                    defaults={
                        "is_current": True,
                        "source": source,
                        "verified": False,
                        "start_date": start_date,
                        "end_date": None,
                    },
                )
                if created:
                    created_relationships += 1
        else:
            rel, created = VesselRelationship.objects.update_or_create(
                vessel=vessel,
                company=company,
                role=role,
                defaults={
                    "is_current": True,
                    "source": source,
                    "verified": False,
                    "start_date": start_date,
                    "end_date": None,
                },
            )
            if created:
                created_relationships += 1

    # 4. Rescore open opportunities for this vessel (no stage change, no history row)
    open_opps = Opportunity.objects.filter(vessel=vessel).exclude(stage__in=CLOSED_STAGES)
    for opp in open_opps:
        recalculate_score(opp)

    return {
        "vessel": vessel,
        "created_companies": created_companies,
        "updated_companies": updated_companies,
        "created_relationships": created_relationships,
        "closed_relationships": closed_relationships,
        "rescored_opportunities": len(open_opps),
    }
