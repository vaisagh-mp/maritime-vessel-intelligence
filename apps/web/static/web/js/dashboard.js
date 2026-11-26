/**
 * apps/web/static/web/js/dashboard.js
 * Dashboard controller: stat cards, hot / 24 hour table, and side panels.
 * All networking goes through api.js; all DOM through el().
 */

import { api } from "./api.js";
import {
    dashboardTableQuery,
    allowanceLines,
    refreshStatusText,
    stageBars,
    statCards,
    timeAgo,
    waitingText,
    withPort,
} from "./dashboard-logic.js";
import { renderLeadTable } from "./lead-table.js";
import { bandBadge, el, errorState, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";

const TABLE_COLUMNS = ["priority", "vessel", "details", "port", "eta", "stage", "action"];

const state = {
    port: new URLSearchParams(window.location.search).get("port") || "",
    tab: "24h",
};

function byId(id) {
    return document.getElementById(id);
}

function clear(node) {
    if (node) node.textContent = "";
}

function stateBox(text, kind = "empty-state") {
    return el("div", { class: kind, role: "status" }, text);
}

/* ---------- Stat cards ---------- */

function renderCards(totals) {
    const host = byId("stat-cards");
    clear(host);
    const aisOn = (document.getElementById("main").dataset.ais || "1") !== "0";
    for (const card of statCards(totals).filter((c) => aisOn || c.key !== "anchorage")) {
        host.appendChild(
            el(
                "a",
                { class: `stat-card tone-${card.tone}`, href: withPort(card.href, state.port) },
                el("span", { class: "stat-label" }, card.label),
                el("span", { class: "stat-value" }, String(card.value))
            )
        );
    }
}

function renderCardsError(message) {
    const host = byId("stat-cards");
    clear(host);
    host.appendChild(errorState(message, loadSummary));
}

/* ---------- Panels ---------- */

function panelBody(id) {
    const node = byId(id);
    clear(node);
    return node;
}

function renderAttention(data) {
    const body = panelBody("panel-attention");
    const items = (data && data.items) || [];
    const hours = (data && data.after_hours) || 24;
    const total = (data && data.count) || 0;
    byId("attention-count").textContent = String(total);
    if (items.length === 0) {
        body.appendChild(stateBox(`Nothing waiting. Every HIGH or HOT lead has been picked up within ${hours} hours.`));
        return;
    }
    const list = el("ul", { class: "mini-list" });
    for (const it of items) {
        list.appendChild(
            el(
                "li",
                {},
                el(
                    "a",
                    { class: "mini-row", href: `/leads/${it.id}/` },
                    el("span", { class: "mini-main" }, it.vessel_name),
                    el("span", { class: "mini-meta" }, `${it.port} · waiting ${waitingText(it.hours_waiting)}`),
                    bandBadge(it.band)
                )
            )
        );
    }
    body.appendChild(list);
    if (total > items.length) {
        body.appendChild(el("p", { class: "panel-note" }, `Showing ${items.length} of ${total}.`));
    }
}

function renderPipeline(byStage) {
    const body = panelBody("panel-pipeline");
    const bars = stageBars(byStage);
    if (bars.every((b) => b.count === 0)) {
        body.appendChild(stateBox("No open leads yet."));
        return;
    }
    const list = el("ul", { class: "bar-list" });
    for (const b of bars) {
        const fill = el("span", { class: "bar-fill" });
        fill.style.width = `${b.pct}%`;
        list.appendChild(
            el(
                "li",
                { class: "bar-row" },
                el("span", { class: "bar-label" }, b.label),
                el("span", { class: "bar-track", "aria-hidden": "true" }, fill),
                el("span", { class: "bar-count" }, String(b.count))
            )
        );
    }
    body.appendChild(list);
}

function renderPorts(rows) {
    const body = panelBody("panel-ports");
    if (!rows || rows.length === 0) {
        body.appendChild(stateBox("No active ports."));
        return;
    }
    const table = el(
        "table",
        { class: "mini-table" },
        el("caption", { class: "visually-hidden" }, "Open and HOT leads by port"),
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Port"), el("th", { scope: "col", class: "col-num" }, "Open"), el("th", { scope: "col", class: "col-num" }, "HOT"))),
        el(
            "tbody",
            {},
            ...rows.map((r) =>
                el(
                    "tr",
                    {},
                    el("td", {}, el("a", { href: `/priority/24h/?port=${r.port_id}` }, `${r.name} (${r.un_locode})`)),
                    el("td", { class: "col-num" }, String(r.open)),
                    el("td", { class: "col-num" }, String(r.hot))
                )
            )
        )
    );
    body.appendChild(table);
}

function renderActivity(rows) {
    const body = panelBody("panel-activity");
    if (!rows || rows.length === 0) {
        body.appendChild(stateBox("No stage changes yet. Moves made on a lead will show up here."));
        return;
    }
    const list = el("ul", { class: "mini-list" });
    for (const r of rows) {
        list.appendChild(
            el(
                "li",
                {},
                el(
                    "a",
                    { class: "mini-row stacked", href: `/leads/${r.opportunity_id}/` },
                    el("span", { class: "mini-main" }, r.vessel_name),
                    el("span", { class: "mini-meta" }, `${r.from_label} to ${r.to_label} · ${r.by} · ${timeAgo(r.at)}`)
                )
            )
        );
    }
    body.appendChild(list);
}

function renderFreshness(rows) {
    const body = panelBody("panel-refresh");
    if (!rows || rows.length === 0) {
        body.appendChild(stateBox("No active ports."));
        return;
    }
    const list = el("ul", { class: "mini-list" });
    for (const r of rows) {
        const failed = r.status && r.status !== "success";
        list.appendChild(
            el(
                "li",
                { class: "fresh-row" },
                el("span", { class: "mini-main" }, `${r.name} (${r.port})`),
                el("span", { class: failed ? "mini-meta is-bad" : "mini-meta" }, refreshStatusText(r))
            )
        );
    }
    body.appendChild(list);
}

/** Adds the provider allowances (owner lookups, arrivals) under the freshness list. */
async function renderAllowances() {
    const body = byId("panel-refresh");
    try {
        const lines = allowanceLines(await api.get("/api/v1/ingest/status/"));
        if (lines.length === 0) return;
        const box = el("ul", { class: "mini-list allowance-list" });
        for (const line of lines) {
            box.appendChild(el("li", { class: "fresh-row" }, el("span", { class: "mini-meta" }, line)));
        }
        body.appendChild(box);
    } catch (err) {
        /* the allowances are extra information: the panel works without them */
    }
}

/* ---------- Data loading ---------- */

async function loadSummary() {
    const query = state.port ? `?port=${encodeURIComponent(state.port)}` : "";
    try {
        const data = await api.get(`/api/v1/opportunities/summary/${query}`);
        renderCards(data.totals);
        renderAttention(data.needs_attention);
        renderPipeline(data.by_stage);
        renderPorts(data.by_port);
        renderActivity(data.recent_activity);
        renderFreshness(data.last_refresh);
        renderAllowances();
        const t = new Date();
        byId("updated-time").textContent = `Updated ${String(t.getUTCHours()).padStart(2, "0")}:${String(t.getUTCMinutes()).padStart(2, "0")} UTC`;
    } catch (err) {
        const msg = err.message || "Could not load the summary";
        renderCardsError(msg);
        for (const id of ["panel-attention", "panel-pipeline", "panel-ports", "panel-activity", "panel-refresh"]) {
            const node = panelBody(id);
            node.appendChild(stateBox("Could not load.", "error-state"));
        }
    }
}

async function loadTable() {
    const host = byId("table-host");
    clear(host);
    host.appendChild(stateBox("Loading leads…", "loading-state"));
    const viewAll = byId("table-viewall");
    viewAll.href = withPort(state.tab === "hot" ? "/priority/24h/?band=HOT" : "/priority/24h/", state.port);
    try {
        const data = await api.get(`/api/v1/opportunities/${dashboardTableQuery(state.tab, state.port)}`);
        const items = data.results || [];
        clear(host);
        if (items.length === 0) {
            host.appendChild(
                stateBox(state.tab === "hot" ? "No HOT leads right now." : "No leads in the 24 hour window right now.")
            );
            return;
        }
        host.appendChild(renderLeadTable(items, TABLE_COLUMNS, state.tab === "hot" ? "HOT leads" : "24 hour priority leads"));
        const total = typeof data.count === "number" ? data.count : items.length;
        if (total > items.length) {
            host.appendChild(el("p", { class: "panel-note" }, `Showing the top ${items.length} of ${total}.`));
        }
    } catch (err) {
        clear(host);
        host.appendChild(errorState(err.message || "Could not load leads", loadTable));
    }
}

function reloadAll() {
    loadSummary();
    loadTable();
}

/* ---------- Controls ---------- */

function selectTab(tab) {
    state.tab = tab;
    for (const t of ["24h", "hot"]) {
        const btn = byId(`tab-${t}`);
        const on = t === tab;
        btn.setAttribute("aria-selected", on ? "true" : "false");
        btn.tabIndex = on ? 0 : -1;
        btn.classList.toggle("active", on);
    }
    byId("table-host").setAttribute("aria-labelledby", `tab-${tab}`);
    loadTable();
}

async function populatePorts() {
    const select = byId("filter-port");
    try {
        const data = await api.get("/api/v1/ports/?active=true");
        const ports = data.results || data || [];
        clear(select);
        select.appendChild(el("option", { value: "" }, "All ports"));
        for (const port of ports) {
            const code = port.un_locode ? ` (${port.un_locode})` : "";
            const opt = el("option", { value: String(port.id), "data-locode": port.un_locode || "" }, `${port.name}${code}`);
            if (String(port.id) === state.port) opt.selected = true;
            select.appendChild(opt);
        }
    } catch {
        // keep the "All ports" option
    }
}

function setPort(value) {
    state.port = value;
    const path = value ? `${window.location.pathname}?port=${encodeURIComponent(value)}` : window.location.pathname;
    window.history.replaceState(null, "", path);
    try {
        sessionStorage.setItem("board_path", path);
    } catch {
        // ignore storage errors
    }
    reloadAll();
}

onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        for (const t of ["24h", "hot"]) {
            byId(`tab-${t}`).addEventListener("click", () => selectTab(t));
            byId(`tab-${t}`).addEventListener("keydown", (e) => {
                if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                    const next = t === "24h" ? "hot" : "24h";
                    selectTab(next);
                    byId(`tab-${next}`).focus();
                }
            });
        }
        byId("filter-port").addEventListener("change", (e) => setPort(e.target.value));
        byId("btn-refresh").addEventListener("click", reloadAll);
        await populatePorts();
        reloadAll();
    } catch (err) {
        const main = byId("main") || document.body;
        renderPageCrash(main, "Dashboard failed to start", err);
    }
});
