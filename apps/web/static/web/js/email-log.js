/**
 * apps/web/static/web/js/email-log.js
 * "Email log" page: every mail sent from the Send mail button.
 */
import { api } from "./api.js";
import { el, errorState, formatUtc, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";
import { historyQuery, pagerText, statusInfo } from "./email-logic.js";

const state = { q: "", status: "", page: 1 };

function byId(id) {
    return document.getElementById(id);
}

function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
}

function row(m) {
    const info = statusInfo(m.status);
    const detail = el("tr", { class: "log-detail", hidden: true },
        el("td", { colSpan: 7 },
            el("pre", { class: "log-body" }, m.body),
            m.error ? el("p", { class: "form-error" }, `Error: ${m.error}`) : null));
    const toggle = el("button", { type: "button", class: "btn btn-secondary", "aria-expanded": "false" }, "View");
    toggle.addEventListener("click", () => {
        detail.hidden = !detail.hidden;
        toggle.setAttribute("aria-expanded", String(!detail.hidden));
        toggle.textContent = detail.hidden ? "View" : "Hide";
    });
    const main = el("tr", {},
        el("td", {}, formatUtc(m.sent_at)),
        el("td", {}, m.company_id ? el("a", { href: `/companies/${m.company_id}/` }, m.company || "—") : (m.company || "—")),
        el("td", {}, m.vessel_id ? el("a", { href: `/vessels/${m.vessel_id}/` }, m.vessel || "—") : (m.vessel || "—")),
        el("td", {}, m.to),
        el("td", {}, el("div", {}, m.subject), el("div", { class: "owner-meta" }, m.template || "")),
        el("td", {}, el("span", { class: `log-status log-status-${info.tone}` }, info.label), el("div", { class: "owner-meta" }, m.sent_by || "")),
        el("td", {}, toggle));
    return [main, detail];
}

function renderTable(rows) {
    const table = el("table", { class: "data-table" });
    table.appendChild(el("thead", {}, el("tr", {},
        ...["Sent (UTC)", "Company", "Vessel", "To", "Subject and template", "Result and sender", ""].map((h) => el("th", { scope: "col" }, h)))));
    const body = el("tbody");
    for (const m of rows) for (const tr of row(m)) body.appendChild(tr);
    table.appendChild(body);
    return table;
}

function renderPager(data) {
    const host = byId("log-pager");
    clear(host);
    const text = pagerText(data.page, data.pages);
    if (!text) return;
    const prev = el("button", { type: "button", class: "btn btn-secondary" }, "Previous");
    const next = el("button", { type: "button", class: "btn btn-secondary" }, "Next");
    prev.disabled = data.page <= 1;
    next.disabled = data.page >= data.pages;
    prev.addEventListener("click", () => { state.page -= 1; load(); });
    next.addEventListener("click", () => { state.page += 1; load(); });
    host.append(prev, el("span", { class: "count-note" }, ` ${text} `), next);
}

async function load() {
    const host = byId("log-host");
    clear(host);
    host.appendChild(el("div", { class: "loading-state" }, "Loading…"));
    try {
        const data = await api.get(`/api/v1/outreach/history/${historyQuery(state)}`);
        state.page = data.page;
        byId("log-count").textContent = String(data.count);
        clear(host);
        if (data.results.length === 0) {
            host.appendChild(el("div", { class: "empty-state" }, "No mails have been sent yet for these filters."));
        } else {
            host.appendChild(renderTable(data.results));
        }
        renderPager(data);
    } catch (err) {
        clear(host);
        host.appendChild(errorState(err.message || "Could not load the log", load));
    }
}

onReady(() => {
    registerGlobalErrorHandlers();
    const root = byId("log-host");
    if (!root) return;
    try {
        let timer = null;
        byId("log-q").addEventListener("input", (e) => {
            clearTimeout(timer);
            timer = setTimeout(() => { state.q = e.target.value; state.page = 1; load(); }, 300);
        });
        byId("log-status").addEventListener("change", (e) => { state.status = e.target.value; state.page = 1; load(); });
        load();
    } catch (err) {
        renderPageCrash(root, "The page could not start", err);
    }
});
