/**
 * apps/web/static/web/js/lead-table.js
 * Renders lead rows as an accessible table. Safe DOM only (el / textContent).
 */

import { etaRelative, etaSourceLabel, inboundLabel } from "./board-logic.js";
import { bandBadge, el, formatNumber, formatUtc } from "./ui.js";

const EM_DASH = "—";

function vesselCell(item) {
    const v = item.vessel_summary || {};
    const ids = [v.imo ? `IMO ${v.imo}` : null, v.mmsi ? `MMSI ${v.mmsi}` : null].filter(Boolean).join(" · ");
    const children = [
        el("a", { class: "cell-title", href: `/leads/${item.id}/` }, v.name || "Vessel"),
    ];
    if (ids) children.push(el("span", { class: "cell-sub" }, ids));
    return el("div", { class: "cell-stack" }, ...children);
}

function detailsCell(item) {
    const v = item.vessel_summary || {};
    const grt = v.grt === null || v.grt === undefined ? null : `${formatNumber(v.grt)} GRT`;
    const sub = [grt, v.flag].filter(Boolean).join(" · ");
    return el(
        "div",
        { class: "cell-stack" },
        el("span", { class: "cell-title cell-plain" }, v.vessel_type || EM_DASH),
        sub ? el("span", { class: "cell-sub" }, sub) : null
    );
}

function etaCell(item) {
    const rel = etaRelative(item.eta, Date.now());
    const source = etaSourceLabel(item.eta_source);
    return el(
        "div",
        { class: "cell-stack", title: source ? `ETA source: ${source}` : "" },
        el("span", { class: rel === "ETA passed" ? "cell-title passed" : "cell-title" }, rel),
        el("span", { class: "cell-sub cell-nowrap" }, item.eta ? formatUtc(item.eta) : "No ETA")
    );
}

function portCell(item) {
    const p = item.port_summary || {};
    return el(
        "div",
        { class: "cell-stack" },
        el("span", { class: "cell-title" }, p.name || EM_DASH),
        p.un_locode ? el("span", { class: "cell-sub" }, p.un_locode) : null
    );
}

function priorityCell(item) {
    return el(
        "div",
        { class: "cell-priority" },
        bandBadge(item.band || "LOW"),
        el("span", { class: "cell-score" }, item.score === null || item.score === undefined ? EM_DASH : String(item.score))
    );
}

function stageCell(item) {
    const children = [el("span", {}, item.stage_label || item.stage || EM_DASH)];
    const arrival = inboundLabel(item);
    if (arrival === "Inbound") children.push(el("span", { class: "badge badge-inbound" }, arrival));
    else if (arrival) {
        children.push(
            el("span", { class: "badge badge-low", title: "The ETA has passed. Refresh data to see where the vessel is now." }, arrival)
        );
    }
    if (item.zone === "anchorage_bound") children.push(el("span", { class: "badge badge-zone" }, "Anchorage bound"));
    return el("div", { class: "cell-badges" }, ...children);
}

export const COLUMNS = {
    priority: { label: "Priority", cell: priorityCell, cls: "col-priority" },
    vessel: { label: "Vessel", cell: vesselCell, cls: "col-vessel" },
    details: { label: "Type / size", cell: detailsCell, cls: "col-details" },
    port: { label: "Port", cell: portCell },
    eta: { label: "ETA", cell: etaCell },
    stage: { label: "Stage", cell: stageCell },
    reason: { label: "Why this lead", cell: (i) => el("span", { class: "cell-reason", title: i.lead_reason || "" }, i.lead_reason || EM_DASH), cls: "col-reason" },
    action: {
        label: "Action",
        cell: (i) =>
            el(
                "div",
                { class: "row-actions" },
                el("a", { class: "btn btn-secondary btn-sm", href: `/leads/${i.id}/`, "aria-label": `Open lead for ${(i.vessel_summary && i.vessel_summary.name) || "vessel"}` }, "Open"),
                el("a", { class: "btn btn-quiet btn-sm", href: `/vessels/${(i.vessel_summary && i.vessel_summary.id) || i.vessel}/`, "aria-label": `Vessel details for ${(i.vessel_summary && i.vessel_summary.name) || "vessel"}` }, "Vessel")
            ),
    },
};

/**
 * @param {Array<Object>} items
 * @param {string[]} columnIds
 * @param {string} caption - accessible table name
 * @returns {HTMLElement}
 */
export function renderLeadTable(items, columnIds, caption) {
    const cols = columnIds.map((id) => ({ id, ...COLUMNS[id] }));
    const head = el("tr", {}, ...cols.map((c) => el("th", { scope: "col", class: c.cls || "" }, c.label)));
    const body = items.map((item) =>
        el(
            "tr",
            { class: `band-row band-row-${String(item.band || "LOW").toLowerCase()}` },
            ...cols.map((c) => {
                const content = c.cell(item);
                return el("td", { class: c.cls || "", "data-label": c.label }, content);
            })
        )
    );
    return el(
        "div",
        { class: "table-scroll" },
        el(
            "table",
            { class: "data-table" },
            el("caption", { class: "visually-hidden" }, caption),
            el("thead", {}, head),
            el("tbody", {}, ...body)
        )
    );
}
