/**
 * apps/web/static/web/js/vessel.js
 * Vessel detail page controller.
 * Fetches vessel data in parallel, manages card lifecycle states, and handles pagination.
 * Exclusively uses el() for DOM construction and api.js for network calls.
 */

import { api, ApiError } from "./api.js";
import { el, renderError, onReady, registerGlobalErrorHandlers, renderPageCrash, toast } from "./ui.js";
import {
    navStatusLabel,
    portAreaLabel,
    safeHttpUrl,
    safeMailto,
    groupContacts,
    vesselAge,
    positionAgeHours,
    osmUrl,
    formatCoord,
    formatMetres,
    formatNumber,
    formatDate,
    formatDateTimeUtc,
    verificationText,
    ownerLookupText,
} from "./vessel-logic.js";
import { renderMailControls } from "./outreach.js";
import { indexByCompany } from "./outreach-logic.js";

const CLOSED_STAGES = new Set(["won", "lost"]);

let observationsNextUrl = null;

/**
 * Configure back link to preserve previous lead board filters if stored.
 */
function initBackLink() {
    const backLink = document.getElementById("back-to-board-link");
    if (!backLink) return;

    // Go back to the priority list the user came from (same-origin path only).
    let target = "/priority/24h/";
    try {
        const stored = sessionStorage.getItem("board_path");
        if (stored && /^\/(priority\/[a-z0-9]+\/)?(\?[^\s]*)?$/i.test(stored)) {
            target = stored;
        }
    } catch {
        // ignore storage errors
    }
    backLink.href = target;
}

/**
 * Helper to display loading indicator inside a container.
 */
function setLoading(container, message) {
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }
    container.appendChild(el("div", { class: "loading-state", role: "status" }, message));
}



/**
 * Helper to display empty state.
 */
function setEmpty(container, message) {
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }
    container.appendChild(el("div", { class: "empty-state", role: "status" }, message));
}

/**
 * 1 & 2. Load Vessel Particulars & update Header details.
 */
async function loadVesselData(vesselId) {
    const bodyParticulars = document.getElementById("body-particulars");
    if (!bodyParticulars) return;

    setLoading(bodyParticulars, "Loading vessel particulars...");

    try {
        const vessel = await api.get(`/api/v1/vessels/${vesselId}/`);

        // Update Header items
        const vesselTitle = document.getElementById("vessel-name");
        if (vesselTitle) vesselTitle.textContent = vessel.name || "Unknown Vessel";

        const headerImo = document.getElementById("header-imo");
        if (headerImo) headerImo.textContent = vessel.imo || "\u2014";

        const headerMmsi = document.getElementById("header-mmsi");
        if (headerMmsi) headerMmsi.textContent = vessel.mmsi || "\u2014";

        const headerType = document.getElementById("header-type");
        if (headerType) headerType.textContent = vessel.vessel_type || "\u2014";

        const headerFlag = document.getElementById("header-flag");
        if (headerFlag) headerFlag.textContent = vessel.flag || "\u2014";

        // Render Particulars definition list
        while (bodyParticulars.firstChild) {
            bodyParticulars.removeChild(bodyParticulars.firstChild);
        }

        const dl = el(
            "dl",
            { class: "data-dl" },
            createDlRow("IMO Number", vessel.imo),
            createDlRow("MMSI", vessel.mmsi),
            createDlRow("Call Sign", vessel.callsign),
            createDlRow("Ship Type", vessel.vessel_type),
            createDlRow("Size Segment", vessel.vessel_size_segment),
            createDlRow("Flag State", vessel.flag),
            createDlRow("Gross Tonnage (GRT)", formatNumber(vessel.grt)),
            createDlRow("Deadweight (DWT)", formatNumber(vessel.dwt)),
            createDlRow("Year Built & Age", vesselAge(vessel.year_built)),
            createDlRow("Length", formatMetres(vessel.length)),
            createDlRow("Beam", formatMetres(vessel.beam)),
            createDlRow("Draught", formatMetres(vessel.draught)),
            createDlRow("Last Dry Dock", formatDate(vessel.last_dry_dock)),
            createDlRow("Last Renewal Survey", formatDate(vessel.last_renewal_survey))
        );

        bodyParticulars.appendChild(dl);
    } catch (err) {
        renderError(bodyParticulars, `Error loading particulars: ${err.message}`, () => loadVesselData(vesselId));
    }
}

