"""Shared enum-like constants used across domain apps."""

COMPANY_TYPE_OWNER = "owner"
COMPANY_TYPE_MANAGER = "manager"
COMPANY_TYPE_OPERATOR = "operator"
COMPANY_TYPE_BROKER = "broker"

COMPANY_TYPE_CHOICES = [
    (COMPANY_TYPE_OWNER, "Owner"),
    (COMPANY_TYPE_MANAGER, "Manager"),
    (COMPANY_TYPE_OPERATOR, "Operator"),
    (COMPANY_TYPE_BROKER, "Broker"),
]

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

PRIORITY_CHOICES = [
    (PRIORITY_HIGH, "High"),
    (PRIORITY_MEDIUM, "Medium"),
    (PRIORITY_LOW, "Low"),
]

RELATIONSHIP_ROLE_OWNER = "owner"
RELATIONSHIP_ROLE_MANAGER = "manager"
RELATIONSHIP_ROLE_OPERATOR = "operator"

RELATIONSHIP_ROLE_CHOICES = [
    (RELATIONSHIP_ROLE_OWNER, "Owner"),
    (RELATIONSHIP_ROLE_MANAGER, "Manager"),
    (RELATIONSHIP_ROLE_OPERATOR, "Operator"),
]

ZONE_72H = "72h"
ZONE_24H = "24h"
ZONE_ANCHORAGE = "anchorage"

ZONE_CHOICES = [
    (ZONE_72H, "72 Hour Approach"),
    (ZONE_24H, "24 Hour Priority"),
    (ZONE_ANCHORAGE, "Anchorage / Port"),
]

STAGE_DETECTED = "detected"
STAGE_QUALIFYING = "qualifying"
STAGE_READY_FOR_REVIEW = "ready_for_review"
STAGE_CONTACTED = "contacted"
STAGE_REPLIED = "replied"
STAGE_QUOTE_REQUESTED = "quote_requested"
STAGE_QUOTED = "quoted"
STAGE_NEGOTIATION = "negotiation"
STAGE_WON = "won"
STAGE_LOST = "lost"
STAGE_FOLLOW_UP_LATER = "follow_up_later"

OPPORTUNITY_STAGE_CHOICES = [
    (STAGE_DETECTED, "Detected"),
    (STAGE_QUALIFYING, "Qualifying"),
    (STAGE_READY_FOR_REVIEW, "Ready For Review"),
    (STAGE_CONTACTED, "Contacted"),
    (STAGE_REPLIED, "Replied"),
    (STAGE_QUOTE_REQUESTED, "Quote Requested"),
    (STAGE_QUOTED, "Quoted"),
    (STAGE_NEGOTIATION, "Negotiation"),
    (STAGE_WON, "Won"),
    (STAGE_LOST, "Lost"),
    (STAGE_FOLLOW_UP_LATER, "Follow Up Later"),
]

# Stages that mark an Opportunity as no longer "open" for dedup purposes.
CLOSED_STAGES = {STAGE_WON, STAGE_LOST}

# Vessel type exclusion blocklist lives in settings.VESSEL_TYPE_EXCLUSIONS so it
# can be overridden per-deployment without a code change.
