/**
 * apps/web/static/web/js/dashboard-logic.js
 * Pure functions for the Dashboard, priority lists and Business Developers page.
 * No DOM and no network calls, so they can be tested with node --test.
 */

const EM_DASH = "—";

/**
 * Stat cards for the Dashboard, in display order.
 * @param {Object} totals - the "totals" object from /api/v1/opportunities/summary/
 * @returns {Array<{key:string,label:string,value:number,href:string,tone:string}>}
 */
export function statCards(totals) {
    const t = totals || {};
    const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
    return [
        { key: "open", label: "Total leads", value: n(t.open), href: "/priority/all/", tone: "neutral" },
        { key: "hot", label: "HOT leads", value: n(t.hot), href: "/priority/all/?band=HOT", tone: "hot" },
        { key: "inbound", label: "Inbound leads", value: n(t.inbound), href: "/priority/all/?inbound=1", tone: "good" },
        { key: "zone_24h", label: "24 hour priority", value: n(t.zone_24h), href: "/priority/24h/", tone: "neutral" },
        { key: "zone_72h", label: "72 hour approach", value: n(t.zone_72h), href: "/priority/72h/", tone: "neutral" },
        { key: "anchorage", label: "At anchorage / port", value: n(t.anchorage), href: "/priority/anchorage/", tone: "neutral" },
        { key: "in_pipeline", label: "In pipeline", value: n(t.in_pipeline), href: "/priority/all/?stage=pipeline", tone: "neutral" },
        { key: "new_24h", label: "New in last 24 h", value: n(t.new_24h), href: "/priority/all/?new=1", tone: "neutral" },
    ];
}

/**
 * Add a port filter to a link when one is chosen.
 * @param {string} href
 * @param {string} portId
 */
export function withPort(href, portId) {
    if (!portId || !/^\d+$/.test(String(portId))) return href;
    const hasQuery = href.includes("?");
    return `${href}${hasQuery ? "&" : "?"}port=${portId}`;
}

/**
 * Widths (0 to 100) for the pipeline bars, relative to the biggest stage.
 * @param {Array<{stage:string,label:string,count:number}>} byStage
 */
export function stageBars(byStage) {
    const rows = Array.isArray(byStage) ? byStage : [];
    const max = rows.reduce((m, r) => Math.max(m, Number(r.count) || 0), 0);
    return rows.map((r) => {
        const count = Number(r.count) || 0;
        return {
            stage: r.stage,
            label: r.label,
            count,
            pct: max > 0 ? Math.max(count > 0 ? 4 : 0, Math.round((count / max) * 100)) : 0,
        };
    });
}

/**
 * Short text for how long a lead has been waiting, e.g. "26 h" or "2 d 3 h".
 * @param {number} hours
 */
export function waitingText(hours) {
    const h = Math.max(0, Math.floor(Number(hours) || 0));
    if (h < 48) return `${h} h`;
    const d = Math.floor(h / 24);
    const rest = h % 24;
    return rest ? `${d} d ${rest} h` : `${d} d`;
}

/**
 * "5 min ago", "3 h ago", "2 d ago", or an em dash for a missing time.
 * @param {string|null} iso
 * @param {number} [nowMs]
 */
export function timeAgo(iso, nowMs = Date.now()) {
    if (!iso) return EM_DASH;
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return EM_DASH;
    const sec = Math.max(0, Math.round((nowMs - t) / 1000));
    if (sec < 60) return "just now";
    const min = Math.round(sec / 60);
    if (min < 60) return `${min} min ago`;
    const hours = Math.round(min / 60);
    if (hours < 48) return `${hours} h ago`;
    return `${Math.round(hours / 24)} d ago`;
}

/**
 * Label for the "last data refresh" panel row.
 * @param {{status:string|null, finished_at:string|null}} entry
 */
export function refreshStatusText(entry, nowMs = Date.now()) {
    if (!entry || !entry.status) return "Not refreshed yet";
    const when = timeAgo(entry.finished_at, nowMs);
    return entry.status === "success" ? `Updated ${when}` : `Last attempt failed, ${when}`;
}

/**
 * API query for the Dashboard hot-leads table.
 * @param {"24h"|"hot"} tab
 * @param {string} portId
 * @param {number} [limit]
 */
export function dashboardTableQuery(tab, portId, limit = 10) {
    const params = new URLSearchParams();
    if (tab === "hot") {
        params.set("band", "HOT");
    } else {
        params.set("zone", "24h");
    }
    params.set("open", "true");
    params.set("ordering", "-score");
    params.set("page_size", String(limit));
    if (portId && /^\d+$/.test(String(portId))) params.set("port", String(portId));
    return `?${params.toString()}`;
}

/**
 * Add page and page size to an API query string.
 * @param {string} query - "" or "?a=b"
 */
