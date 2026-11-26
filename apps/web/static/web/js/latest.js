/**
 * apps/web/static/web/js/latest.js
 * "Latest arrivals" page: the vessels touched by the last live Expected Arrivals fetch of each port,
 * with their owners and managers.
 */
import { api } from "./api.js";
import { bandBadge, el, errorState, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";
import { safeHttpUrl, safeMailto, ownerLookupText } from "./vessel-logic.js";
import { buildQuery, companyMeta, dateChips, fetchText, pageText, splitCompanies, utcText } from "./latest-logic.js";

const state = { port: "", band: "", page: 1, date: "" };

function byId(id) {
    return document.getElementById(id);
}

function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
}

function companyBlock(c) {
    const box = el("div", { class: "owner-entry" });
    box.appendChild(el("a", { href: `/companies/${encodeURIComponent(c.company_id)}/`, class: "owner-name" }, c.name));
    box.appendChild(el("span", { class: "owner-role" }, ` ${c.role_label}`));
    if (c.verified) box.appendChild(el("span", { class: "badge badge-low", title: "Confirmed by your team" }, "Confirmed"));
    const meta = companyMeta(c);
    if (meta) box.appendChild(el("div", { class: "owner-meta" }, meta));
    const mail = safeMailto(c.email);
    if (mail) box.appendChild(el("div", { class: "owner-meta" }, el("a", { href: mail }, c.email)));
    const site = safeHttpUrl(c.website);
    if (site) box.appendChild(el("div", { class: "owner-meta" }, el("a", { href: site, target: "_blank", rel: "noopener noreferrer" }, c.website)));
    return box;
}

function companyCell(list, row) {
    const td = el("td");
    if (list.length === 0) {
        const hasAny = (row.companies || []).length > 0;
        td.appendChild(el("span", { class: "text-muted" }, hasAny ? "—" : ownerLookupText(row.vessel.ownership_checked_at, false)));
        return td;
    }
    for (const c of list) td.appendChild(companyBlock(c));
    return td;
}

function renderTable(rows) {
    const table = el("table", { class: "data-table" });
    table.appendChild(el("thead", {}, el("tr", {},
        ...["Vessel", "Port", "ETA", "Priority", "Owner", "Manager"].map((h) => el("th", { scope: "col" }, h)))));
    const body = el("tbody");
    for (const row of rows) {
        const { owners, managers } = splitCompanies(row.companies);
        const v = row.vessel;
        body.appendChild(el("tr", {},
            el("td", {},
                el("a", { href: row.id ? `/leads/${row.id}/` : `/vessels/${v.id}/` }, v.name),
                el("div", { class: "owner-meta" }, [v.imo ? `IMO ${v.imo}` : "", v.vessel_type || ""].filter(Boolean).join(" · "))),
            el("td", {}, row.port),
            el("td", {}, utcText(row.eta) || "—"),
            el("td", {}, bandBadge(row.band), el("span", { class: "owner-meta" }, ` ${row.score}`)),
            companyCell(owners, row),
            companyCell(managers, row)));
    }
    table.appendChild(body);
    return table;
}

function renderPager(data) {
    const host = byId("latest-pager");
    clear(host);
    const text = pageText(data.page, data.pages);
    if (!text) return;
    const prev = el("button", { type: "button", class: "btn btn-secondary" }, "Previous");
    const next = el("button", { type: "button", class: "btn btn-secondary" }, "Next");
    prev.disabled = data.page <= 1;
    next.disabled = data.page >= data.pages;
    prev.addEventListener("click", () => { state.page -= 1; load(); });
    next.addEventListener("click", () => { state.page += 1; load(); });
    host.append(prev, el("span", { class: "count-note" }, ` ${text} `), next);
}

function renderFetches(data) {
    const host = byId("latest-fetches");
    clear(host);
    for (const f of data.fetches) host.appendChild(el("div", {}, fetchText(f)));
    const picker = byId("latest-date");
    picker.value = data.date;
    const chips = byId("latest-chips");
    clear(chips);
    for (const chip of dateChips(data.dates)) {
        const b = el("button", { type: "button", class: chip.value === data.date ? "btn btn-primary" : "btn btn-secondary" }, chip.label);
        b.addEventListener("click", () => { state.date = chip.value; state.page = 1; load(); });
        chips.appendChild(b);
    }
}

async function load() {
    const host = byId("latest-host");
    clear(host);
    host.appendChild(el("div", { class: "loading-state" }, "Loading…"));
    try {
        const data = await api.get(`/api/v1/opportunities/latest-arrivals/${buildQuery(state)}`);
        byId("latest-fetches").textContent = data.fetches.map(fetchText).join("  ·  ");
        byId("latest-count").textContent = String(data.count);
        clear(host);
        if (data.results.length === 0) {
            host.appendChild(el("div", { class: "empty-state" }, "No vessels from the last fetch match these filters."));
        } else {
            host.appendChild(renderTable(data.results));
        }
        renderPager(data);
    } catch (err) {
        clear(host);
        host.appendChild(errorState(err.message || "Could not load the list", load));
    }
}

onReady(() => {
    registerGlobalErrorHandlers();
    const root = byId("latest-host");
    if (!root) return;
    try {
        byId("latest-port").addEventListener("change", (e) => { state.port = e.target.value; state.page = 1; load(); });
        const picker = byId("latest-date");
        picker.max = new Date().toISOString().slice(0, 10);
        picker.addEventListener("change", (e) => { state.date = e.target.value; state.page = 1; load(); });
        byId("latest-today").addEventListener("click", () => { state.date = ""; state.page = 1; load(); });
        byId("latest-band").addEventListener("change", (e) => { state.band = e.target.value; state.page = 1; load(); });
        load();
    } catch (err) {
        renderPageCrash(root, "The page could not start", err);
    }
});
