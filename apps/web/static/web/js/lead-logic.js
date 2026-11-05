/**
 * apps/web/static/web/js/lead-logic.js
 * Pure functions for lead detail pipeline, stage options, note validation, and history formatting.
 * Strictly no DOM operations and no network requests.
 */

import { STAGES, PIPELINE_ORDER, CLOSED_STAGE_VALUES } from "./stages.js";

/**
 * Return array of stage options with current stage marked.
 * @param {string} currentStage
 * @returns {Array<{ value: string, label: string, isCurrent: boolean }>}
 */
export function stageOptions(currentStage) {
    return STAGES.map((s) => ({
        value: s.value,
        label: s.label,
        isCurrent: s.value === currentStage,
    }));
}

/**
 * Return progress steps for the main path and status of side states.
 * @param {string} currentStage
 * @returns {{
 *   steps: Array<{ value: string, label: string, state: "done"|"current"|"todo" }>,
 *   isFollowUpLater: boolean,
 *   isLost: boolean,
 *   sideStates: Array<{ value: string, label: string, isCurrent: boolean }>
 * }}
 */
export function progressSteps(currentStage) {
    const stageMap = Object.fromEntries(STAGES.map((s) => [s.value, s.label]));
    const currIdx = PIPELINE_ORDER.indexOf(currentStage);

    const steps = PIPELINE_ORDER.map((val, idx) => {
        let state = "todo";
        if (currIdx !== -1) {
            if (idx < currIdx) {
                state = "done";
            } else if (idx === currIdx) {
                state = "current";
            }
        }
        return {
            value: val,
            label: stageMap[val] || val,
            state,
        };
    });

    const isFollowUpLater = currentStage === "follow_up_later";
    const isLost = currentStage === "lost";

    const sideStates = [
        {
            value: "follow_up_later",
            label: stageMap["follow_up_later"] || "Follow Up Later",
            isCurrent: isFollowUpLater,
        },
        {
            value: "lost",
            label: stageMap["lost"] || "Lost",
            isCurrent: isLost,
        },
    ];

    return {
        steps,
        isFollowUpLater,
        isLost,
        sideStates,
    };
}

/**
 * Check whether a stage transition requires confirmation modal.
 * True for won and lost.
 * @param {string} newStage
 * @returns {boolean}
 */
export function needsConfirm(newStage) {
    return newStage === "won" || newStage === "lost";
}

/**
 * Validate note text. Rejects empty notes and notes > 2000 chars after trimming.
 * Counts characters after trimming.
 * @param {string|null} text
 * @returns {{ ok: boolean, trimmed: string, error: string|null }}
 */
export function validateNote(text) {
    if (text === null || text === undefined) {
        return { ok: false, trimmed: "", error: "Note cannot be empty." };
    }
    const trimmed = String(text).trim();
    if (trimmed.length === 0) {
        return { ok: false, trimmed: "", error: "Note cannot be empty." };
    }
    if (trimmed.length > 2000) {
        return { ok: false, trimmed, error: "Ensure this field has no more than 2000 characters." };
    }
    return { ok: true, trimmed, error: null };
}

/**
 * Calculate counter text for note length after trimming.
 * e.g. "42 / 2000"
 * @param {string|null} text
 * @returns {string}
 */
export function noteCounterText(text) {
    const trimmedLen = (text || "").trim().length;
    return `${trimmedLen} / 2000`;
}

/**
 * Construct PATCH body for updating opportunity stage.
 * Omit note when empty. Always includes expected_stage.
 * @param {string} shownStage
 * @param {string} newStage
 * @param {string|null} [note]
 * @returns {{ stage: string, expected_stage: string, note?: string }}
 */
export function buildPatchBody(shownStage, newStage, note = null) {
    const body = {
        stage: newStage,
        expected_stage: shownStage,
    };
    if (note !== null && note !== undefined) {
        const trimmed = String(note).trim();
        if (trimmed.length > 0) {
            body.note = trimmed;
        }
    }
    return body;
}

/**
 * Resolve display name for author or user.
 * @param {Object|null} user
 * @returns {string}
 */
export function actorName(user) {
    if (!user) return "Deleted user";
    if (user.full_name && typeof user.full_name === "string" && user.full_name.trim().length > 0) {
        return user.full_name.trim();
    }
    if (user.username && typeof user.username === "string" && user.username.trim().length > 0) {
        return user.username.trim();
    }
    return "Deleted user";
}

/**
 * Generate human-readable label for a stage change history entry.
 * e.g. "Detected to Qualifying" or "Created as Detected".
 * @param {Object} change
 * @param {Function} [stageLabelFor]
 * @returns {string}
 */
export function historyLabel(change, stageLabelFor = null) {
    if (!change) return "";

    const getLabel = (code, label) => {
        if (label) return label;
        if (stageLabelFor) return stageLabelFor(code);
        const match = STAGES.find((s) => s.value === code);
        return match ? match.label : (code || "");
    };

    const toLabel = getLabel(change.to_stage, change.to_stage_label);

    if (!change.from_stage) {
        return `Created as ${toLabel}`;
    }

    const fromLabel = getLabel(change.from_stage, change.from_stage_label);
    return `${fromLabel} to ${toLabel}`;
}

/**
 * Determine if the stage update button should be enabled.
 * Disabled when:
 * 1. busy is true (request in flight)
 * 2. selectedStage equals shownStage (even if note is present; notes without stage change use "Add note")
 * 3. selectedStage is invalid or empty
 *
 * @param {string} shownStage - Currently active stage for the lead
 * @param {string} selectedStage - Currently selected stage in the dropdown
 * @param {string|null} [note] - Optional note text
 * @param {boolean} [busy=false] - Whether a network request is currently pending
 * @returns {boolean}
 */
export function canSubmitStage(shownStage, selectedStage, note = "", busy = false) {
    if (busy) {
        return false;
    }
    if (!selectedStage || typeof selectedStage !== "string") {
        return false;
    }
    return selectedStage !== shownStage;
}

