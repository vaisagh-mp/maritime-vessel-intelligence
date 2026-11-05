/**
 * apps/web/static/web/js/stages.js
 * Canonical shared opportunity stage definitions.
 * Mirrors OPPORTUNITY_STAGE_CHOICES and CLOSED_STAGES in apps/common/constants.py.
 */

export const STAGES = [
    { value: "detected", label: "Detected" },
    { value: "qualifying", label: "Qualifying" },
    { value: "ready_for_review", label: "Ready For Review" },
    { value: "contacted", label: "Contacted" },
    { value: "replied", label: "Replied" },
    { value: "quote_requested", label: "Quote Requested" },
    { value: "quoted", label: "Quoted" },
    { value: "negotiation", label: "Negotiation" },
    { value: "won", label: "Won" },
    { value: "lost", label: "Lost" },
    { value: "follow_up_later", label: "Follow Up Later" },
];

export const PIPELINE_ORDER = [
    "detected",
    "qualifying",
    "ready_for_review",
    "contacted",
    "replied",
    "quote_requested",
    "quoted",
    "negotiation",
    "won",
];

export const CLOSED_STAGE_VALUES = ["won", "lost"];
