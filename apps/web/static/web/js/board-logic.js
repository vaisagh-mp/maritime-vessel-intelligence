/**
 * apps/web/static/web/js/board-logic.js
 * Pure functions for lead board state, query serialization, ETA formatting, and summaries.
 * Contains NO DOM operations and NO network calls (fetch).
 */

import { STAGES } from "./stages.js";

export const VALID_BANDS = ["HOT", "HIGH", "MEDIUM", "LOW"];

export const VALID_STAGES = STAGES.map((s) => s.value);

// "pipeline" is not a real stage: it means every stage after first contact.
export const STAGE_FILTER_VALUES = [...VALID_STAGES, "pipeline"];

export const STAGE_LABELS = Object.fromEntries(STAGES.map((s) => [s.value, s.label]));

export const BOARD_COLUMNS = [
    { id: "24h", label: "24 hour priority" },
    { id: "72h", label: "72 hour approach" },
    { id: "anchorage", label: "Anchorage / port" },
];

export const ZONE_TO_COLUMN = {
    "24h": "24h",
    "72h": "72h",
    "anchorage": "anchorage",
    "anchorage_bound": "anchorage",
};

export function zoneToColumn(zone) {
    return ZONE_TO_COLUMN[zone] || "anchorage";
}

export const ZONES = [
    { id: "24h", label: "24 hour priority" },
    { id: "72h", label: "72 hour approach" },
    { id: "anchorage", label: "Anchorage / port" },
    { id: "anchorage_bound", label: "Anchorage bound" },
];

/**
 * Return a fresh default filters object.
 * Single source of truth for default board filters.
 * @returns {Object}
 */
export function defaultFilters() {
    return {
        port: "",
        band: "",
        stage: "",
        q: "",
        sort: "-score",
        inbound: false,
        isNew: false,
        closed: false,
    };
}

/**
 * Count how many filters differ from default settings.
 * Counting rules:
 * - sort counts as active only when different from "-score"
 * - stage counts as active only when non-empty
 * - search of only spaces is not active
 * @param {Object} [filters]
 * @returns {number}
 */
export function activeFilterCount(filters) {
    if (!filters) return 0;
    let count = 0;
    if (filters.port && String(filters.port).trim() !== "") count += 1;
    if (filters.band && String(filters.band).trim() !== "") count += 1;
    if (filters.stage && String(filters.stage).trim() !== "") count += 1;
    if (filters.q && String(filters.q).trim() !== "") count += 1;
    if (filters.sort && filters.sort !== "-score") count += 1;
    if (Boolean(filters.inbound)) count += 1;
    if (Boolean(filters.isNew)) count += 1;
    if (Boolean(filters.closed)) count += 1;
    return count;
}

/**
 * Check if the filters match the default settings.
 * @param {Object} [filters]
 * @returns {boolean}
 */
export function isDefault(filters) {
    return activeFilterCount(filters) === 0;
}

/**
 * Parse a URL search string into a normalized filters object.
 * Invalid or unknown parameters are ignored.
 * @param {string} search - e.g. "?port=1&band=HOT&q=tanker&inbound=1"
 * @returns {Object} normalized filters
 */
export function readFilters(search) {
    const params = new URLSearchParams(search || "");
    const filters = defaultFilters();

    const portVal = params.get("port");
    if (portVal && /^\d+$/.test(portVal.trim())) {
        filters.port = portVal.trim();
    }

    const bandVal = (params.get("band") || "").trim().toUpperCase();
    if (VALID_BANDS.includes(bandVal)) {
        filters.band = bandVal;
    }

    const stageVal = (params.get("stage") || "").trim().toLowerCase();
    if (STAGE_FILTER_VALUES.includes(stageVal)) {
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

    const newVal = params.get("new");
    if (newVal === "1" || newVal === "true") {
        filters.isNew = true;
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
    if (filters.stage && STAGE_FILTER_VALUES.includes(filters.stage)) {
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
    if (filters.isNew) {
        params.set("new", "1");
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
 * @param {string} zone - "24h" | "72h" | "anchorage" | "all" (all zones, no zone filter)
 * @returns {string}
 */
export function apiQueryForZone(filters, zone) {
    const params = new URLSearchParams();

    if (zone && zone !== "all") {
        params.set("zone", zone);
    }
    params.set("ordering", filters && filters.sort === "eta" ? "eta" : "-score");

    if (!filters || !filters.closed) {
        params.set("open", "true");
    }
    // Inbound leads whose ETA passed long ago are no longer a real 24h / 72h arrival.
    if ((zone === "24h" || zone === "72h") && !(filters && filters.closed)) {
        params.set("hide_stale", "true");
    }

    if (filters) {
        if (filters.inbound) {
            // "Inbound only" means vessels really on the way: not ones whose ETA has passed.
            params.set("is_inbound", "true");
            params.set("upcoming", "true");
        }
        if (filters.isNew) {
            params.set("new_hours", "24");
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
            // "Inbound only" means vessels really on the way: not ones whose ETA has passed.
            params.set("is_inbound", "true");
            params.set("upcoming", "true");
        }
        if (filters.isNew) {
            params.set("new_hours", "24");
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
 * True when an ETA exists and is already in the past.
 * @param {string|null} isoString
 * @param {number} [nowMs]
 * @returns {boolean}
 */
export function isEtaPassed(isoString, nowMs = Date.now()) {
    if (!isoString) return false;
    const t = new Date(isoString).getTime();
    return !isNaN(t) && t - nowMs <= 0;
}

/**
 * Badge text for a lead's arrival status, or "" when it has none.
 * An inbound lead whose ETA has passed is "Status unconfirmed", because the
 * saved data no longer says where the vessel really is.
 * @param {{is_inbound?: boolean, eta?: string|null}} item
 * @param {number} [nowMs]
 * @returns {string} "Inbound" | "Status unconfirmed" | ""
 */
export function inboundLabel(item, nowMs = Date.now()) {
    if (!item || !item.is_inbound) return "";
    return isEtaPassed(item.eta, nowMs) ? "Status unconfirmed" : "Inbound";
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
