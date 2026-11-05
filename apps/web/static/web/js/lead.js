/**
 * apps/web/static/web/js/lead.js
 * Lead detail & pipeline page controller.
 * Handles parallel loading of lead data, notes, and stage history.
 * Manages stage changes, confirmation modal, note submission, and pagination.
 * DOM is strictly constructed using el() from ui.js; network calls use api.js only.
 */

import { api, ApiError } from "./api.js";
import {
    el,
    formatUtc,
    formatNumber,
    dash,
    bandBadge,
    toast,
    renderError,
    onReady,
    registerGlobalErrorHandlers,
    renderPageCrash,
} from "./ui.js";
import { etaRelative, etaSourceLabel } from "./board-logic.js";
import {
    stageOptions,
    progressSteps,
    needsConfirm,
    validateNote,
    noteCounterText,
    buildPatchBody,
    actorName,
    historyLabel,
    canSubmitStage,
} from "./lead-logic.js";
import { STAGES } from "./stages.js";

// Global state for this page instance
let leadId = null;
let currentOpportunity = null;
let notesNextUrl = null;
let historyNextUrl = null;
let pendingTransition = null;
let isStageBusy = false;

/**
 * Configure back link to preserve previous lead board filters if stored in sessionStorage.
 */
function initBackLink() {
    const backLink = document.getElementById("back-to-board-link");
    if (!backLink) return;

    try {
        const storedQuery = sessionStorage.getItem("board_query");
        if (storedQuery && typeof storedQuery === "string") {
            const cleanQuery = storedQuery.startsWith("?") ? storedQuery : `?${storedQuery}`;
            backLink.href = `/${cleanQuery}`;
        } else {
            backLink.href = "/";
        }
    } catch {
        backLink.href = "/";
    }
}

/**
 * Render Card 1: Header information.
 */
function renderHeader(opp) {
    if (!opp) return;

    // Vessel title and link
    const vesselLink = document.getElementById("header-vessel-link");
    if (vesselLink && opp.vessel_summary) {
        vesselLink.href = `/vessels/${opp.vessel}/`;
        vesselLink.textContent = opp.vessel_summary.name || "Unknown Vessel";
    }

    // Subtitle items
    const summary = opp.vessel_summary || {};
    const portSummary = opp.port_summary || {};

    const imoEl = document.getElementById("header-imo");
    if (imoEl) imoEl.textContent = dash(summary.imo);

    const mmsiEl = document.getElementById("header-mmsi");
    if (mmsiEl) mmsiEl.textContent = dash(summary.mmsi);

    const typeEl = document.getElementById("header-type");
    if (typeEl) typeEl.textContent = dash(summary.vessel_type);

    const grtEl = document.getElementById("header-grt");
    if (grtEl) grtEl.textContent = formatNumber(summary.grt);

    const flagEl = document.getElementById("header-flag");
    if (flagEl) flagEl.textContent = dash(summary.flag);

    const portEl = document.getElementById("header-port");
    if (portEl) {
        const pName = portSummary.name || "—";
        const pLoc = portSummary.un_locode ? ` (${portSummary.un_locode})` : "";
        portEl.textContent = `${pName}${pLoc}`;
    }

    // Header Badges - only render chips that have valid values
    const badgeContainer = document.getElementById("header-badges");
    if (badgeContainer) {
        while (badgeContainer.firstChild) {
            badgeContainer.removeChild(badgeContainer.firstChild);
        }

        // Score Band Badge
        if (opp.band) {
            badgeContainer.appendChild(bandBadge(opp.band));
        }

        // Numeric Score Badge
        if (opp.score !== null && opp.score !== undefined) {
            const scoreBadge = el(
                "span",
                { class: "badge badge-score", title: "Lead Score" },
                `${opp.score} pts`
            );
            badgeContainer.appendChild(scoreBadge);
        }

        // Zone Badge
        const zoneVal = opp.zone_label || opp.zone;
        if (zoneVal) {
            const zoneBadge = el(
                "span",
                { class: "badge badge-zone", title: "Arrival Zone" },
                zoneVal
            );
            badgeContainer.appendChild(zoneBadge);
        }

        // Inbound Tag
        if (opp.is_inbound) {
            const inboundBadge = el(
                "span",
                { class: "badge badge-inbound", title: "Inbound to port" },
                "Inbound"
            );
            badgeContainer.appendChild(inboundBadge);
        }
    }

    // Meta definition list (ETA, Source, Reason)
    const metaEta = document.getElementById("header-meta-eta");
    if (metaEta) {
        if (!opp.eta) {
            metaEta.textContent = "None recorded";
        } else {
            const utcStr = formatUtc(opp.eta);
            const relStr = etaRelative(opp.eta);
            metaEta.textContent = `${utcStr} (${relStr})`;
        }
    }

    const metaSource = document.getElementById("header-meta-source");
    if (metaSource) {
        metaSource.textContent = etaSourceLabel(opp.eta_source) || opp.eta_source || "—";
    }

    const metaReason = document.getElementById("header-meta-reason");
    if (metaReason) {
        metaReason.textContent = opp.lead_reason || "No lead rationale recorded.";
    }
}