export function withPaging(query, page, pageSize) {
    const params = new URLSearchParams((query || "").replace(/^\?/, ""));
    params.set("page", String(Math.max(1, Number(page) || 1)));
    params.set("page_size", String(pageSize));
    return `?${params.toString()}`;
}

/**
 * Text and button states for a pager.
 * @returns {{from:number,to:number,total:number,pages:number,page:number,hasPrev:boolean,hasNext:boolean}}
 */
export function pageInfo(total, page, pageSize) {
    const size = Math.max(1, Number(pageSize) || 25);
    const count = Math.max(0, Number(total) || 0);
    const pages = Math.max(1, Math.ceil(count / size));
    const current = Math.min(Math.max(1, Number(page) || 1), pages);
    const from = count === 0 ? 0 : (current - 1) * size + 1;
    const to = Math.min(count, current * size);
    return { from, to, total: count, pages, page: current, hasPrev: current > 1, hasNext: current < pages };
}

/**
 * Read the page number from a URL search string.
 */
export function readPage(search) {
    const p = new URLSearchParams(search || "").get("page");
    return p && /^\d+$/.test(p) && Number(p) >= 1 ? Number(p) : 1;
}

/**
 * Generate a random password for a new Business Developer.
 * Uses the supplied random source (crypto.getRandomValues in the browser).
 * Avoids look-alike characters. Always has upper, lower, digit and symbol.
 * @param {(arr:Uint32Array)=>Uint32Array} fill
 * @param {number} [length]
 */
export function generatePassword(fill, length = 14) {
    const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const lower = "abcdefghijkmnopqrstuvwxyz";
    const digits = "23456789";
    const symbols = "!@#$%&*?";
    const all = upper + lower + digits + symbols;
    const buf = fill(new Uint32Array(length));
    const pick = (set, i) => set[buf[i] % set.length];
    const chars = [pick(upper, 0), pick(lower, 1), pick(digits, 2), pick(symbols, 3)];
    for (let i = 4; i < length; i += 1) chars.push(pick(all, i));
    // Shuffle with a second draw so the guaranteed characters are not always first.
    const order = fill(new Uint32Array(length));
    return chars
        .map((c, i) => ({ c, k: order[i] }))
        .sort((a, b) => a.k - b.k)
        .map((o) => o.c)
        .join("");
}

/**
 * Filter the Business Developer rows by status text and search text.
 * @param {Array<Object>} rows
 * @param {{q:string,status:string}} f
 */
export function filterBds(rows, f) {
    const q = String((f && f.q) || "").trim().toLowerCase();
    const status = (f && f.status) || "";
    return (Array.isArray(rows) ? rows : []).filter((r) => {
        if (status === "active" && !r.is_active) return false;
        if (status === "inactive" && r.is_active) return false;
        if (!q) return true;
        return [r.username, r.full_name, r.email].some((v) => String(v || "").toLowerCase().includes(q));
    });
}

/**
 * Turn an API error body into one message per field.
 * @param {Object|null} data - e.g. {"email": ["Enter a valid email address."]}
 * @returns {Object<string,string>}
 */
export function fieldErrors(data) {
    const out = {};
    if (!data || typeof data !== "object") return out;
    for (const [key, val] of Object.entries(data)) {
        if (Array.isArray(val) && val.length) out[key] = String(val[0]);
        else if (typeof val === "string") out[key] = val;
    }
    return out;
}

/**
 * Format a date as "05 Nov 2026" (UTC) or an em dash.
 */
export function formatDate(iso) {
    if (!iso) return EM_DASH;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return EM_DASH;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${String(d.getUTCDate()).padStart(2, "0")} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/**
 * Plain lines for the Data freshness panel from /api/v1/ingest/status/.
 * @param {Object|null} status
 * @returns {string[]}
 */
export function allowanceLines(status) {
    if (!status) return [];
    const lines = [];
    const o = status.ownership;
    if (o && o.enabled === false) {
        lines.push("Owner lookup is switched off.");
    } else if (o) {
        lines.push(`Owner lookups this month: ${o.used} of ${o.cap} used (${o.remaining} left).`);
        lines.push(`Today: ${o.auto_budget_today} in the daily sync, ${o.manual_left_today} for the Look up owner button.`);
    }
    for (const a of status.arrivals || []) {
        lines.push(a.allowed_now
            ? `${a.port}: arrivals can be fetched now.`
            : `${a.port}: arrivals fetched, next call allowed ${formatWhen(a.next_allowed_at)}.`);
    }
    return lines;
}

function formatWhen(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "later";
    return `${String(d.getUTCDate()).padStart(2, "0")}/${String(d.getUTCMonth() + 1).padStart(2, "0")} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;
}
