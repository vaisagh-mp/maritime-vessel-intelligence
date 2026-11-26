/**
 * apps/web/static/web/js/priority.js
 * Priority list page (24 hour, 72 hour, anchorage): filters, table, pager, CSV export.
 * The zone comes from <main data-zone="...">. All networking goes through api.js.
 */

import { api } from "./api.js";
import {
    activeFilterCount,
    apiQueryForZone,
    defaultFilters,
    exportQuery,
    readFilters,
    toQuery,
} from "./board-logic.js";
import { pageInfo, readPage, withPaging } from "./dashboard-logic.js";
import { renderLeadTable } from "./lead-table.js";
import { el, errorState, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";

const PAGE_SIZE = 25;
const COLUMNS = ["priority", "vessel", "details", "port", "eta", "stage", "reason", "action"];

const main = document.getElementById("main");
const ZONE = (main && main.dataset.zone) || "24h";

let filters = readFilters(window.location.search);
let page = readPage(window.location.search);
let requestToken = 0;

function byId(id) {
    return document.getElementById(id);
}

function currentPath() {
    const params = new URLSearchParams(toQuery(filters).replace(/^\?/, ""));
    if (page > 1) params.set("page", String(page));
    const qs = params.toString();
    return qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
}

function syncUrl() {
    const path = currentPath();
    window.history.replaceState(null, "", path);
    try {
        sessionStorage.setItem("board_path", path);
    } catch {
        // ignore storage errors
    }
}

function syncControls() {
    byId("filter-port").value = filters.port;
    byId("filter-band").value = filters.band;
    byId("filter-stage").value = filters.stage;
    byId("filter-q").value = filters.q;
    byId("filter-sort").value = filters.sort;
    byId("filter-inbound").checked = filters.inbound;
    byId("filter-new").checked = filters.isNew;
    byId("filter-closed").checked = filters.closed;
}

function updateMeta() {
    const count = activeFilterCount(filters);
    byId("reset-filters").disabled = count === 0;
    byId("active-filters-count").textContent = count === 0 ? "" : `${count} filter${count === 1 ? "" : "s"} active`;
    byId("link-export").href = `/api/v1/opportunities/export/${exportQuery({ ...filters })}${ZONE === "all" ? "" : `&zone=${encodeURIComponent(ZONE)}`}`;
    const t = new Date();
    byId("updated-time").textContent = `Updated ${String(t.getUTCHours()).padStart(2, "0")}:${String(t.getUTCMinutes()).padStart(2, "0")} UTC`;
}

function renderPager(total) {
    const host = byId("pager");
    host.textContent = "";
    const info = pageInfo(total, page, PAGE_SIZE);
    host.appendChild(
        el(
            "span",
            { class: "pager-text", role: "status", "aria-live": "polite" },
            total === 0 ? "No leads" : `Showing ${info.from} to ${info.to} of ${info.total}`
        )
    );
    if (info.pages > 1) {
        host.appendChild(
            el(
                "div",
                { class: "pager-buttons" },
                el("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: !info.hasPrev, onClick: () => goToPage(info.page - 1) }, "Previous"),
                el("span", { class: "pager-page" }, `Page ${info.page} of ${info.pages}`),
                el("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: !info.hasNext, onClick: () => goToPage(info.page + 1) }, "Next")
            )
        );
    }
}

async function load() {
    const token = ++requestToken;
    const host = byId("table-host");
    host.textContent = "";
    host.appendChild(el("div", { class: "loading-state", role: "status" }, "Loading leads…"));
    updateMeta();
    try {
        const query = withPaging(apiQueryForZone(filters, ZONE), page, PAGE_SIZE);
        const data = await api.get(`/api/v1/opportunities/${query}`);
        if (token !== requestToken) return;
        const items = data.results || [];
        const total = typeof data.count === "number" ? data.count : items.length;
        host.textContent = "";
        byId("list-count").textContent = String(total);
        if (items.length === 0 && page > 1 && total > 0) {
            page = pageInfo(total, page, PAGE_SIZE).page;
            syncUrl();
            load();
            return;
        }
        if (items.length === 0) {
            host.appendChild(el("div", { class: "empty-state", role: "status" }, host.dataset.empty || "No leads for these filters."));
        } else {
            host.appendChild(renderLeadTable(items, COLUMNS, `${byId("list-title").textContent} leads`));
        }
        renderPager(total);
    } catch (err) {
        if (token !== requestToken) return;
        host.textContent = "";
        host.appendChild(errorState(err.message || "Could not load leads", load));
        byId("pager").textContent = "";
    }
}

function goToPage(n) {
    page = n;
    syncUrl();
    load();
    const top = byId("list-title");
    if (top) top.scrollIntoView({ block: "start" });
}

function onFiltersChanged() {
    page = 1;
    syncUrl();
    load();
}

function resetFilters() {
    filters = defaultFilters();
    page = 1;
    syncControls();
    syncUrl();
    byId("filter-status").textContent = "Filters reset";
    byId("filter-q").focus();
    load();
}

async function populatePorts() {
    const select = byId("filter-port");
    try {
        const data = await api.get("/api/v1/ports/?active=true");
        const ports = data.results || data || [];
        select.textContent = "";
        select.appendChild(el("option", { value: "" }, "All ports"));
        for (const port of ports) {
            const code = port.un_locode ? ` (${port.un_locode})` : "";
            const opt = el("option", { value: String(port.id), "data-locode": port.un_locode || "" }, `${port.name}${code}`);
            if (String(port.id) === filters.port) opt.selected = true;
            select.appendChild(opt);
        }
    } catch {
        // keep the "All ports" option
    }
}

function bind() {
    const set = (key, id, read) =>
        byId(id).addEventListener("change", (e) => {
            filters[key] = read(e.target);
            onFiltersChanged();
        });
    set("port", "filter-port", (t) => t.value);
    set("band", "filter-band", (t) => t.value);
    set("stage", "filter-stage", (t) => t.value);
    set("sort", "filter-sort", (t) => t.value);
    set("inbound", "filter-inbound", (t) => t.checked);
    set("isNew", "filter-new", (t) => t.checked);
    set("closed", "filter-closed", (t) => t.checked);

    let timer = null;
    byId("filter-q").addEventListener("input", (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            filters.q = e.target.value.trim();
            onFiltersChanged();
        }, 300);
    });
    byId("btn-refresh").addEventListener("click", load);
    byId("reset-filters").addEventListener("click", resetFilters);
}

onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        syncControls();
        bind();
        syncUrl();
        await populatePorts();
        load();
    } catch (err) {
        renderPageCrash(main || document.body, "Priority list failed to start", err);
    }
});