/**
 * Render Card 2: Progress Strip.
 */
function renderProgressStrip(currentStage) {
    const container = document.getElementById("progress-strip-container");
    if (!container) return;

    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }

    const { steps, isFollowUpLater, isLost, sideStates } = progressSteps(currentStage);

    // Main path pipeline list
    const stepList = el("ol", { class: "progress-strip", role: "list" });
    for (const step of steps) {
        const isCurrent = step.state === "current";
        const attrs = {
            class: `progress-step step-${step.state}`,
        };
        if (isCurrent) {
            attrs["aria-current"] = "step";
        }
        stepList.appendChild(el("li", attrs, step.label));
    }
    container.appendChild(stepList);

    // Side states strip
    const sideStrip = el("div", { class: "side-states-strip" }, el("span", {}, "Side states:"));
    for (const side of sideStates) {
        const isCurrent = side.isCurrent;
        let activeClass = "";
        if (isCurrent) {
            activeClass = side.value === "lost" ? "active-lost" : "active-follow-up";
        }
        const attrs = {
            class: `side-state-badge ${activeClass}`.trim(),
        };
        if (isCurrent) {
            attrs["aria-current"] = "step";
        }
        sideStrip.appendChild(el("span", attrs, side.label));
    }
    container.appendChild(sideStrip);
}

/**
 * Populate and manage Stage Change Form.
 */
function populateStageSelect(currentStage) {
    const select = document.getElementById("stage-select");
    if (!select) return;

    while (select.firstChild) {
        select.removeChild(select.firstChild);
    }

    const options = stageOptions(currentStage);
    for (const opt of options) {
        const attrs = { value: opt.value };
        if (opt.isCurrent) {
            attrs.selected = "selected";
        }
        const text = opt.isCurrent ? `${opt.label} (current)` : opt.label;
        select.appendChild(el("option", attrs, text));
    }
}

/**
 * Evaluate stage form button state and same-stage hint.
 */
function updateStageButtonState() {
    const select = document.getElementById("stage-select");
    const textarea = document.getElementById("stage-note-input");
    const updateBtn = document.getElementById("stage-update-btn");
    const sameHint = document.getElementById("stage-same-hint");

    if (!select || !textarea || !updateBtn || !currentOpportunity) return;

    const selectedStage = select.value;
    const trimmedNote = textarea.value.trim();
    const canSubmit = canSubmitStage(currentOpportunity.stage, selectedStage, trimmedNote, isStageBusy);

    updateBtn.disabled = !canSubmit;

    if (selectedStage === currentOpportunity.stage && trimmedNote.length > 0) {
        if (sameHint) sameHint.classList.remove("hidden");
    } else {
        if (sameHint) sameHint.classList.add("hidden");
    }
}

/**
 * Initialize Stage Card event listeners and confirmation modal.
 */
