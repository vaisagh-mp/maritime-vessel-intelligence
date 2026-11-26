/**
 * apps/web/static/web/js/refresh-logic.js
 * Pure helpers for the "Refresh data (live)" button.
 * Contains NO DOM operations and NO network calls (fetch).
 */

export const LIVE_LABEL = "Refresh data (live)";

export const PORT_NAMES = {
    SGSIN: "Singapore",
    AEFJR: "Fujairah",
};

/**
 * Format whole seconds as m:ss, for example 72 -> "1:12".
 * @param {number} seconds
 * @returns {string}
 */
export function formatCountdown(seconds) {
    const total = Math.max(0, Math.ceil(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    const secs = total % 60;
    return `${minutes}:${String(secs).padStart(2, "0")}`;
}

/**
 * Decide what the live button shows.
 * @param {{locode?: string, status?: Object|null, busy?: boolean, remaining?: number}} input
 *   remaining: seconds left on the cooldown as counted locally (overrides status when given)
 * @returns {{disabled: boolean, label: string, message: string}}
 */
export function liveRefreshState({ locode = "", status = null, busy = false, remaining = null } = {}) {
    if (status && status.enabled === false) {
        return { disabled: true, label: LIVE_LABEL, message: "Live refresh is disabled." };
    }
    if (busy || (status && status.running)) {
        return { disabled: true, label: "Fetching…", message: "" };
    }
    const wait = remaining !== null && remaining !== undefined
        ? remaining
        : (status && Number(status.cooldown_remaining)) || 0;
    if (wait > 0) {
        return { disabled: true, label: `Available in ${formatCountdown(wait)}`, message: "" };
    }
    if (!locode) {
        return { disabled: true, label: LIVE_LABEL, message: "Choose a port first." };
    }
    return { disabled: false, label: LIVE_LABEL, message: "" };
}

/**
 * "24 Nov, 02:00 UTC" style text for an ISO timestamp, "" when it cannot be read.
 * @param {string} iso
 * @returns {string}
 */
export function formatWhen(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    return `${d.getUTCDate()} ${months[d.getUTCMonth()]}, ${hh}:${mm} UTC`;
}

function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

/**
 * Sentence shown after a run finishes.
 * @param {Object|null} run  run object from /api/v1/ingest/runs/<id>/
 * @returns {string}
 */
export function summaryMessage(run) {
    if (!run) return "";
    if (run.status === "failed") {
        const detail = run.error ? String(run.error) : "unknown error";
        return `Refresh failed: ${detail}`;
    }
    const portName = PORT_NAMES[run.port] || run.port || "Port";
    const s = run.summary || {};
    if (s.arrivals_skipped) {
        const next = s.arrivals_next_at ? ` Next call allowed ${formatWhen(s.arrivals_next_at)}.` : "";
        return `${portName}: arrivals were already fetched today (the provider allows one call per port per day).${next}`
            + aisMessage(s) + ownershipMessage(s);
    }
    const read = num(s.accepted);
    const created = num(s.opportunities_created);
    const updated = num(s.opportunities_updated);
    if (read === null && created === null && updated === null) {
        return `${portName}: refresh finished.`;
    }
    let text = `${portName}: ${read ?? 0} vessels read, ${created ?? 0} new leads, ${updated ?? 0} updated.`;
    const errors = num(s.errors);
    if (errors) {
        text += ` ${errors} row${errors === 1 ? "" : "s"} could not be saved.`;
    }
    return text + aisMessage(s) + ownershipMessage(s);
}

/**
 * Extra sentence about the AIS step, empty when AIS did not run.
 * @param {Object} s run summary
 * @returns {string}
 */
export function aisMessage(s) {
    if (!s) return "";
    if (s.ais_error) return ` AIS failed: ${s.ais_error}`;
    const anchored = num(s.ais_in_anchorage);
    if (anchored === null) return "";
    const created = num(s.ais_opportunities_created) ?? 0;
    return ` AIS: ${anchored} in anchorage, ${created} new anchorage leads.`;
}

/**
 * Extra sentence about the owner lookup step, empty when there is nothing to say.
 * @param {Object} s run summary
 * @returns {string}
 */
export function ownershipMessage(s) {
    if (!s) return "";
    if (s.own_error) return ` Owner lookup failed: ${s.own_error}`;
    if (s.own_skipped === "disabled") return " Owner lookup is switched off.";
    if (s.own_skipped === "budget") return " Owner lookup: today's share is used up.";
    if (s.own_skipped === "quota") return " Owner lookup paused: monthly limit reached.";
    if (s.own_skipped === "no_candidates") return " Owners: every vessel here is already checked.";
    const requested = num(s.own_requested);
    if (requested === null) return "";
    const links = num(s.own_relationships_created) ?? 0;
    return ` Owners: ${requested} vessel${requested === 1 ? "" : "s"} looked up, ${links} owner or manager link${links === 1 ? "" : "s"} added.`;
}
