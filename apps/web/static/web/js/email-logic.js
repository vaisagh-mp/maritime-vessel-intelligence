/**
 * apps/web/static/web/js/email-logic.js
 * Pure helpers for the Email templates and Email log pages (no DOM, tested with node --test).
 */

/**
 * Query string for the history API.
 * @param {{q?: string, status?: string, page?: number}} s
 * @returns {string}
 */
export function historyQuery({ q = "", status = "", page = 1 } = {}) {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (status) p.set("status", status);
    if (page > 1) p.set("page", String(page));
    const text = p.toString();
    return text ? `?${text}` : "";
}

/**
 * Label and style for the result of one mail.
 * @param {string} status sent | test | failed
 * @returns {{label: string, tone: string}}
 */
export function statusInfo(status) {
    if (status === "sent") return { label: "Sent", tone: "ok" };
    if (status === "test") return { label: "Test, not delivered", tone: "test" };
    return { label: "Failed", tone: "bad" };
}

/**
 * Text inserted into a field at the cursor when a placeholder chip is pressed.
 * @param {string} value current text
 * @param {number} start selection start
 * @param {number} end selection end
 * @param {string} name placeholder name, e.g. "vessel_name"
 * @returns {{value: string, cursor: number}}
 */
export function insertPlaceholder(value, start, end, name) {
    const token = `{{${name}}}`;
    const s = Number.isInteger(start) ? start : value.length;
    const e = Number.isInteger(end) ? end : s;
    return { value: value.slice(0, s) + token + value.slice(e), cursor: s + token.length };
}

/**
 * Placeholders in a text that are not in the allowed list (the server leaves those as typed).
 * @param {string} text
 * @param {string[]} allowed
 * @returns {string[]}
 */
export function unknownPlaceholders(text, allowed) {
    const found = new Set();
    for (const m of String(text || "").matchAll(/\{\{\s*([a-z_]+)\s*\}\}/g)) {
        if (!allowed.includes(m[1])) found.add(m[1]);
    }
    return [...found].sort();
}

/**
 * "Page 2 of 5" or an empty string when there is only one page.
 * @param {number} page
 * @param {number} pages
 * @returns {string}
 */
export function pagerText(page, pages) {
    return pages > 1 ? `Page ${page} of ${pages}` : "";
}