function initStageForm() {
    const form = document.getElementById("stage-change-form");
    const select = document.getElementById("stage-select");
    const textarea = document.getElementById("stage-note-input");
    const counter = document.getElementById("stage-note-counter");
    const errorEl = document.getElementById("stage-error");

    const dialog = document.getElementById("confirm-stage-dialog");
    const dialogMessage = document.getElementById("dialog-message");
    const dialogCancelBtn = document.getElementById("dialog-cancel-btn");
    const dialogConfirmBtn = document.getElementById("dialog-confirm-btn");

    if (!form || !select || !textarea) return;

    select.addEventListener("change", () => {
        if (errorEl) errorEl.classList.add("hidden");
        updateStageButtonState();
    });

    textarea.addEventListener("input", () => {
        if (counter) {
            counter.textContent = noteCounterText(textarea.value.length, 2000);
        }
        if (errorEl) errorEl.classList.add("hidden");
        updateStageButtonState();
    });

    // Confirmation dialog cancel / close
    if (dialogCancelBtn && dialog) {
        dialogCancelBtn.addEventListener("click", () => {
            dialog.close();
            pendingTransition = null;
        });
    }

    if (dialog) {
        dialog.addEventListener("cancel", () => {
            pendingTransition = null;
        });
    }

    // Confirmation dialog confirm
    if (dialogConfirmBtn && dialog) {
        dialogConfirmBtn.addEventListener("click", async () => {
            dialog.close();
            if (pendingTransition) {
                const { newStage, noteText } = pendingTransition;
                pendingTransition = null;
                await executeStagePatch(newStage, noteText);
            }
        });
    }

    // Form submit
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const selectedStage = select.value;
        const noteText = textarea.value;

        if (!currentOpportunity || selectedStage === currentOpportunity.stage) {
            return;
        }

        if (needsConfirm(selectedStage)) {
            pendingTransition = { newStage: selectedStage, noteText };
            if (dialog && dialogMessage) {
                const stageObj = STAGES.find((s) => s.value === selectedStage);
                const targetLabel = stageObj ? stageObj.label : selectedStage;
                const vesselName = currentOpportunity.vessel_summary?.name || "this vessel";
                dialogMessage.textContent = `Move lead for ${vesselName} to "${targetLabel}"?`;
                dialog.showModal();
            }
        } else {
            await executeStagePatch(selectedStage, noteText);
        }
    });
}

/**
 * Execute PATCH to update stage (with optional note).
 */
async function executeStagePatch(newStage, noteText) {
    const errorEl = document.getElementById("stage-error");
    const textarea = document.getElementById("stage-note-input");
    const counter = document.getElementById("stage-note-counter");

    if (errorEl) errorEl.classList.add("hidden");
    isStageBusy = true;
    updateStageButtonState();

    const body = buildPatchBody(currentOpportunity.stage, newStage, noteText);

    try {
        const updated = await api.patch(`/api/v1/opportunities/${leadId}/`, body);
        currentOpportunity = updated;
        toast("Stage updated", "success");

        // Update UI
        renderHeader(updated);
        renderProgressStrip(updated.stage);
        populateStageSelect(updated.stage);

        // Clear stage note
        if (textarea) {
            textarea.value = "";
        }
        if (counter) {
            counter.textContent = noteCounterText(0, 2000);
        }

        // Refresh first page of notes and history
        loadNotes(leadId, true).catch(() => {});
        loadHistory(leadId, true).catch(() => {});
    } catch (err) {
        if (err.status === 409) {
            // Concurrency conflict safeguard
            const msg =
                err.detail ||
                err.message ||
                "This lead's stage was changed by someone else. Reload the page to see the latest stage.";
            if (errorEl) {
                errorEl.textContent = msg;
                errorEl.classList.remove("hidden");
            }
            // Note text is preserved in textarea!
            // Reload opportunity from server to update UI state
            try {
                const refreshed = await api.get(`/api/v1/opportunities/${leadId}/`);
                currentOpportunity = refreshed;
                renderHeader(refreshed);
                renderProgressStrip(refreshed.stage);
                populateStageSelect(refreshed.stage);
                loadNotes(leadId, true).catch(() => {});
                loadHistory(leadId, true).catch(() => {});
            } catch {
                // If refresh fails, keep current view
            }
        } else if (err.status === 400) {
            if (errorEl) {
                errorEl.textContent = err.detail || err.message || "Invalid stage update.";
                errorEl.classList.remove("hidden");
            }
        } else {
            if (errorEl) {
                errorEl.textContent = err.message || "Failed to update stage.";
                errorEl.classList.remove("hidden");
            }
        }
    } finally {
        isStageBusy = false;
        updateStageButtonState();
    }
}

/**
 * Card 3: Notes Form & Pagination.
 */
function renderNoteItem(note) {
    return el(
        "div",
        { class: "note-card" },
        el(
            "div",
            { class: "note-header" },
            el("span", { class: "note-author" }, actorName(note.author)),
            el("span", { class: "note-date" }, formatUtc(note.created_at))
        ),
        el("p", { class: "note-text" }, note.text || "")
    );
}

