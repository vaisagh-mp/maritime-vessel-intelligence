"""Case-insensitive Company matching + VesselRelationship creation from
enrichment's management-data response."""
from apps.common.constants import (
    COMPANY_TYPE_MANAGER,
    COMPANY_TYPE_OWNER,
    RELATIONSHIP_ROLE_MANAGER,
    RELATIONSHIP_ROLE_OWNER,
)
from apps.companies.models import Company
from apps.relationships.models import VesselRelationship


def _match_or_create_company(name, company_type, email=None, website=None, address=None):
    existing = Company.objects.filter(name__iexact=name).first()
    if existing:
        return existing
    return Company.objects.create(
        name=name,
        company_type=company_type,
        email=email or "",
        website=website or "",
        address=address or "",
    )


def apply_management_data(vessel, management: dict, source: str):
    """Creates/links the manager and (if present and not a "-") the
    registered owner, via unverified VesselRelationship rows sourced from the
    data provider — never treated as a confirmed named decision-maker.
    """
    created_relationships = []

    if management.get("manager_name"):
        manager = _match_or_create_company(
            management["manager_name"],
            COMPANY_TYPE_MANAGER,
            email=management.get("manager_email"),
            website=management.get("manager_website"),
            address=management.get("manager_address"),
        )
        rel, _ = VesselRelationship.objects.get_or_create(
            vessel=vessel, company=manager, role=RELATIONSHIP_ROLE_MANAGER,
            defaults={"source": source, "verified": False},
        )
        created_relationships.append(rel)

    if management.get("registered_owner_name"):
        owner = _match_or_create_company(
            management["registered_owner_name"],
            COMPANY_TYPE_OWNER,
            email=management.get("registered_owner_email"),
            website=management.get("registered_owner_website"),
            address=management.get("registered_owner_address"),
        )
        rel, _ = VesselRelationship.objects.get_or_create(
            vessel=vessel, company=owner, role=RELATIONSHIP_ROLE_OWNER,
            defaults={"source": source, "verified": False},
        )
        created_relationships.append(rel)

    # Recalculate scores on all open Opportunities for this vessel — new
    # company data affects priority-manager, verified-contact, and
    # existing-relationship signals.
    from apps.common.constants import CLOSED_STAGES
    from apps.opportunities.models import Opportunity
    from services.opportunity_service import recalculate_score

    open_opps = Opportunity.objects.filter(vessel=vessel).exclude(stage__in=CLOSED_STAGES)
    for opp in open_opps:
        recalculate_score(opp)

    return created_relationships
