/**
 * apps/web/static/web/js/vessel-logic.js
 * Pure functional business logic for vessel detail rendering and data sanitization.
 * Free of DOM operations and network requests.
 */

// Navigation status code mapping according to AIS ITU-R M.1371 standards.
// Note: Navigation status codes 98 and 99 are provider-specific and unconfirmed.
const NAV_STATUS_MAP = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    14: "AIS-SART",
    15: "Undefined",
};

const PREFERRED_ROLE_ORDER = [
    "registered_owner",
    "beneficial_owner",
    "commercial_manager",
    "technical_manager",
    "ism_manager",
    "operator",
    "owner",
    "manager",
];

const PORT_AREA_LABELS = {
    inbound: "Inbound",
    in_port: "In Port",
    anchorage: "Anchorage",
    anchorage_bound: "Anchorage Bound",
    unknown: "Unknown",
};

/**
 * Convert numerical or string navigation status code to descriptive label.
 * @param {number|string|null} code
 * @returns {string}
 */
export function navStatusLabel(code) {
    if (code === null || code === undefined || code === "") {
        return "\u2014";
    }
    const num = Number(code);
    if (!isNaN(num) && NAV_STATUS_MAP[num] !== undefined) {
        return NAV_STATUS_MAP[num];
    }
    return `Unknown (code ${code})`;
}

/**
 * Format port area string into user-facing label.
 * @param {string|null} value
 * @returns {string}
 */
export function portAreaLabel(value) {
    if (!value || typeof value !== "string") {
        return "\u2014";
    }
    const key = value.trim().toLowerCase();
    return PORT_AREA_LABELS[key] || value;
}

/**
 * Validate and safely format an external website URL.
 * Only http:// and https:// URLs are permitted.
 * If no scheme is present but the string resembles a domain name, https:// is prepended.
 * Returns { href: string, text: string } or null for dangerous or invalid values.
 * @param {string|null} text
 * @returns {{ href: string, text: string }|null}
 */
export function safeHttpUrl(text) {
    if (!text || typeof text !== "string") return null;
    const trimmed = text.trim();
    if (!trimmed) return null;

    // Check if an explicit scheme is provided
    const schemeMatch = trimmed.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/);
    if (schemeMatch) {
        const scheme = schemeMatch[1].toLowerCase();
        if (scheme !== "http" && scheme !== "https") {
            return null;
        }
        try {
            const u = new URL(trimmed);
            if (u.protocol === "http:" || u.protocol === "https:") {
                return { href: u.href, text: trimmed };
            }
        } catch {
            return null;
        }
        return null;
    }

    // No scheme provided: verify it resembles a domain name
    if (/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(\/.*)?$/.test(trimmed)) {
        try {
            const u = new URL(`https://${trimmed}`);
            if (u.protocol === "https:" && u.hostname.includes(".")) {
                return { href: u.href, text: trimmed };
            }
        } catch {
            return null;
        }
    }

    return null;
}

/**
 * Validate and format an email into a safe mailto: URI.
 * Enforces exactly one '@', no whitespace, no angle brackets, and no control characters.
 * @param {string|null} text
 * @returns {string|null}
 */
export function safeMailto(text) {
    if (!text || typeof text !== "string") return null;
    const trimmed = text.trim();
    if (!trimmed) return null;

    // Enforce exactly one '@'
    const atMatches = trimmed.match(/@/g);
    if (!atMatches || atMatches.length !== 1) {
        return null;
    }

    // Forbid whitespace, angle brackets, and control characters
    if (/[\s<>\x00-\x1f\x7f]/.test(trimmed)) {
        return null;
    }

    const [localPart, domainPart] = trimmed.split("@");
    if (!localPart || !domainPart || !domainPart.includes(".")) {
        return null;
    }

    return `mailto:${trimmed}`;
}

/**
 * Group vessel relationships by role according to preferred display order.
 * Unknown roles are placed at the end.
 * @param {Array<Object>} relationships
 * @returns {Array<{ role: string, roleLabel: string, items: Array<Object> }>}
 */
export function groupContacts(relationships) {
    if (!Array.isArray(relationships) || relationships.length === 0) {
        return [];
    }

    const groupMap = new Map();
    for (const rel of relationships) {
        if (!rel) continue;
        const role = rel.role || "unknown";
        if (!groupMap.has(role)) {
            const roleLabel = rel.role_label || role.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
            groupMap.set(role, {
                role,
                roleLabel,
                items: [],
            });
        }
        groupMap.get(role).items.push(rel);
    }

    const groups = Array.from(groupMap.values());

    groups.sort((a, b) => {
        const idxA = PREFERRED_ROLE_ORDER.indexOf(a.role);
        const idxB = PREFERRED_ROLE_ORDER.indexOf(b.role);

        if (idxA !== -1 && idxB !== -1) {
            return idxA - idxB;
        }
        if (idxA !== -1) return -1;
        if (idxB !== -1) return 1;
        return a.role.localeCompare(b.role);
    });

    return groups;
}

/**
 * Calculate vessel age from year built.
 * e.g. (2009, 2026) -> "2009, 17 years"
 * @param {number|string|null} yearBuilt
 * @param {number|null} [nowYear]
 * @returns {string}
 */