function createDlRow(term, definition) {
    const textVal = definition === null || definition === undefined || definition === "" ? "\u2014" : String(definition);
    return el(
        "div",
        { class: "dl-row" },
        el("dt", {}, term),
        el("dd", {}, textVal)
    );
}

/**
 * 3 & 6. Load Vessel Observations (Latest position + History table).
 */
async function loadObservationsData(vesselId) {
    const bodyPosition = document.getElementById("body-position");
    const bodyHistory = document.getElementById("body-history");

    if (bodyPosition) setLoading(bodyPosition, "Loading latest position...");
    if (bodyHistory) setLoading(bodyHistory, "Loading position history...");

    try {
        const response = await api.get(`/api/v1/vessels/${vesselId}/observations/?page_size=25`);
        const observations = Array.isArray(response) ? response : (response.results || []);
        observationsNextUrl = response.next || null;

        // Render Card 3: Latest Position & Voyage
        if (bodyPosition) {
            while (bodyPosition.firstChild) {
                bodyPosition.removeChild(bodyPosition.firstChild);
            }

            if (observations.length === 0) {
                setEmpty(bodyPosition, "No position observations recorded for this vessel.");
            } else {
                const latest = observations[0];
                renderLatestPositionCard(bodyPosition, latest);
            }
        }

        // Render Card 6: Position History
        if (bodyHistory) {
            while (bodyHistory.firstChild) {
                bodyHistory.removeChild(bodyHistory.firstChild);
            }

            if (observations.length === 0) {
                setEmpty(bodyHistory, "No position history available.");
            } else {
                renderPositionHistoryCard(bodyHistory, observations, vesselId);
            }
        }
    } catch (err) {
        if (bodyPosition) {
            renderError(bodyPosition, `Error loading position: ${err.message}`, () => loadObservationsData(vesselId));
        }
        if (bodyHistory) {
            renderError(bodyHistory, `Error loading history: ${err.message}`, () => loadObservationsData(vesselId));
        }
    }
}

function renderLatestPositionCard(container, obs) {
    const latFormatted = formatCoord(obs.latitude);
    const lonFormatted = formatCoord(obs.longitude);
    const coordsText = obs.latitude !== null && obs.longitude !== null ? `${latFormatted}, ${lonFormatted}` : "\u2014";

    const dl = el(
        "dl",
        { class: "data-dl" },
        createDlRow("Observed At (UTC)", formatDateTimeUtc(obs.timestamp)),
        createDlRow("Coordinates", coordsText),
        createDlRow("Speed", obs.speed !== null && obs.speed !== undefined ? `${obs.speed} knots` : "\u2014"),
        createDlRow("Course", obs.course !== null && obs.course !== undefined ? `${obs.course}°` : "\u2014"),
        createDlRow("Navigational Status", navStatusLabel(obs.navigational_status)),
        createDlRow("Port Area", portAreaLabel(obs.port_area)),
        createDlRow("Current Port", obs.current_port || "\u2014"),
        createDlRow("Last Port & Time", formatPortAndTime(obs.last_port, obs.last_port_time)),
        createDlRow("Next Port (UN/LOCODE)", formatNextPort(obs.destination, obs.next_port_unlocode)),
        createDlRow("ETA (Calculated)", formatDateTimeUtc(obs.eta_calc)),
        createDlRow("ETA Last Updated", formatDateTimeUtc(obs.eta_updated))
    );

    container.appendChild(dl);

    // Stale position warning indicator (>24 hours)
    const ageHours = positionAgeHours(obs.timestamp);
    if (ageHours !== null && ageHours >= 24) {
        const staleWarning = el(
            "div",
            { class: "stale-warning", role: "status" },
            el("span", { class: "stale-badge" }, "STALE"),
            el("span", {}, `Position is ${ageHours} hours old`)
        );
        container.appendChild(staleWarning);
    }

    // OpenStreetMap link
    const mapUrl = osmUrl(obs.latitude, obs.longitude);
    if (mapUrl) {
        const osmWrap = el(
            "div",
            { class: "external-link-wrap" },
            el(
                "a",
                {
                    href: mapUrl,
                    target: "_blank",
                    rel: "noopener noreferrer",
                    class: "external-link",
                },
                "Open in OpenStreetMap \u2197"
            ),
            el("span", { class: "external-note" }, "(opens an external site)")
        );
        container.appendChild(osmWrap);
    }
}

