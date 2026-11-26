/**
 * apps/web/static/web/js/companies.js
 * Company list page controller.
 */

import { api } from "./api.js";
import {
    activeFilterCount,
    apiQuery,
    defaultFilters,
    readFilters,
    pageNumbers,
    roleChips,
    toQuery,
} from "./companies-logic.js";
import { pageInfo, readPage } from "./dashboard-logic.js";
import { bandBadge, el, errorState, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";

const PAGE_SIZE = 12;
const main = document.getElementById("main");

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
        // ignore
    }
}

function syncControls() {
    byId("filter-q").value = filters.q;
    byId("filter-country").value = filters.country;
    byId("filter-type").value = filters.type;
    byId("filter-role").value = filters.role;
    byId("filter-sort").value = filters.ordering;
    byId("filter-open-leads").checked = filters.has_open_leads;
}

function updateMeta() {
    const count = activeFilterCount(filters);
    byId("reset-filters").disabled = count === 0;
    byId("active-filters-count").textContent = count === 0 ? "" : `${count} filter${count === 1 ? "" : "s"} active`;
}

function renderCompanyCard(item) {
    const chips = roleChips(item.role_counts);
    const chipEls = chips.map((c) =>
        el("span", { class: "badge badge-score" }, `${c.count} ${c.label}`)
    );

    const children = [
        el("div", { class: "company-card-head" },
            el("a", { class: "company-card-name", href: `/companies/${item.id}/` }, item.name),
            el("span", { class: "badge badge-low" }, item.company_type || "—")
        ),
    ];

    if (item.country) {
        children.push(el("span", { class: "cell-sub" }, item.country));
    }

    children.push(
        el("div", { class: "company-card-stats" },
            el("span", { class: "company-card-vessel-count" }, `${item.vessel_count} vessel${item.vessel_count === 1 ? "" : "s"}`)
        )
    );

    if (chipEls.length > 0) {
        children.push(el("div", { class: "company-card-chips" }, ...chipEls));
    }

    const leadLine = [];
    if (item.open_leads > 0) {
        leadLine.push(el("span", { class: "company-card-leads" }, `${item.open_leads} open lead${item.open_leads === 1 ? "" : "s"}`));
        leadLine.push(bandBadge(item.best_band));
    }
    if (leadLine.length > 0) {
        children.push(el("div", { class: "company-card-lead-row" }, ...leadLine));
    }

    return el("a", { class: "card company-card", href: `/companies/${item.id}/` }, ...children);
}

function renderPager(total) {
    const host = byId("pager");
    host.textContent = "";
    const info = pageInfo(total, page, PAGE_SIZE);
    host.appendChild(
        el("span", { class: "pager-text", role: "status", "aria-live": "polite" },
            total === 0 ? "No companies" : `Showing ${info.from} to ${info.to} of ${info.total}`)
    );
    if (info.pages > 1) {
        host.appendChild(
            el("div", { class: "pager-buttons" },
                el("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: !info.hasPrev, onClick: () => goToPage(info.page - 1) }, "Previous"),
                ...pageNumbers(info.page, info.pages).map((n) =>
                    n === "…"
                        ? el("span", { class: "pager-gap", "aria-hidden": "true" }, "…")
                        : el(
                              "button",
                              {
                                  type: "button",
                                  class: n === info.page ? "btn btn-primary btn-sm pager-num" : "btn btn-secondary btn-sm pager-num",
                                  "aria-label": `Page ${n}`,
                                  "aria-current": n === info.page ? "page" : null,
                                  onClick: () => (n === info.page ? null : goToPage(n)),
                              },
                              String(n)
                          )
                ),
                el("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: !info.hasNext, onClick: () => goToPage(info.page + 1) }, "Next")
            )
        );
    }
}

async function load() {
    const token = ++requestToken;
    const host = byId("card-host");
    host.textContent = "";
    host.appendChild(el("div", { class: "loading-state", role: "status" }, "Loading companies…"));
    updateMeta();
    try {
        const query = apiQuery(filters, page, PAGE_SIZE);
        const data = await api.get(`/api/v1/companies/overview/${query}`);
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
            host.appendChild(el("div", { class: "empty-state", role: "status" }, "No companies match these filters."));
        } else {
            for (const item of items) {
                host.appendChild(renderCompanyCard(item));
            }
        }
        renderPager(total);
    } catch (err) {
        if (token !== requestToken) return;
        host.textContent = "";
        host.appendChild(errorState(err.message || "Could not load companies", load));
        byId("pager").textContent = "";
    }
}

function goToPage(n) {
    page = n;
    syncUrl();
    load();
    const top = byId("page-title");
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

function bind() {
    const set = (key, id, read) =>
        byId(id).addEventListener("change", (e) => {
            filters[key] = read(e.target);
            onFiltersChanged();
        });
    set("type", "filter-type", (t) => t.value);
    set("role", "filter-role", (t) => t.value);
    set("ordering", "filter-sort", (t) => t.value);
    set("has_open_leads", "filter-open-leads", (t) => t.checked);

    let timer = null;
    const debounce = (key, id) => {
        byId(id).addEventListener("input", (e) => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                filters[key] = e.target.value.trim();
                onFiltersChanged();
            }, 300);
        });
    };
    debounce("q", "filter-q");
    debounce("country", "filter-country");

    byId("reset-filters").addEventListener("click", resetFilters);
}

onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        syncControls();
        bind();
        syncUrl();
        load();
    } catch (err) {
        renderPageCrash(main || document.body, "Company list failed to start", err);
    }
});
