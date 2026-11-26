/**
 * apps/web/static/web/js/latest-logic.js
 * Pure helpers for the "Latest arrivals" page. No DOM and no network calls.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Query string for /api/v1/opportunities/latest-arrivals/.
 * @param {{port?: string, band?: string, page?: number, date?: string}} f
 * @returns {string} "" or "?port=...&band=..."
 */
export function buildQuery({ port = "", band = "", page = 1, date = "" } = {}) {
    const q = new URLSearchParams();
    if (date) q.set("date", date);
    if (port) q.set("port", port);
    if (band) q.set("band", band);
    if (page > 1) q.set("page", String(page));
    const text = q.toString();
    return text ? `?${text}` : "";
}

/**
 * "24 Nov, 02:00 UTC" for an ISO timestamp, "" when it cannot be read.
 * @param {string|null|undefined} iso
 * @returns {string}
 */
export function utcText(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${hh}:${mm} UTC`;
}

/**
 * One line per port about its fetch on the chosen day, with the counts.
 * @param {{port: string, name: string, fetched_at: string|null, vessels?: number, with_owner?: number, with_manager?: number, approximate?: boolean}} fetch
 * @returns {string}
 */
export function fetchText(fetch) {
    const when = utcText(fetch && fetch.fetched_at);
    const name = `Port of ${(fetch && (fetch.name || fetch.port)) || "?"}`;
    if (!when) return `${name}: no live fetch on this date`;
    const vessels = Number(fetch.vessels) || 0;
    const owners = Number(fetch.with_owner) || 0;
    const managers = Number(fetch.with_manager) || 0;
    const text = `${name}: fetched ${when} \u00b7 ${vessels} vessel${vessels === 1 ? "" : "s"}`
        + ` \u00b7 ${owners} with owner data \u00b7 ${managers} with manager data`;
    return fetch.approximate ? `${text} (saved before history was kept, may be incomplete)` : text;
}

/**
 * The most recent fetch dates as short labels for quick buttons.
 * @param {string[]} dates ISO dates, newest first
 * @param {number} limit
 * @returns {Array<{value: string, label: string}>}
 */
export function dateChips(dates, limit = 7) {
    return (dates || []).slice(0, limit).map((value) => {
        const [y, m, d] = value.split("-").map(Number);
        return { value, label: `${d} ${MONTHS[(m || 1) - 1]}` };
    });
}

/**
 * Split a vessel's companies into owners and managers.
 * @param {Array<{group: string}>} companies
 * @returns {{owners: Array, managers: Array}}
 */
export function splitCompanies(companies) {
    const owners = [];
    const managers = [];
    for (const c of companies || []) {
        (c.group === "owner" ? owners : managers).push(c);
    }
    return { owners, managers };
}

/**
 * Second line under a company name, for example "Greece" or "Greece · mail@x.com".
 * @param {{country?: string}} company
 * @returns {string}
 */
export function companyMeta(company) {
    return (company && company.country) ? String(company.country) : "";
}

/**
 * "Page 2 of 5", or "" when there is one page.
 * @param {number} page
 * @param {number} pages
 * @returns {string}
 */
export function pageText(page, pages) {
    return pages > 1 ? `Page ${page} of ${pages}` : "";
}