function formatPortAndTime(port, time) {
    if (!port && !time) return "\u2014";
    if (port && time) return `${port} (${formatDateTimeUtc(time)})`;
    return port || formatDateTimeUtc(time);
}

function formatNextPort(destination, unlocode) {
    if (!destination && !unlocode) return "\u2014";
    if (destination && unlocode) return `${destination} [${unlocode}]`;
    return destination || `[${unlocode}]`;
}

function renderPositionHistoryCard(container, initialObservations, vesselId) {
    const tableWrap = el("div", { class: "table-scroll vessel-table-wrap", tabindex: "0", role: "region", "aria-label": "Position observations history" });
    const table = el("table", { class: "vessel-table" });

    table.appendChild(
        el("caption", { class: "visually-hidden" }, "Historical position observations for this vessel")
    );

    const thead = el(
        "thead",
        {},
        el(
            "tr",
            {},
            el("th", { scope: "col" }, "Observed At (UTC)"),
            el("th", { scope: "col" }, "Port Area"),
            el("th", { scope: "col" }, "Status"),
            el("th", { scope: "col" }, "Speed"),
            el("th", { scope: "col" }, "Current Port"),
            el("th", { scope: "col" }, "Next Port"),
            el("th", { scope: "col" }, "Source")
        )
    );

    const tbody = el("tbody", { id: "history-tbody" });

    for (const obs of initialObservations) {
        tbody.appendChild(createObservationRow(obs));
    }

    table.appendChild(thead);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    container.appendChild(tableWrap);

    // Load More container
    const loadMoreRow = el("div", { class: "load-more-row", id: "history-load-more-container" });
    if (observationsNextUrl) {
        const btnLoadMore = el(
            "button",
            {
                type: "button",
                class: "btn-load-more",
                onClick: async () => {
                    await loadMoreObservations(tbody, loadMoreRow);
                },
            },
            "Load more observations"
        );
        loadMoreRow.appendChild(btnLoadMore);
    }
    container.appendChild(loadMoreRow);
}

function createObservationRow(obs) {
    return el(
        "tr",
        {},
        el("td", {}, formatDateTimeUtc(obs.timestamp)),
        el("td", {}, portAreaLabel(obs.port_area)),
        el("td", {}, navStatusLabel(obs.navigational_status)),
        el("td", {}, obs.speed !== null && obs.speed !== undefined ? `${obs.speed} kn` : "\u2014"),
        el("td", {}, obs.current_port || "\u2014"),
        el("td", {}, obs.destination || (obs.next_port_unlocode ? `[${obs.next_port_unlocode}]` : "\u2014")),
        el("td", {}, obs.source || "\u2014")
    );
}