async function loadNotes(id, reset = false) {
    const listContainer = document.getElementById("notes-list");
    const paginationContainer = document.getElementById("notes-pagination");
    if (!listContainer) return;

    if (reset) {
        notesNextUrl = null;
        while (listContainer.firstChild) listContainer.removeChild(listContainer.firstChild);
        if (paginationContainer) {
            while (paginationContainer.firstChild) paginationContainer.removeChild(paginationContainer.firstChild);
        }
        listContainer.appendChild(el("div", { class: "loading-state" }, "Loading notes..."));
    }

    const url = notesNextUrl || `/api/v1/opportunities/${id}/notes/?page_size=25`;

    try {
        const data = await api.get(url);
        notesNextUrl = data.next || null;

        if (reset) {
            while (listContainer.firstChild) listContainer.removeChild(listContainer.firstChild);
        }

        const notes = data.results || (Array.isArray(data) ? data : []);

        if (notes.length === 0 && listContainer.children.length === 0) {
            listContainer.appendChild(el("div", { class: "empty-state" }, "No notes yet."));
        } else {
            for (const note of notes) {
                listContainer.appendChild(renderNoteItem(note));
            }
        }

        // Pagination button
        if (paginationContainer) {
            while (paginationContainer.firstChild) paginationContainer.removeChild(paginationContainer.firstChild);
            if (notesNextUrl) {
                const loadMoreBtn = el(
                    "button",
                    {
                        type: "button",
                        class: "btn btn-load-more",
                        onClick: () => loadNotes(id, false),
                    },
                    "Load more notes"
                );
                paginationContainer.appendChild(loadMoreBtn);
            }
        }
    } catch (err) {
        renderError(listContainer, err.message || "Failed to load notes.", () => loadNotes(id, true));
    }
}

function initNoteForm() {
    const form = document.getElementById("note-add-form");
    const textarea = document.getElementById("note-text-input");
    const counter = document.getElementById("note-counter");
    const saveBtn = document.getElementById("note-save-btn");
    const errorEl = document.getElementById("note-error");
    const listContainer = document.getElementById("notes-list");

    if (!form || !textarea || !saveBtn) return;

    textarea.addEventListener("input", () => {
        const len = textarea.value.length;
        if (counter) {
            counter.textContent = noteCounterText(len, 2000);
        }
        const check = validateNote(textarea.value);
        saveBtn.disabled = !check.ok;
        if (errorEl) errorEl.classList.add("hidden");
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const check = validateNote(textarea.value);
        if (!check.ok) return;

        saveBtn.disabled = true;
        if (errorEl) errorEl.classList.add("hidden");

        try {
            const created = await api.post(`/api/v1/opportunities/${leadId}/notes/`, {
                text: check.trimmed,
            });

            toast("Note saved", "success");

            // Reset textarea
            textarea.value = "";
            if (counter) counter.textContent = noteCounterText(0, 2000);
            saveBtn.disabled = true;

            // Remove empty state if present
            const emptyEl = listContainer.querySelector(".empty-state");
            if (emptyEl) {
                listContainer.removeChild(emptyEl);
            }

            // Prepend new note immediately
            const noteEl = renderNoteItem(created);
            listContainer.insertBefore(noteEl, listContainer.firstChild);
        } catch (err) {
            if (errorEl) {
                errorEl.textContent = err.detail || err.message || "Failed to save note.";
                errorEl.classList.remove("hidden");
            }
            saveBtn.disabled = false;
        }
    });
}

/**
 * Card 4: Stage History.
 */
function renderHistoryItem(item) {
    let transitionText = "";
    if (item.from_stage) {
        const fromLabel = item.from_stage_label || historyLabel(item.from_stage);
        const toLabel = item.to_stage_label || historyLabel(item.to_stage);
        transitionText = `${fromLabel} → ${toLabel}`;
    } else {
        const toLabel = item.to_stage_label || historyLabel(item.to_stage);
        transitionText = `Created as ${toLabel || "Detected"}`;
    }

    return el(
        "div",
        { class: "history-card" },
        el("div", { class: "history-transition" }, transitionText),
        el(
            "div",
            { class: "history-meta" },
            el("span", { class: "history-actor" }, actorName(item.changed_by)),
            el("span", { class: "history-date" }, formatUtc(item.changed_at))
        )
    );
}

