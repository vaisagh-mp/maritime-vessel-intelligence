/**
 * apps/web/static/web/js/company.js
 * Company detail page controller.
 */

import { api } from "./api.js";
import { inboundLabel } from "./board-logic.js";
import { roleLabel } from "./companies-logic.js";
import { pageInfo, readPage } from "./dashboard-logic.js";
import { bandBadge, el, errorState, formatUtc, onReady, registerGlobalErrorHandlers, renderPageCrash } from "./ui.js";
import { safeHttpUrl, safeMailto } from "./vessel-logic.js";

const main = document.getElementById("main");
const COMPANY_ID = main && main.dataset.companyId;
const PAGE_SIZE = 25;

let page = readPage(window.location.search);
let roleFilter = new URLSearchParams(window.location.search).get("role") || "";
let requestToken = 0;

function byId(id) {
    return document.getElementById(id);
}

function syncUrl() {
    const params = new URLSearchParams();
    if (roleFilter) params.set("role", roleFilter);
    if (page > 1) params.set("page", String(page));
    const qs = params.toString();
    const path = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", path);
}

/** Restore the "back to companies" link to the last company list URL. */
function restoreBackLink() {
    const link = byId("back-link");
    if (!link) return;
    try {
        const saved = sessionStorage.getItem("board_path");
        if (saved && saved.startsWith("/companies")) {
            link.href = saved;
        }
    } catch {
        // ignore
    }
}

/** Render the contact section with safe email and website links. */
function renderContact() {
    const host = byId("company-contact");
    if (!host) return;
    host.textContent = "";

    // Read values already in the page from the server template: we'll fetch
    // them from the overview API for enrichment but the template already has
    // the company object so we can read data-attrs or just use the API.
    // We use the company overview API data we'll fetch anyway.
}

/** Build the contact and summary section from API data. */
function renderSummary(data) {
    // Contact
    const contactHost = byId("company-contact");
    if (contactHost) {
        contactHost.textContent = "";
        const items = [];

        const emailVal = data.email || "";
        if (emailVal) {
            const mailto = safeMailto(emailVal);
            if (mailto) {
                items.push(el("a", { class: "company-contact-link", href: mailto }, emailVal));
            } else {
                items.push(el("span", { class: "cell-sub" }, emailVal));
            }
        }

        const websiteVal = data.website || "";
        if (websiteVal) {
            const link = safeHttpUrl(websiteVal);
            if (link) {
                items.push(el("a", { class: "company-contact-link", href: link.href, target: "_blank", rel: "noopener noreferrer" }, link.text));
            } else {
                items.push(el("span", { class: "cell-sub" }, websiteVal));
            }
        }

        if (items.length > 0) {
            contactHost.appendChild(el("div", { class: "company-contact-row" }, ...items));
        }
    }

    // Summary numbers
    const summaryHost = byId("company-summary");
    if (summaryHost) {
        summaryHost.textContent = "";
        const stats = [
            { label: "Total vessels", value: String(data.vessel_count || 0) },
            { label: "Open leads", value: String(data.open_leads || 0) },
        ];
        if (data.best_band && data.best_band !== "LOW" && data.open_leads > 0) {
            stats.push({ label: "Best band", value: data.best_band });
        }
        for (const s of stats) {
            summaryHost.appendChild(
                el("div", { class: "summary-stat" },
                    el("span", { class: "summary-stat-value" }, s.value),
                    el("span", { class: "summary-stat-label" }, s.label)
                )
            );
        }
    }
}

/** Load company summary from the overview API. */
async function loadSummary() {
    try {
        const data = await api.get(`/api/v1/companies/overview/?q=&page_size=1&page=1`);
        // Find this company in the results, or fetch from the detail endpoint
    } catch {
        // non-critical
    }

    // Better approach: fetch overview with an exact filter
    try {
        // Use the existing company detail endpoint
        const detail = await api.get(`/api/v1/companies/${COMPANY_ID}/`);
        // And get overview data
        const overview = await api.get(`/api/v1/companies/overview/?page_size=200`);
        const items = overview.results || [];
        const match = items.find((c) => c.id === Number(COMPANY_ID));
        if (match) {
            renderSummary(match);
        } else {
            // Fallback: use detail data only
            renderSummary({
                email: detail.email,
                website: detail.website,
                vessel_count: detail.vessel_count || 0,
                open_leads: 0,
                best_band: "LOW",
            });
        }
    } catch {
        // non-critical
    }
}

/** Load and render the vessel table. */
async function loadVessels() {
    const token = ++requestToken;
    const host = byId("vessel-table-host");
    host.textContent = "";
    host.appendChild(el("div", { class: "loading-state", role: "status" }, "Loading vessels…"));

    try {
        const params = new URLSearchParams();
        params.set("page", String(page));
        params.set("page_size", String(PAGE_SIZE));
        if (roleFilter) params.set("role", roleFilter);

        const data = await api.get(`/api/v1/companies/${COMPANY_ID}/vessels/?${params.toString()}`);
        if (token !== requestToken) return;

        const items = data.results || [];
        const total = typeof data.count === "number" ? data.count : items.length;
        host.textContent = "";

        if (items.length === 0) {
            host.appendChild(el("div", { class: "empty-state", role: "status" }, "No vessels for this company."));
        } else {
            host.appendChild(renderVesselTable(items));
        }
        renderPager(total);
    } catch (err) {
        if (token !== requestToken) return;
        host.textContent = "";
        host.appendChild(errorState(err.message || "Could not load vessels", loadVessels));
        byId("pager").textContent = "";
    }
}