async function loadMoreObservations(tbody, loadMoreContainer) {
    if (!observationsNextUrl) return;

    while (loadMoreContainer.firstChild) {
        loadMoreContainer.removeChild(loadMoreContainer.firstChild);
    }
    loadMoreContainer.appendChild(el("span", { class: "loading-text" }, "Loading more observations..."));

    try {
        const response = await api.get(observationsNextUrl);
        const moreObs = Array.isArray(response) ? response : (response.results || []);
        observationsNextUrl = response.next || null;

        for (const obs of moreObs) {
            tbody.appendChild(createObservationRow(obs));
        }

        while (loadMoreContainer.firstChild) {
            loadMoreContainer.removeChild(loadMoreContainer.firstChild);
        }

        const announcement = el("span", { class: "visually-hidden", role: "status", "aria-live": "polite" }, `${moreObs.length} more observations loaded`);
        loadMoreContainer.appendChild(announcement);

        if (observationsNextUrl) {
            const btn = el(
                "button",
                {
                    type: "button",
                    class: "btn-load-more",
                    onClick: async () => {
                        await loadMoreObservations(tbody, loadMoreContainer);
                    },
                },
                "Load more observations"
            );
            loadMoreContainer.appendChild(btn);
        }
    } catch (err) {
        while (loadMoreContainer.firstChild) {
            loadMoreContainer.removeChild(loadMoreContainer.firstChild);
        }
        loadMoreContainer.appendChild(
            el(
                "div",
                { class: "error-state" },
                el("span", {}, `Failed to load more: ${err.message}`),
                el(
                    "button",
                    {
                        type: "button",
                        class: "btn-retry",
                        onClick: async () => {
                            await loadMoreObservations(tbody, loadMoreContainer);
                        },
                    },
                    "Retry"
                )
            )
        );
    }
}

/**
 * 4. Load Opportunities table & update Header badge.
 */
async function loadOpportunitiesData(vesselId) {
    const bodyOpps = document.getElementById("body-opportunities");
    if (!bodyOpps) return;

    setLoading(bodyOpps, "Loading opportunities...");

    try {
        const response = await api.get(`/api/v1/opportunities/?vessel=${vesselId}&ordering=-detected_at`);
        const opportunities = Array.isArray(response) ? response : (response.results || []);

        // Filter and identify newest open opportunity for Header badge
        const openOpps = opportunities.filter((o) => !CLOSED_STAGES.has(o.stage));
        updateHeaderBadge(openOpps.length > 0 ? openOpps[0] : null);

        while (bodyOpps.firstChild) {
            bodyOpps.removeChild(bodyOpps.firstChild);
        }

        if (opportunities.length === 0) {
            setEmpty(bodyOpps, "No commercial opportunities recorded for this vessel.");
            return;
        }

        // Sort opportunities: Open ones first, then closed, preserving detected_at order
        const sortedOpps = [
            ...openOpps,
            ...opportunities.filter((o) => CLOSED_STAGES.has(o.stage)),
        ];

        renderOpportunitiesTable(bodyOpps, sortedOpps);
    } catch (err) {
        renderError(bodyOpps, `Error loading opportunities: ${err.message}`, () => loadOpportunitiesData(vesselId));
    }
}

function updateHeaderBadge(newestOpenOpp) {
    const badgeContainer = document.getElementById("header-badge-container");
    if (!badgeContainer) return;

    while (badgeContainer.firstChild) {
        badgeContainer.removeChild(badgeContainer.firstChild);
    }

    if (!newestOpenOpp || !newestOpenOpp.band) {
        return;
    }

    const bandLower = String(newestOpenOpp.band).toLowerCase();
    const scoreText = newestOpenOpp.score !== null && newestOpenOpp.score !== undefined ? ` (Score: ${newestOpenOpp.score})` : "";
    const badge = el(
        "div",
        {
            class: `header-lead-badge band-${bandLower}`,
            role: "status",
            "aria-label": `Priority band ${newestOpenOpp.band}`,
        },
        el("span", { class: "badge-band" }, `${newestOpenOpp.band}${scoreText}`)
    );

    badgeContainer.appendChild(badge);
}