async function loadHistory(id, reset = false) {
    const listContainer = document.getElementById("history-list");
    const paginationContainer = document.getElementById("history-pagination");
    if (!listContainer) return;

    if (reset) {
        historyNextUrl = null;
        while (listContainer.firstChild) listContainer.removeChild(listContainer.firstChild);
        if (paginationContainer) {
            while (paginationContainer.firstChild) paginationContainer.removeChild(paginationContainer.firstChild);
        }
        listContainer.appendChild(el("div", { class: "loading-state" }, "Loading stage history..."));
    }

    const url = historyNextUrl || `/api/v1/opportunities/${id}/history/?page_size=25`;

    try {
        const data = await api.get(url);
        historyNextUrl = data.next || null;

        if (reset) {
            while (listContainer.firstChild) listContainer.removeChild(listContainer.firstChild);
        }

        const items = data.results || (Array.isArray(data) ? data : []);

        if (items.length === 0 && listContainer.children.length === 0) {
            listContainer.appendChild(
                el(
                    "div",
                    { class: "empty-state" },
                    "No stage changes recorded yet. Changes made from now on appear here."
                )
            );
        } else {
            for (const item of items) {
                listContainer.appendChild(renderHistoryItem(item));
            }
        }

        // Pagination button
        if (paginationContainer) {
            while (paginationContainer.firstChild) paginationContainer.removeChild(paginationContainer.firstChild);
            if (historyNextUrl) {
                const loadMoreBtn = el(
                    "button",
                    {
                        type: "button",
                        class: "btn btn-load-more",
                        onClick: () => loadHistory(id, false),
                    },
                    "Load more history"
                );
                paginationContainer.appendChild(loadMoreBtn);
            }
        }
    } catch (err) {
        renderError(listContainer, err.message || "Failed to load history.", () => loadHistory(id, true));
    }
}

/**
 * Card 5: Vessel Summary.
 */
function renderVesselSummary(summary, vesselId) {
    const container = document.getElementById("vessel-summary-details");
    if (!container) return;

    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }

    if (!summary) {
        container.appendChild(el("div", { class: "empty-state" }, "No vessel details available."));
        return;
    }

    const dl = el(
        "dl",
        { class: "summary-dl" },
        el("dt", { class: "summary-dt" }, "IMO"),
        el("dd", { class: "summary-dd" }, dash(summary.imo)),
        el("dt", { class: "summary-dt" }, "MMSI"),
        el("dd", { class: "summary-dd" }, dash(summary.mmsi)),
        el("dt", { class: "summary-dt" }, "Type"),
        el("dd", { class: "summary-dd" }, dash(summary.vessel_type)),
        el("dt", { class: "summary-dt" }, "GRT"),
        el("dd", { class: "summary-dd" }, formatNumber(summary.grt)),
        el("dt", { class: "summary-dt" }, "DWT"),
        el("dd", { class: "summary-dd" }, formatNumber(summary.dwt)),
        el("dt", { class: "summary-dt" }, "Flag"),
        el("dd", { class: "summary-dd" }, dash(summary.flag)),
        el("dt", { class: "summary-dt" }, "Year Built"),
        el("dd", { class: "summary-dd" }, dash(summary.year_built))
    );
    container.appendChild(dl);

    const fullLink = document.getElementById("link-full-vessel");
    if (fullLink && (vesselId || summary.id)) {
        fullLink.href = `/vessels/${vesselId || summary.id}/`;
    }
}

/**
 * Main Page Initialization when DOM is ready.
 */
onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        const mainEl = document.querySelector("[data-lead-id]");
        if (!mainEl) return;

        leadId = mainEl.dataset.leadId;
        if (!leadId) return;

        initBackLink();
        initStageForm();
        initNoteForm();

        // 1. Fetch opportunity details
        try {
            const oppRes = await api.get(`/api/v1/opportunities/${leadId}/`);
            currentOpportunity = oppRes;

            // Render Card 1 (Header), Card 2 (Stage), and Card 5 (Vessel Summary)
            renderHeader(oppRes);
            renderProgressStrip(oppRes.stage);
            populateStageSelect(oppRes.stage);
            renderVesselSummary(oppRes.vessel_summary, oppRes.vessel);
            updateStageButtonState();
        } catch (err) {
            const header = document.getElementById("page-header");
            if (header) {
                renderError(header, err.message || "Failed to load lead.", () => window.location.reload());
            }
        }

        // 2. Fetch notes and history in parallel (failures do not block header or pipeline)
        loadNotes(leadId, true).catch(() => {});
        loadHistory(leadId, true).catch(() => {});
    } catch (err) {
        const main = document.getElementById("main") || document.body;
        renderPageCrash(main, "Lead controller initialization failed", err);
    }
});

