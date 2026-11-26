/**
 * apps/web/static/web/js/outreach-logic.js
 * Pure helpers for the "Send mail" button on the vessel page. No DOM and no network calls.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dayText(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/**
 * Line under a contact showing the last mail sent to that company about this vessel.
 * @param {{sent_at?: string, sent_by?: string, count?: number, status?: string, template?: string}|null|undefined} entry
 * @returns {string} "" when nothing was sent
 */
export function lastMailedText(entry) {
    if (!entry || !entry.sent_at) return "";
    const day = dayText(entry.sent_at);
    if (!day) return "";
    let text = `Last mailed ${day}`;
    if (entry.sent_by) text += ` by ${entry.sent_by}`;
    if (entry.template) text += ` (${entry.template})`;
    const count = Number(entry.count) || 0;
    if (count > 1) text += `, ${count} mails in all`;
    if (entry.status === "test") text += " · test mode, not delivered";
    return text;
}

/**
 * Index the log rows by company id.
 * @param {Array<{company_id: number}>} rows
 * @returns {Object<string, Object>}
 */
export function indexByCompany(rows) {
    const map = {};
    for (const row of rows || []) map[String(row.company_id)] = row;
    return map;
}

/**
 * Banner shown in the dialog when no mail server is configured.
 * @param {string} mode "live" | "test"
 * @param {string} [redirectTo] the safe-test address, when set
 * @returns {string}
 */
export function modeNote(mode, redirectTo = "") {
    if (redirectTo) return `Safe test: every mail is delivered to ${redirectTo} instead of the company, so nobody outside your team is contacted.`;
    return mode === "test"
        ? "Test mode: no mail server is set up, so this mail is only printed in the server window and is not delivered."
        : "";
}

/**
 * Text for the placeholders the server could not fill.
 * @param {string[]} names
 * @returns {string}
 */
export function placeholderNote(names) {
    if (!names || names.length === 0) return "";
    return `Replace these before sending: ${names.map((n) => `{{${n}}}`).join(", ")}`;
}

/**
 * Label of the main button in the dialog.
 * @param {{busy?: boolean, needsConfirm?: boolean}} s
 * @returns {string}
 */
export function sendLabel({ busy = false, needsConfirm = false } = {}) {
    if (busy) return "Sending…";
    return needsConfirm ? "Send anyway" : "Send mail";
}

/**
 * Short label for the badge on a template card.
 * @param {string} kind first_contact | reminder | other
 * @param {string} [fallback] label sent by the server
 * @returns {string}
 */
export function kindLabel(kind, fallback = "") {
    const labels = { first_contact: "First mail", reminder: "Reminder", other: "Other" };
    return labels[kind] || fallback || "Other";
}