function renderVesselTable(items) {
    const cols = [
        { id: "vessel", label: "Vessel" },
        { id: "details", label: "Type / size" },
        { id: "roles", label: "Roles" },
        { id: "lead", label: "Open lead" },
        { id: "action", label: "Action" },
    ];
    const head = el("tr", {}, ...cols.map((c) => el("th", { scope: "col" }, c.label)));
    const body = items.map((item) => {
        const v = item;
        const ids = [v.imo ? `IMO ${v.imo}` : null, v.mmsi ? `MMSI ${v.mmsi}` : null].filter(Boolean).join(" · ");
        const vesselCell = el("div", { class: "cell-stack" },
            el("a", { class: "cell-title", href: `/vessels/${v.id}/` }, v.name || "Vessel"),
            ids ? el("span", { class: "cell-sub" }, ids) : null
        );

        const grt = v.grt != null ? `${Number(v.grt).toLocaleString("en-US")} GRT` : null;
        const sub = [grt, v.flag].filter(Boolean).join(" · ");
        const detailsCell = el("div", { class: "cell-stack" },
            el("span", { class: "cell-title cell-plain" }, v.vessel_type || "—"),
            sub ? el("span", { class: "cell-sub" }, sub) : null
        );

        const rolesBadges = (v.roles || []).map((r) =>
            el("span", { class: "badge badge-score" }, roleLabel(r))
        );
        if (v.verified) {
            rolesBadges.push(el("span", { class: "badge badge-inbound" }, "Verified"));
        }
        const rolesCell = el("div", { class: "cell-badges" }, ...rolesBadges);

        let leadCell;
        if (v.open_lead) {
            const lead = v.open_lead;
            const arrivalLabel = inboundLabel(lead);
            const arrivalBadge = arrivalLabel === "Inbound"
                ? el("span", { class: "badge badge-inbound" }, arrivalLabel)
                : arrivalLabel
                    ? el("span", { class: "badge badge-low", title: "ETA passed" }, arrivalLabel)
                    : null;
            leadCell = el("div", { class: "cell-stack" },
                el("a", { class: "cell-title", href: `/leads/${lead.id}/` },
                    `${lead.port || "—"} · ${lead.stage || ""}`),
                el("div", { class: "cell-badges" },
                    bandBadge(lead.band),
                    el("span", { class: "cell-score" }, String(lead.score)),
                    arrivalBadge
                ),
                lead.eta ? el("span", { class: "cell-sub" }, `ETA ${formatUtc(lead.eta)}`) : null
            );
        } else {
            leadCell = el("span", { class: "cell-sub" }, "—");
        }

        const actionCell = el("div", { class: "row-actions" },
            el("a", { class: "btn btn-secondary btn-sm", href: `/vessels/${v.id}/`, "aria-label": `Vessel details for ${v.name}` }, "Vessel"),
            v.open_lead
                ? el("a", { class: "btn btn-quiet btn-sm", href: `/leads/${v.open_lead.id}/`, "aria-label": `Open lead for ${v.name}` }, "Lead")
                : null
        );

        return el("tr", {},
            el("td", { "data-label": "Vessel" }, vesselCell),
            el("td", { "data-label": "Type / size" }, detailsCell),
            el("td", { "data-label": "Roles" }, rolesCell),
            el("td", { "data-label": "Open lead" }, leadCell),
            el("td", { "data-label": "Action" }, actionCell)
        );
    });

    return el("div", { class: "table-scroll" },
        el("table", { class: "data-table" },
            el("caption", { class: "visually-hidden" }, "Company vessels"),
            el("thead", {}, head),
            el("tbody", {}, ...body)
        )
    );
}

function renderPager(total) {
    const host = byId("pager");
    host.textContent = "";
    const info = pageInfo(total, page, PAGE_SIZE);
    host.appendChild(
        el("span", { class: "pager-text", role: "status", "aria-live": "polite" },
            total === 0 ? "No vessels" : `Showing ${info.from} to ${info.to} of ${info.total}`)
    );
    if (info.pages > 1) {
        host.appendChild(
            el("div", { class: "pager-buttons" },
                el("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: !info.hasPrev, onClick: () => goToPage(info.page - 1) }, "Previous"),
                el("span", { class: "pager-page" }, `Page ${info.page} of ${info.pages}`),
                el("button", { type: "button", class: "btn btn-secondary btn-sm", disabled: !info.hasNext, onClick: () => goToPage(info.page + 1) }, "Next")
            )
        );
    }
}

function goToPage(n) {
    page = n;
    syncUrl();
    loadVessels();
}

function bind() {
    const roleSelect = byId("filter-role");
    if (roleSelect) {
        roleSelect.value = roleFilter;
        roleSelect.addEventListener("change", (e) => {
            roleFilter = e.target.value;
            page = 1;
            syncUrl();
            loadVessels();
        });
    }
}

onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        restoreBackLink();
        bind();
        syncUrl();
        loadSummary();
        loadVessels();
    } catch (err) {
        renderPageCrash(main || document.body, "Company page failed to start", err);
    }
});