export function vesselAge(yearBuilt, nowYear = null) {
    if (yearBuilt === null || yearBuilt === undefined || yearBuilt === "") {
        return "\u2014";
    }
    const y = Number(yearBuilt);
    if (isNaN(y) || y <= 0) {
        return "\u2014";
    }

    const currentYear = Number(nowYear) || new Date().getFullYear();
    const age = currentYear - y;
    if (age < 0) {
        return String(y);
    }
    const unit = age === 1 ? "year" : "years";
    return `${y}, ${age} ${unit}`;
}

/**
 * Calculate age in whole hours of a given ISO timestamp compared to reference time.
 * @param {string|null} isoString
 * @param {number|null} [nowMs]
 * @returns {number|null}
 */
export function positionAgeHours(isoString, nowMs = null) {
    if (!isoString) return null;
    const time = new Date(isoString).getTime();
    if (isNaN(time)) return null;

    const reference = nowMs !== null && nowMs !== undefined ? Number(nowMs) : Date.now();
    const diffMs = Math.max(0, reference - time);
    return Math.floor(diffMs / (1000 * 60 * 60));
}

/**
 * Generate OpenStreetMap URL for geographic coordinates.
 * @param {number|string|null} lat
 * @param {number|string|null} lon
 * @returns {string|null}
 */
export function osmUrl(lat, lon) {
    if (lat === null || lat === undefined || lon === null || lon === undefined) {
        return null;
    }
    const nLat = Number(lat);
    const nLon = Number(lon);
    if (isNaN(nLat) || isNaN(nLon)) {
        return null;
    }
    return `https://www.openstreetmap.org/?mlat=${nLat}&mlon=${nLon}#map=12/${nLat}/${nLon}`;
}

/**
 * Format latitude or longitude to 5 decimal places.
 * @param {number|string|null} value
 * @returns {string}
 */
export function formatCoord(value) {
    if (value === null || value === undefined || value === "") {
        return "\u2014";
    }
    const n = Number(value);
    if (isNaN(n)) {
        return "\u2014";
    }
    return n.toFixed(5);
}

/**
 * Format numerical dimensions to one decimal place with unit suffix.
 * @param {number|string|null} value
 * @param {string} [unit="m"]
 * @returns {string}
 */
export function formatMetres(value, unit = "m") {
    if (value === null || value === undefined || value === "") {
        return "\u2014";
    }
    const n = Number(value);
    if (isNaN(n) || n === 0) {
        return "\u2014";
    }
    return `${n.toFixed(1)} ${unit}`;
}

/**
 * Format numbers with thousands separators; return em dash if 0 or null.
 * @param {number|string|null} value
 * @returns {string}
 */
export function formatNumber(value) {
    if (value === null || value === undefined || value === "") {
        return "\u2014";
    }
    const n = Number(value);
    if (isNaN(n) || n === 0) {
        return "\u2014";
    }
    return n.toLocaleString("en-US");
}

/**
 * Format date string into YYYY-MM-DD.
 * @param {string|null} value
 * @returns {string}
 */
export function formatDate(value) {
    if (!value) return "\u2014";
    try {
        const d = new Date(value);
        if (isNaN(d.getTime())) return String(value);
        return d.toISOString().split("T")[0];
    } catch {
        return String(value);
    }
}

/**
 * Format datetime into YYYY-MM-DD HH:mm UTC.
 * @param {string|null} value
 * @returns {string}
 */
export function formatDateTimeUtc(value) {
    if (!value) return "\u2014";
    try {
        const d = new Date(value);
        if (isNaN(d.getTime())) return String(value);
        const y = d.getUTCFullYear();
        const m = String(d.getUTCMonth() + 1).padStart(2, "0");
        const day = String(d.getUTCDate()).padStart(2, "0");
        const h = String(d.getUTCHours()).padStart(2, "0");
        const min = String(d.getUTCMinutes()).padStart(2, "0");
        return `${y}-${m}-${day} ${h}:${min} UTC`;
    } catch {
        return String(value);
    }
}

/**
 * One line saying who confirmed an owner/manager link and when.
 * @param {{verified?: boolean, verified_by_name?: string, last_verified_date?: string|null}} rel
 * @returns {string} e.g. "Confirmed by Asha Rao on 2026-11-24", or "" when not verified
 */
export function verificationText(rel) {
    if (!rel || !rel.verified) return "";
    const who = rel.verified_by_name ? ` by ${rel.verified_by_name}` : "";
    const when = rel.last_verified_date ? ` on ${formatDate(rel.last_verified_date)}` : "";
    return `Confirmed${who}${when}`;
}

/**
 * What to tell the user about the owner lookup for a vessel.
 * @param {string|null|undefined} checkedAt ISO timestamp of the last lookup, if any
 * @param {boolean} hasData true when owners or managers are already shown
 * @returns {string}
 */
export function ownerLookupText(checkedAt, hasData) {
    if (!checkedAt) return "Owner not looked up yet.";
    const day = formatDate(checkedAt);
    return hasData ? `Owner data last checked on ${day}.` : `Checked on ${day}, no data returned.`;
}