function renderOpportunitiesTable(container, opps) {
    const tableWrap = el("div", { class: "table-scroll vessel-table-wrap", tabindex: "0", role: "region", "aria-label": "Vessel opportunities table" });
    const table = el("table", { class: "vessel-table" });

    table.appendChild(
        el("caption", { class: "visually-hidden" }, "Opportunities pipeline for this vessel")
    );

    const thead = el(
        "thead",
        {},
        el(
            "tr",
            {},
            el("th", { scope: "col" }, "Port"),
            el("th", { scope: "col" }, "Zone"),
            el("th", { scope: "col" }, "Stage"),
            el("th", { scope: "col" }, "Score & Band"),
            el("th", { scope: "col" }, "ETA (UTC)"),
            el("th", { scope: "col" }, "Detected At"),
            el("th", { scope: "col" }, "Lead Reason"),
            el("th", { scope: "col" }, "Actions")
        )
    );

    const tbody = el("tbody");

    for (const opp of opps) {
        const portName = (opp.port_summary && opp.port_summary.name) || (opp.port ? `Port ${opp.port}` : "\u2014");
        const bandLower = opp.band ? String(opp.band).toLowerCase() : "low";
        const scoreVal = opp.score !== null && opp.score !== undefined ? opp.score : "\u2014";

        const tr = el(
            "tr",
            {},
            el("td", {}, portName),
            el("td", {}, opp.zone_label || opp.zone || "\u2014"),
            el("td", {}, opp.stage_label || opp.stage || "\u2014"),
            el(
                "td",
                {},
                el("span", { class: `table-badge band-${bandLower}` }, `${opp.band || "\u2014"} (${scoreVal})`)
            ),
            el("td", {}, formatEtaAndSource(opp.eta, opp.eta_source)),
            el("td", {}, formatDateTimeUtc(opp.detected_at)),
            el(
                "td",
                { class: "cell-lead-reason" },
                el("span", { class: "lead-reason-clamp", title: opp.lead_reason || "\u2014" }, opp.lead_reason || "\u2014")
            ),
            el(
                "td",
                {},
                el(
                    "a",
                    {
                        href: `/leads/${opp.id}/`,
                        class: "action-link",
                    },
                    "Open lead"
                )
            )
        );
        tbody.appendChild(tr);
    }

    table.appendChild(thead);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    container.appendChild(tableWrap);
}

function formatEtaAndSource(eta, source) {
    if (!eta) return "\u2014";
    const dt = formatDateTimeUtc(eta);
    if (!source) return dt;
    const sourceWord = source === "eta_calc" ? "calc" : (source === "ais_eta" ? "AIS" : source);
    return `${dt} [${sourceWord}]`;
}

/**
 * The "Look up owner" button. One Kpler lookup for this vessel; the server enforces
 * the daily share for the button, the monthly allowance and the re-check period.
 */
function renderLookupBar(vesselId, checkedAt, hasData) {
    const message = el("p", { class: "form-error", role: "status" });
    const button = el("button", { type: "button", class: "btn btn-secondary" }, checkedAt ? "Look up again" : "Look up owner");
    const bar = el("div", { class: "lookup-bar" });
    if (hasData) bar.appendChild(el("p", { class: "lookup-note" }, ownerLookupText(checkedAt, true)));
    button.addEventListener("click", async () => {
        button.disabled = true;
        message.textContent = "Looking up…";
        try {
            await api.post(`/api/v1/ingest/vessels/${vesselId}/lookup-owner/`, {});
            await Promise.all([loadRelationshipsData(vesselId), loadOpportunitiesData(vesselId)]);
        } catch (err) {
            message.textContent = err.message || "Owner lookup failed.";
            button.disabled = false;
        }
    });
    bar.append(button, message);
    return bar;
}

/**
 * 5. Load Owners and Managers relationships.
 */
