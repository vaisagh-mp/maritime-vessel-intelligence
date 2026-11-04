/**
 * apps/web/static/web/js/board-logic.js
 * Pure functions for lead board state, query serialization, ETA formatting, and summaries.
 * Contains NO DOM operations and NO network calls (fetch).
 */

export const VALID_BANDS = ["HOT", "HIGH", "MEDIUM", "LOW"];

export const VALID_STAGES = [
    "detected",
    "qualifying",
    "ready_for_review",
    "contacted",
    "replied",
    "quote_requested",
    "quoted",
    "negotiation",
    "won",
    "lost",
    "follow_up_later",
];

export const STAGE_LABELS = {
    detected: "Detected",
    qualifying: "Qualifying",
    ready_for_review: "Ready For Review",
    contacted: "Contacted",
    replied: "Replied",
    quote_requested: "Quote Requested",
    quoted: "Quoted",
    negotiation: "Negotiation",
    won: "Won",
    lost: "Lost",
    follow_up_later: "Follow Up Later",
};

export const ZONES = [
    { id: "24h", label: "24 hour priority" },
    { id: "72h", label: "72 hour approach" },
    { id: "anchorage", label: "Anchorage / port" },
];

/**
 * Parse a URL search string into a normalized filters object.
 * Invalid or unknown parameters are ignored.
 * @param {string} search - e.g. "?port=1&band=HOT&q=tanker&inbound=1"
 * @returns {Object} normalized filters
 */
export function readFilters(search) {
    const params = new URLSearchParams(search || "");
    const filters = {
        port: "",
        band: "",
        stage: "",
        q: "",
        sort: "-score",
        inbound: false,
        closed: false,
    };

    const portVal = params.get("port");
    if (portVal && /^\d+$/.test(portVal.trim())) {
        filters.port = portVal.trim();
    }

    const bandVal = (params.get("band") || "").trim().toUpperCase();
    if (VALID_BANDS.includes(bandVal)) {
        filters.band = bandVal;
    }

    const stageVal = (params.get("stage") || "").trim().toLowerCase();
    if (VALID_STAGES.includes(stageVal)) {
        filters.stage = stageVal;
    }

    const qVal = params.get("q");
    if (qVal) {
        filters.q = qVal.trim();
    }

    const sortVal = params.get("sort");
    if (sortVal === "eta" || sortVal === "-score") {
        filters.sort = sortVal;
    }

    const inboundVal = params.get("inbound");
    if (inboundVal === "1" || inboundVal === "true") {
        filters.inbound = true;
    }

    const closedVal = params.get("closed");
    if (closedVal === "1" || closedVal === "true") {
        filters.closed = true;
    }

    return filters;
}

/**
 * Convert a filters object into a URL query string for history.replaceState.
 * Omits default/empty parameters.
 * @param {Object} filters
 * @returns {string} e.g. "?port=1&band=HOT" or ""
 */
export function toQuery(filters) {
    if (!filters) {
        return "";
    }
    const params = new URLSearchParams();

    if (filters.port) {
        params.set("port", filters.port);
    }
    if (filters.band && VALID_BANDS.includes(filters.band)) {
        params.set("band", filters.band);
    }
    if (filters.stage && VALID_STAGES.includes(filters.stage)) {
        params.set("stage", filters.stage);
    }
    if (filters.q) {
        params.set("q", filters.q);
    }
    if (filters.sort && filters.sort !== "-score") {
        params.set("sort", filters.sort);
    }
    if (filters.inbound) {
        params.set("inbound", "1");
    }
    if (filters.closed) {
        params.set("closed", "1");
    }

    const qs = params.toString();
    return qs ? `?${qs}` : "";
}

/**
 * Build query string for API requests for a specific zone column.
 * Always sends open=true unless closed is on.
 * @param {Object} filters
 * @param {string} zone - "24h" | "72h" | "anchorage"
 * @returns {string}
 */
export function apiQueryForZone(filters, zone) {
    const params = new URLSearchParams();

    if (zone) {
        params.set("zone", zone);
    }
    params.set("ordering", filters && filters.sort === "eta" ? "eta" : "-score");

    if (!filters || !filters.closed) {
        params.set("open", "true");
    }

    if (filters) {
        if (filters.inbound) {
            params.set("is_inbound", "true");
        }
        if (filters.port) {
            params.set("port", filters.port);
        }
        if (filters.band) {
            params.set("band", filters.band);
        }
        if (filters.stage) {
            params.set("stage", filters.stage);
        }
        if (filters.q) {
            params.set("q", filters.q);
        }
    }

    const qs = params.toString();
    return qs ? `?${qs}` : "";
}

/**
 * Build query string for CSV export endpoint (/api/v1/opportunities/export/).
 * Excludes zone, page, and page_size.
 * @param {Object} filters
 * @returns {string}
 */
export function exportQuery(filters) {
    const params = new URLSearchParams();

    params.set("ordering", filters && filters.sort === "eta" ? "eta" : "-score");

    if (!filters || !filters.closed) {
        params.set("open", "true");
    }

    if (filters) {
        if (filters.inbound) {
            params.set("is_inbound", "true");
        }
        if (filters.port) {
            params.set("port", filters.port);
        }
        if (filters.band) {
            params.set("band", filters.band);
        }
        if (filters.stage) {
            params.set("stage", filters.stage);
        }
        if (filters.q) {
            params.set("q", filters.q);
        }
    }

    const qs = params.toString();
    return qs ? `?${qs}` : "";
}

/**
 * Format relative ETA text compared to nowMs.
 * @param {string|null} isoString - ISO datetime string
 * @param {number} [nowMs] - current timestamp in ms (defaults to Date.now())
 * @returns {string} "in 5 h", "in 2 d", "ETA passed", or "No ETA"
 */
export function etaRelative(isoString, nowMs = Date.now()) {
    if (!isoString) {
        return "No ETA";
    }
    const targetMs = new Date(isoString).getTime();
    if (isNaN(targetMs)) {
        return "No ETA";
    }

    const diffMs = targetMs - nowMs;
    if (diffMs <= 0) {
        return "ETA passed";
    }

    const oneHour = 3600 * 1000;
    const oneDay = 24 * oneHour;

    if (diffMs < oneDay) {
        const hours = Math.max(1, Math.round(diffMs / oneHour));
        return `in ${hours} h`;
    }

    const days = Math.max(1, Math.round(diffMs / oneDay));
    return `in ${days} d`;
}

/**
 * Convert eta_source code to human-readable label.
 * @param {string|null} source
 * @returns {string}
 */
export function etaSourceLabel(source) {
    if (!source) {
        return "";
    }
    if (source === "eta_calc") {
        return "provider calculated";
    }
    if (source === "ais_eta") {
        return "AIS declared";
    }
    return "";
}

/**
 * Calculate totals for summary strip from loaded cards.
 * @param {Array<Object>} items
 * @returns {{ total: number, hot: number, inbound: number }}
 */
export function summarise(items) {
    if (!Array.isArray(items)) {
        return { total: 0, hot: 0, inbound: 0 };
    }

    let hot = 0;
    let inbound = 0;

    for (const item of items) {
        if (item) {
            if (String(item.band || "").toUpperCase() === "HOT") {
                hot++;
            }
            if (item.is_inbound === true) {
                inbound++;
            }
        }
    }

    return {
        total: items.length,
        hot,
        inbound,
    };
}
