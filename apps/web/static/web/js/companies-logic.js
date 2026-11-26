/**
 * apps/web/static/web/js/companies-logic.js
 * Pure functions for the companies pages.
 * No DOM operations, no network calls — testable with node --test.
 */

/**
 * Default company list filters.
 * @returns {Object}
 */
export function defaultFilters() {
    return {
        q: "",
        country: "",
        type: "",
        role: "",
        has_open_leads: false,
        ordering: "name",
    };
}

/**
 * Count how many filters differ from defaults.
 * @param {Object} [filters]
 * @returns {number}
 */
export function activeFilterCount(filters) {
    if (!filters) return 0;
    let count = 0;
    if (filters.q && String(filters.q).trim() !== "") count += 1;
    if (filters.country && String(filters.country).trim() !== "") count += 1;
    if (filters.type && String(filters.type).trim() !== "") count += 1;
    if (filters.role && String(filters.role).trim() !== "") count += 1;
    if (Boolean(filters.has_open_leads)) count += 1;
    if (filters.ordering && filters.ordering !== "name") count += 1;
    return count;
}

/**
 * Parse URL search string into a normalized filters object.
 * @param {string} search
 * @returns {Object}
 */
export function readFilters(search) {
    const params = new URLSearchParams(search || "");
    const f = defaultFilters();

    const q = params.get("q");
    if (q) f.q = q.trim();

    const country = params.get("country");
    if (country) f.country = country.trim();

    const type = params.get("type");
    if (type) f.type = type.trim();

    const role = params.get("role");
    if (role) f.role = role.trim();

    const openLeads = params.get("has_open_leads");
    if (openLeads === "1" || openLeads === "true") f.has_open_leads = true;

    const ordering = params.get("ordering");
    if (ordering && ["-vessels", "vessels", "hottest", "name"].includes(ordering)) {
        f.ordering = ordering;
    }

    return f;
}

/**
 * Convert filters to URL query string (omitting defaults).
 * @param {Object} filters
 * @returns {string}
 */
export function toQuery(filters) {
    if (!filters) return "";
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.country) params.set("country", filters.country);
    if (filters.type) params.set("type", filters.type);
    if (filters.role) params.set("role", filters.role);
    if (filters.has_open_leads) params.set("has_open_leads", "1");
    if (filters.ordering && filters.ordering !== "name") params.set("ordering", filters.ordering);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
}

/**
 * Build query for the company overview API endpoint.
 * @param {Object} filters
 * @param {number} page
 * @param {number} pageSize
 * @returns {string}
 */
export function apiQuery(filters, page, pageSize) {
    const params = new URLSearchParams();
    if (filters) {
        if (filters.q) params.set("q", filters.q);
        if (filters.country) params.set("country", filters.country);
        if (filters.type) params.set("type", filters.type);
        if (filters.role) params.set("role", filters.role);
        if (filters.has_open_leads) params.set("has_open_leads", "true");
        params.set("ordering", filters.ordering || "name");
    }
    params.set("page", String(Math.max(1, Number(page) || 1)));
    params.set("page_size", String(pageSize));
    return `?${params.toString()}`;
}

/**
 * Capitalize and humanize a role key.
 * @param {string} role
 * @returns {string}
 */
export function roleLabel(role) {
    if (!role) return "";
    return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Build a compact summary of role counts like "8 managed, 4 owned".
 * @param {Object} roleCounts - {role: n}
 * @returns {Array<{role: string, label: string, count: number}>}
 */
export function roleChips(roleCounts) {
    if (!roleCounts || typeof roleCounts !== "object") return [];
    return Object.entries(roleCounts)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([role, count]) => ({
            role,
            label: roleLabel(role),
            count: Number(count) || 0,
        }));
}

/**
 * Page numbers to show in the pager, with "…" where pages are skipped.
 * Always shows the first page, the last page, and the pages next to the current one.
 * @param {number} current - current page (1-based)
 * @param {number} pages - total pages
 * @returns {Array<number|string>} e.g. [1, "…", 4, 5, 6, "…", 12]
 */
export function pageNumbers(current, pages) {
    const total = Math.max(1, Number(pages) || 1);
    const cur = Math.min(Math.max(1, Number(current) || 1), total);
    const wanted = new Set([1, total, cur - 1, cur, cur + 1]);
    const list = [...wanted].filter((n) => n >= 1 && n <= total).sort((a, b) => a - b);
    const out = [];
    for (let i = 0; i < list.length; i += 1) {
        if (i > 0 && list[i] - list[i - 1] > 1) {
            out.push(list[i] - list[i - 1] === 2 ? list[i] - 1 : "…");
        }
        out.push(list[i]);
    }
    return out;
}
