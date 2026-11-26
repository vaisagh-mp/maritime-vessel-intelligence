/**
 * apps/web/static/web/js/refresh.js
 * "Refresh data (live)" button controller for the Lead board.
 * One click asks the SERVER for ONE MarineTraffic call for the selected port.
 * The server owns the 2 minute cooldown; this file only shows it.
 * All networking goes through api.js. Never retries automatically.
 */

import { api } from "./api.js";
import { formatCountdown, liveRefreshState, summaryMessage } from "./refresh-logic.js";
import { onReady } from "./ui.js";

const STATUS_URL = "/api/v1/ingest/status/";
const REFRESH_URL = "/api/v1/ingest/refresh/";
const POLL_MS = 3000;
const SYNC_MS = 15000;
const MAX_POLL_ERRORS = 3;

const state = {
    status: null,        // last payload from the status endpoint
    cooldownEndsAt: 0,   // ms timestamp, counted locally between syncs
    busy: false,         // POST in flight or polling a run
    flash: "",           // sentence from the last action
};

let pollTimer = null;
let btn = null;
let statusEl = null;

function selectedLocode() {
    const select = document.getElementById("filter-port");
    if (!select) return "";
    const option = select.options[select.selectedIndex];
    return (option && option.getAttribute("data-locode")) || "";
}

function localRemaining() {
    if (!state.cooldownEndsAt) return 0;
    return Math.max(0, Math.ceil((state.cooldownEndsAt - Date.now()) / 1000));
}

function render() {
    if (!btn) return;
    const view = liveRefreshState({
        locode: selectedLocode(),
        status: state.status,
        busy: state.busy,
        remaining: localRemaining(),
    });
    btn.disabled = view.disabled;
    btn.textContent = view.label;
    btn.setAttribute("aria-disabled", view.disabled ? "true" : "false");
    if (statusEl) {
        statusEl.textContent = state.flash || view.message;
    }
}

function applyStatus(payload) {
    state.status = payload;
    state.cooldownEndsAt = Date.now() + (Number(payload.cooldown_remaining) || 0) * 1000;
}

async function loadStatus() {
    try {
        applyStatus(await api.get(STATUS_URL));
        if (state.status.running && !state.busy) {
            state.busy = true;
            state.flash = "A refresh is running…";
            pollRun(state.status.running.run_id);
        }
    } catch {
        // Keep the last known state; the button stays usable only if it was.
    }
    render();
}

function stopPolling() {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
}

function reloadBoard() {
    const reload = document.getElementById("btn-refresh");
    if (reload) reload.click();
}

function pollRun(runId, errors = 0) {
    stopPolling();
    pollTimer = setTimeout(async () => {
        try {
            const run = await api.get(`/api/v1/ingest/runs/${runId}/`);
            if (run.status === "running") {
                pollRun(runId, 0);
                return;
            }
            state.busy = false;
            state.flash = summaryMessage(run);
            await loadStatus();
            if (run.status === "success") reloadBoard();
        } catch (err) {
            if (errors + 1 >= MAX_POLL_ERRORS) {
                state.busy = false;
                state.flash = "Could not read the refresh result. Use Reload to check the board.";
                await loadStatus();
                return;
            }
            pollRun(runId, errors + 1);
        }
    }, POLL_MS);
}

async function onClick() {
    const locode = selectedLocode();
    if (!locode || state.busy) {
        render();
        return;
    }
    state.busy = true;
    state.flash = "";
    render();
    try {
        const data = await api.post(REFRESH_URL, { port: locode });
        state.flash = "Fetching from MarineTraffic…";
        render();
        pollRun(data.run_id);
    } catch (err) {
        state.busy = false;
        state.flash = err && err.message ? err.message : "Refresh could not be started.";
        await loadStatus();
    }
}

function tick() {
    // Re-render every second so the countdown moves; the server stays the authority.
    render();
}

onReady(() => {
    btn = document.getElementById("btn-live-refresh");
    statusEl = document.getElementById("live-refresh-status");
    if (!btn) return;

    btn.addEventListener("click", onClick);
    const portSelect = document.getElementById("filter-port");
    if (portSelect) {
        portSelect.addEventListener("change", () => {
            state.flash = "";
            render();
        });
    }

    render();
    loadStatus();
    setInterval(tick, 1000);
    setInterval(() => {
        if (!state.busy && localRemaining() === 0) loadStatus();
    }, SYNC_MS);
});

// Exposed for tests of formatting only; no side effects.
export { formatCountdown };