async function loadRelationshipsData(vesselId) {
    let checkedAt = null;
    let mailLog = {};
    const bodyRels = document.getElementById("body-relationships");
    if (!bodyRels) return;

    setLoading(bodyRels, "Loading owners and managers...");

    try {
        const [response, vesselInfo, mailInfo] = await Promise.all([
            api.get(`/api/v1/relationships/?vessel=${vesselId}&is_current=true`),
            api.get(`/api/v1/vessels/${vesselId}/`).catch(() => null),
            api.get(`/api/v1/outreach/log/?vessel=${vesselId}`).catch(() => null),
        ]);
        checkedAt = vesselInfo ? vesselInfo.ownership_checked_at : null;
        mailLog = indexByCompany(mailInfo ? mailInfo.results : []);
        const relationships = Array.isArray(response) ? response : (response.results || []);

        while (bodyRels.firstChild) {
            bodyRels.removeChild(bodyRels.firstChild);
        }

        const groups = relationships.length ? groupContacts(relationships) : [];
        if (groups.length === 0) {
            setEmpty(bodyRels, ownerLookupText(checkedAt, false));
            bodyRels.appendChild(renderLookupBar(vesselId, checkedAt, false));
            return;
        }

        const listWrap = el("div", { class: "contacts-list" });

        for (const group of groups) {
            const groupEl = el("div", { class: "contact-group" });
            groupEl.appendChild(el("h3", { class: "contact-role-title" }, group.roleLabel));

            for (const rel of group.items) {
                groupEl.appendChild(renderContactEntry(rel, mailLog[String(rel.company)], () => loadRelationshipsData(vesselId)));
            }

            listWrap.appendChild(groupEl);
        }

        bodyRels.appendChild(listWrap);
        bodyRels.appendChild(renderLookupBar(vesselId, checkedAt, true));
    } catch (err) {
        renderError(bodyRels, `Error loading contacts: ${err.message}`, () => loadRelationshipsData(vesselId));
    }
}

function renderContactEntry(rel, lastMail, reload) {
    const c = rel.company_detail || {};
    const companyName = c.name || "Unknown Company";
    const isVerified = Boolean(rel.verified);

    const entry = el("div", { class: "contact-entry" });

    // Top row: Company name + Verification Badge
    const topRow = el(
        "div",
        { class: "contact-entry-top" },
        el("span", { class: "contact-name" }, companyName),
        el(
            "span",
            {
                class: `contact-verification-badge ${isVerified ? "verified" : "unverified"}`,
            },
            isVerified ? "Verified" : "Unverified public data"
        )
    );
    entry.appendChild(topRow);

    // Details row: Country, Website, Email, Source, Start Date
    const detailsRow = el("div", { class: "contact-details" });

    if (c.country) {
        detailsRow.appendChild(el("span", {}, el("strong", {}, "Country: "), c.country));
    }

    if (c.website) {
        const safeUrl = safeHttpUrl(c.website);
        if (safeUrl) {
            detailsRow.appendChild(
                el(
                    "span",
                    {},
                    el("strong", {}, "Website: "),
                    el(
                        "a",
                        {
                            href: safeUrl.href,
                            target: "_blank",
                            rel: "noopener noreferrer",
                        },
                        safeUrl.text
                    )
                )
            );
        } else {
            detailsRow.appendChild(el("span", {}, el("strong", {}, "Website: "), c.website));
        }
    }

    if (c.email) {
        const safeMail = safeMailto(c.email);
        if (safeMail) {
            detailsRow.appendChild(
                el(
                    "span",
                    {},
                    el("strong", {}, "Email: "),
                    el("a", { href: safeMail }, c.email.trim())
                )
            );
        } else {
            detailsRow.appendChild(el("span", {}, el("strong", {}, "Email: "), c.email));
        }
    }

    if (rel.source) {
        detailsRow.appendChild(el("span", {}, el("strong", {}, "Source: "), rel.source));
    }

    if (rel.start_date) {
        detailsRow.appendChild(el("span", {}, el("strong", {}, "Since: "), formatDate(rel.start_date)));
    }

    entry.appendChild(detailsRow);

    // Who confirmed it, when, and how
    if (isVerified) {
        const confirmed = verificationText(rel);
        const lines = [el("span", { class: "contact-verified-line" }, confirmed)];
        if (rel.verification_note) {
            lines.push(el("span", { class: "contact-verified-note" }, `\u201c${rel.verification_note}\u201d`));
        }
        entry.appendChild(el("div", { class: "contact-verified" }, ...lines));
    }

    entry.appendChild(renderMailControls(rel, c, lastMail, reload || (() => {})));
    entry.appendChild(renderVerifyControls(rel, entry));
    return entry;
}

