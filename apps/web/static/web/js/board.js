/**
 * apps/web/static/web/js/board.js
 * Lead board interactive controller: filter controls, URL state sync, 3-column board, and CSV export.
 * Strictly uses safe DOM element generation via el() and api.js for networking.
 */

import { api } from "./api.js";
import {
    apiQueryForZone,
    etaRelative,
    etaSourceLabel,
    exportQuery,
    readFilters,
    STAGE_LABELS,
    summarise,
    toQuery,
    VALID_BANDS,
    VALID_STAGES,
    ZONES,
} from "./board-logic.js";
import { bandBadge, el, errorState, formatNumber, formatUtc, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";

const EM_DASH = "\u2014";

// State
let currentFilters = readFilters(window.location.search);
const columnData = {
    "24h": { items: [], totalCount: 0, nextUrl: null, loading: false },
    "72h": { items: [], totalCount: 0, nextUrl: null, loading: false },
    "anchorage": { items: [], totalCount: 0, nextUrl: null, loading: false },
};

function formatCurrentUtcTime() {
    const d = new Date();
    const hours = String(d.getUTCHours()).padStart(2, "0");
    const minutes = String(d.getUTCMinutes()).padStart(2, "0");
    return `Updated ${hours}:${minutes} UTC`;
}

function updateExportLink() {
    const exportLink = document.getElementById("link-export");
    if (exportLink) {
        exportLink.href = `/api/v1/opportunities/export/${exportQuery(currentFilters)}`;
    }
}

function updateUpdatedTime() {
    const timeEl = document.getElementById("updated-time");
    if (timeEl) {
        timeEl.textContent = formatCurrentUtcTime();
    }
}

function updateSummaryStrip() {
    const allItems = [
        ...columnData["24h"].items,
        ...columnData["72h"].items,
        ...columnData["anchorage"].items,
    ];
    const { total, hot, inbound } = summarise(allItems);

    const totalEl = document.getElementById("summary-total");
    const hotEl = document.getElementById("summary-hot");
    const inboundEl = document.getElementById("summary-inbound");
    const noteEl = document.getElementById("summary-note");

    if (totalEl) totalEl.textContent = String(total);
    if (hotEl) hotEl.textContent = String(hot);
    if (inboundEl) inboundEl.textContent = String(inbound);

    const allLoaded =
        !columnData["24h"].nextUrl &&
        !columnData["72h"].nextUrl &&
        !columnData["anchorage"].nextUrl;

    if (noteEl) {
        noteEl.textContent = allLoaded ? "" : "(in loaded cards)";
    }
}

function createLeadCard(item) {
    const bandName = item.band || "LOW";
    const bandClass = `band-${bandName.toLowerCase()}`;

    // Stretched link for full card clickability
    const vesselName = item.vessel_summary?.name || "Vessel";
    const stretchedLink = el(
        "a",
        {
            class: "card-stretched-link",
            href: `/leads/${item.id}/`,
            "aria-label": `View lead for ${vesselName}`,
        },
        "View lead"
    );

    // Top row: Band badge + score
    const badge = bandBadge(bandName);
    const scoreVal = item.score !== null && item.score !== undefined ? String(item.score) : EM_DASH;
    const scoreEl = el("span", { class: "card-score" }, `Score: ${scoreVal}`);
    const topRow = el("div", { class: "card-top-row" }, badge, scoreEl);

    // Vessel name + separate Vessel details link
    const nameEl = el("span", { class: "card-vessel-name" }, vesselName);
    const vesselId = item.vessel_summary?.id || item.vessel;
    const vesselLink = el(
        "a",
        {
            class: "card-vessel-link",
            href: `/vessels/${vesselId}/`,
        },
        "Vessel details"
    );
    const vesselRow = el("div", { class: "card-vessel-row" }, nameEl, vesselLink);

    // Line 1: Type · GRT · Flag
    const vType = item.vessel_summary?.vessel_type || EM_DASH;
    const grt = formatNumber(item.vessel_summary?.grt);
    const flag = item.vessel_summary?.flag || EM_DASH;
    const line1 = el("div", { class: "card-line" }, `${vType} · ${grt} GRT · ${flag}`);

    // Line 2: Port and UN/LOCODE
    const portName = item.port_summary?.name || EM_DASH;
    const locode = item.port_summary?.un_locode ? ` (${item.port_summary.un_locode})` : "";
    const line2 = el("div", { class: "card-line" }, `${portName}${locode}`);

    // Line 3: ETA, source, and relative time
    const etaFormatted = formatUtc(item.eta);
    const sourceLabel = etaSourceLabel(item.eta_source);
    const sourceText = sourceLabel ? ` (${sourceLabel})` : "";
    const relText = etaRelative(item.eta, Date.now());
    const relClass = relText === "ETA passed" ? "card-eta-rel passed" : "card-eta-rel";

    const line3 = el(
        "div",
        { class: "card-line" },
        el("span", {}, `${etaFormatted}${sourceText} · `),
        el("span", { class: relClass }, relText)
    );

    // Line 4: Lead reason
    const reasonText = item.lead_reason || "";
    const reasonEl = el(
        "p",
        { class: "card-lead-reason", title: reasonText },
        reasonText || EM_DASH
    );

    // Footer: Stage label + Inbound badge
    const stageLabel = item.stage_label || item.stage || "";
    const stageEl = el("span", { class: "card-stage" }, stageLabel);
    const footerChildren = [stageEl];

    if (item.is_inbound) {
        footerChildren.push(el("span", { class: "badge-inbound" }, "Inbound"));
    }
    const footerEl = el("div", { class: "card-footer" }, ...footerChildren);

    return el(
        "article",
        { class: `lead-card ${bandClass}` },
        stretchedLink,
        topRow,
        vesselRow,
        line1,
        line2,
        line3,
        reasonEl,
        footerEl
    );
}

function renderColumn(zoneId) {
    const colEl = document.getElementById(`column-${zoneId}`);
    if (!colEl) return;

    const cardsContainer = colEl.querySelector(".column-cards");
    const countEl = colEl.querySelector(".column-count");
    const loadMoreContainer = colEl.querySelector(".column-load-more-container");

    if (!cardsContainer) return;

    cardsContainer.textContent = "";
    if (loadMoreContainer) loadMoreContainer.textContent = "";

    const state = columnData[zoneId];
    if (countEl) {
        countEl.textContent = `(${state.totalCount})`;
    }

    if (state.loading && state.items.length === 0) {
        const loadingState = el("div", { class: "column-state" }, "Loading leads...");
        cardsContainer.appendChild(loadingState);
        return;
    }

    if (state.error && state.items.length === 0) {
        cardsContainer.appendChild(errorState(state.error, () => loadColumn(zoneId)));
        return;
    }

    if (state.items.length === 0) {
        const emptyState = el(
            "div",
            { class: "column-state" },
            "No leads in this zone for these filters"
        );
        cardsContainer.appendChild(emptyState);
        return;
    }

    // Render cards
    for (const item of state.items) {
        cardsContainer.appendChild(createLeadCard(item));
    }

    // Load More button
    if (state.nextUrl && loadMoreContainer) {
        const loadMoreBtn = el(
            "button",
            {
                type: "button",
                class: "btn btn-secondary column-load-more",
                onClick: () => loadMoreColumn(zoneId),
            },
            state.loadingMore ? "Loading..." : "Load more"
        );
        loadMoreContainer.appendChild(loadMoreBtn);
    }
}

async function loadColumn(zoneId) {
    const state = columnData[zoneId];
    state.loading = true;
    state.error = null;
    state.items = [];
    state.nextUrl = null;
    renderColumn(zoneId);

    try {
        const query = apiQueryForZone(currentFilters, zoneId);
        const url = `/api/v1/opportunities/${query}`;
        const data = await api.get(url);

        state.items = data.results || [];
        state.totalCount = typeof data.count === "number" ? data.count : state.items.length;
        state.nextUrl = data.next || null;
    } catch (err) {
        state.error = err.message || "Failed to load leads";
    } finally {
        state.loading = false;
        renderColumn(zoneId);
        updateSummaryStrip();
    }
}

async function loadMoreColumn(zoneId) {
    const state = columnData[zoneId];
    if (!state.nextUrl || state.loadingMore) return;

    state.loadingMore = true;
    renderColumn(zoneId);

    try {
        // Parse relative path + query from nextUrl to stay same-origin
        const nextUrlObj = new URL(state.nextUrl, window.location.origin);
        const relativeUrl = `${nextUrlObj.pathname}${nextUrlObj.search}`;
        const data = await api.get(relativeUrl);

        state.items = [...state.items, ...(data.results || [])];
        state.nextUrl = data.next || null;
    } catch (err) {
        state.error = err.message || "Failed to load more leads";
    } finally {
        state.loadingMore = false;
        renderColumn(zoneId);
        updateSummaryStrip();
    }
}

function refreshAllColumns() {
    updateExportLink();
    updateUpdatedTime();
    for (const zone of ZONES) {
        loadColumn(zone.id);
    }
}

async function populatePortsDropdown() {
    const portSelect = document.getElementById("filter-port");
    if (!portSelect) return;

    try {
        const data = await api.get("/api/v1/ports/?active=true");
        const ports = data.results || data || [];

        // Retain "All ports" option
        portSelect.textContent = "";
        portSelect.appendChild(el("option", { value: "" }, "All ports"));

        for (const port of ports) {
            const locode = port.un_locode ? ` (${port.un_locode})` : "";
            const option = el("option", { value: String(port.id) }, `${port.name}${locode}`);
            if (String(port.id) === currentFilters.port) {
                option.selected = true;
            }
            portSelect.appendChild(option);
        }
    } catch {
        // Fallback: keep existing port dropdown options
    }
}

function syncFormControls() {
    const portSelect = document.getElementById("filter-port");
    const bandSelect = document.getElementById("filter-band");
    const stageSelect = document.getElementById("filter-stage");
    const qInput = document.getElementById("filter-q");
    const sortSelect = document.getElementById("filter-sort");
    const inboundCheck = document.getElementById("filter-inbound");
    const closedCheck = document.getElementById("filter-closed");

    if (portSelect) portSelect.value = currentFilters.port;
    if (bandSelect) bandSelect.value = currentFilters.band;
    if (stageSelect) stageSelect.value = currentFilters.stage;
    if (qInput) qInput.value = currentFilters.q;
    if (sortSelect) sortSelect.value = currentFilters.sort;
    if (inboundCheck) inboundCheck.checked = currentFilters.inbound;
    if (closedCheck) closedCheck.checked = currentFilters.closed;
}

function onFiltersChanged() {
    const newQuery = toQuery(currentFilters);
    const newPath = newQuery ? `${window.location.pathname}${newQuery}` : window.location.pathname;
    window.history.replaceState(null, "", newPath);
    try {
        sessionStorage.setItem("board_query", newQuery ? newQuery.substring(1) : "");
    } catch {
        // Ignore storage access errors
    }
    refreshAllColumns();
}

function bindFilterEvents() {
    const portSelect = document.getElementById("filter-port");
    const bandSelect = document.getElementById("filter-band");
    const stageSelect = document.getElementById("filter-stage");
    const qInput = document.getElementById("filter-q");
    const sortSelect = document.getElementById("filter-sort");
    const inboundCheck = document.getElementById("filter-inbound");
    const closedCheck = document.getElementById("filter-closed");
    const refreshBtn = document.getElementById("btn-refresh");

    if (portSelect) {
        portSelect.addEventListener("change", (e) => {
            currentFilters.port = e.target.value;
            onFiltersChanged();
        });
    }

    if (bandSelect) {
        bandSelect.addEventListener("change", (e) => {
            currentFilters.band = e.target.value;
            onFiltersChanged();
        });
    }

    if (stageSelect) {
        stageSelect.addEventListener("change", (e) => {
            currentFilters.stage = e.target.value;
            onFiltersChanged();
        });
    }

    if (sortSelect) {
        sortSelect.addEventListener("change", (e) => {
            currentFilters.sort = e.target.value;
            onFiltersChanged();
        });
    }

    if (inboundCheck) {
        inboundCheck.addEventListener("change", (e) => {
            currentFilters.inbound = e.target.checked;
            onFiltersChanged();
        });
    }

    if (closedCheck) {
        closedCheck.addEventListener("change", (e) => {
            currentFilters.closed = e.target.checked;
            onFiltersChanged();
        });
    }

    // Debounced search input (300ms)
    if (qInput) {
        let debounceTimer = null;
        qInput.addEventListener("input", (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                currentFilters.q = e.target.value.trim();
                onFiltersChanged();
            }, 300);
        });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            refreshAllColumns();
        });
    }
}

// Initialise board safely when DOM is ready
onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        try {
            const initQuery = window.location.search;
            sessionStorage.setItem("board_query", initQuery ? initQuery.substring(1) : "");
        } catch {
            // Ignore storage access errors
        }
        syncFormControls();
        bindFilterEvents();
        await populatePortsDropdown();
        refreshAllColumns();
    } catch (err) {
        const main = document.getElementById("main") || document.body;
        renderPageCrash(main, "Board controller initialization failed", err);
    }
});