/**
 * "Mark verified" / "Undo verification" controls for one owner or manager link.
 * Marking opens a small form (optional note); both actions call the API and reload the section.
 */
function renderVerifyControls(rel, entry) {
    const host = el("div", { class: "contact-actions" });
    const vesselId = document.querySelector("[data-vessel-id]").dataset.vesselId;

    async function send(action, body, setError, setBusy) {
        setBusy(true);
        try {
            await api.post(`/api/v1/relationships/${rel.id}/${action}/`, body);
            toast(action === "verify" ? "Marked as verified." : "Verification removed.", "success");
            await Promise.all([loadRelationshipsData(vesselId), loadOpportunitiesData(vesselId)]);
        } catch (err) {
            const noteErr = err && err.data && err.data.note;
            setError((Array.isArray(noteErr) ? noteErr[0] : null) || (err && err.message) || "Could not save. Try again.");
            setBusy(false);
        }
    }

    if (rel.verified) {
        const undo = el("button", { type: "button", class: "btn btn-quiet btn-sm", "aria-label": `Remove verification for ${(rel.company_detail || {}).name || "this company"}` }, "Undo verification");
        const error = el("span", { class: "form-error", role: "alert" });
        undo.addEventListener("click", () => send("unverify", {}, (m) => { error.textContent = m; }, (b) => { undo.disabled = b; }));
        host.appendChild(undo);
        host.appendChild(error);
        return host;
    }

    const open = el("button", { type: "button", class: "btn btn-secondary btn-sm", "aria-expanded": "false", "aria-label": `Mark ${(rel.company_detail || {}).name || "this company"} as verified` }, "Mark verified");
    const form = el("form", { class: "verify-form", hidden: true });
    const noteId = `verify-note-${rel.id}`;
    const note = el("textarea", { id: noteId, class: "form-textarea", rows: "2", maxlength: "300", placeholder: "e.g. Called the company and confirmed they manage this vessel" });
    const error = el("span", { class: "form-error", role: "alert" });
    const confirmBtn = el("button", { type: "submit", class: "btn btn-primary btn-sm" }, "Confirm");
    const cancel = el("button", { type: "button", class: "btn btn-quiet btn-sm" }, "Cancel");
    form.appendChild(el("label", { for: noteId, class: "verify-label" }, "How did you confirm it? (optional)"));
    form.appendChild(note);
    form.appendChild(el("div", { class: "verify-buttons" }, confirmBtn, cancel, error));

    open.addEventListener("click", () => {
        form.hidden = false;
        open.hidden = true;
        open.setAttribute("aria-expanded", "true");
        note.focus();
    });
    cancel.addEventListener("click", () => {
        form.hidden = true;
        open.hidden = false;
        open.setAttribute("aria-expanded", "false");
        error.textContent = "";
        note.value = "";
        open.focus();
    });
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        error.textContent = "";
        send("verify", { note: note.value }, (m) => { error.textContent = m; }, (b) => { confirmBtn.disabled = b; cancel.disabled = b; });
    });
    host.appendChild(open);
    host.appendChild(form);
    return host;
}

/**
 * Initialize vessel detail page safely when DOM is ready.
 */
onReady(() => {
    registerGlobalErrorHandlers();
    try {
        initBackLink();

        const rootElement = document.querySelector("[data-vessel-id]");
        if (!rootElement) return;

        const vesselId = rootElement.dataset.vesselId;
        if (!vesselId) return;

        // Trigger all four requests in parallel; each updates its own card upon response
        loadVesselData(vesselId);
        loadObservationsData(vesselId);
        loadOpportunitiesData(vesselId);
        loadRelationshipsData(vesselId);
    } catch (err) {
        const main = document.getElementById("main") || document.body;
        renderPageCrash(main, "Vessel controller initialization failed", err);
    }
});
