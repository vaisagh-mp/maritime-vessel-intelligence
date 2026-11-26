/**
 * apps/web/static/web/js/tests/lead-logic.test.mjs
 * Unit tests for lead-logic pure functions using node:test.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
    stageOptions,
    progressSteps,
    needsConfirm,
    validateNote,
    noteCounterText,
    noteFormState,
    buildPatchBody,
    actorName,
    historyLabel,
    canSubmitStage,
} from "../lead-logic.js";
import { formatErrorMessage } from "../ui.js";
import { PIPELINE_ORDER, STAGES } from "../stages.js";

test("stageOptions: returns all stages with correct isCurrent flag", () => {
    const options = stageOptions("qualifying");
    assert.equal(options.length, STAGES.length);
    const qualifying = options.find((o) => o.value === "qualifying");
    assert.equal(qualifying.isCurrent, true);

    const detected = options.find((o) => o.value === "detected");
    assert.equal(detected.isCurrent, false);
});

test("progressSteps: covers main pipeline stages", () => {
    // Current is 'contacted' (index 3 in PIPELINE_ORDER)
    const { steps, isFollowUpLater, isLost } = progressSteps("contacted");
    assert.equal(steps.length, PIPELINE_ORDER.length);

    // 0: detected (done)
    assert.equal(steps[0].value, "detected");
    assert.equal(steps[0].state, "done");

    // 1: qualifying (done)
    assert.equal(steps[1].value, "qualifying");
    assert.equal(steps[1].state, "done");

    // 2: ready_for_review (done)
    assert.equal(steps[2].value, "ready_for_review");
    assert.equal(steps[2].state, "done");

    // 3: contacted (current)
    assert.equal(steps[3].value, "contacted");
    assert.equal(steps[3].state, "current");

    // 4: replied (todo)
    assert.equal(steps[4].value, "replied");
    assert.equal(steps[4].state, "todo");

    // Won (last step, todo)
    assert.equal(steps[steps.length - 1].value, "won");
    assert.equal(steps[steps.length - 1].state, "todo");

    assert.equal(isFollowUpLater, false);
    assert.equal(isLost, false);
});

test("progressSteps: covers side states (follow_up_later and lost)", () => {
    // Side state 1: follow_up_later
    const followUpRes = progressSteps("follow_up_later");
    assert.equal(followUpRes.isFollowUpLater, true);
    assert.equal(followUpRes.isLost, false);
    // All main path steps remain todo when in side state
    assert.ok(followUpRes.steps.every((s) => s.state === "todo"));
    const fulSide = followUpRes.sideStates.find((s) => s.value === "follow_up_later");
    assert.equal(fulSide.isCurrent, true);

    // Side state 2: lost
    const lostRes = progressSteps("lost");
    assert.equal(lostRes.isFollowUpLater, false);
    assert.equal(lostRes.isLost, true);
    assert.ok(lostRes.steps.every((s) => s.state === "todo"));
    const lostSide = lostRes.sideStates.find((s) => s.value === "lost");
    assert.equal(lostSide.isCurrent, true);
});

test("progressSteps: covers every stage in STAGES", () => {
    for (const stage of STAGES) {
        const res = progressSteps(stage.value);
        if (PIPELINE_ORDER.includes(stage.value)) {
            const currentStep = res.steps.find((s) => s.value === stage.value);
            assert.equal(currentStep.state, "current");
        } else if (stage.value === "follow_up_later") {
            assert.equal(res.isFollowUpLater, true);
        } else if (stage.value === "lost") {
            assert.equal(res.isLost, true);
        }
    }
});

test("needsConfirm: true only for won and lost", () => {
    assert.equal(needsConfirm("won"), true);
    assert.equal(needsConfirm("lost"), true);
    assert.equal(needsConfirm("contacted"), false);
    assert.equal(needsConfirm("qualifying"), false);
    assert.equal(needsConfirm("follow_up_later"), false);
    assert.equal(needsConfirm(""), false);
    assert.equal(needsConfirm(null), false);
});

test("validateNote: validates empty, spaces, lengths, and scripts", () => {
    // Empty and null
    assert.deepEqual(validateNote(""), { ok: false, trimmed: "", error: "Note cannot be empty." });
    assert.deepEqual(validateNote(null), { ok: false, trimmed: "", error: "Note cannot be empty." });
    assert.deepEqual(validateNote("   \n\t  "), { ok: false, trimmed: "", error: "Note cannot be empty." });

    // 1 character after trimming
    assert.deepEqual(validateNote(" a "), { ok: true, trimmed: "a", error: null });

    // Exactly 2000 characters
    const text2000 = "x".repeat(2000);
    const res2000 = validateNote(`  ${text2000}  `);
    assert.equal(res2000.ok, true);
    assert.equal(res2000.trimmed.length, 2000);
    assert.equal(res2000.error, null);

    // 2001 characters
    const text2001 = "x".repeat(2001);
    const res2001 = validateNote(text2001);
    assert.equal(res2001.ok, false);
    assert.equal(res2001.error, "Ensure this field has no more than 2000 characters.");

    // Note with <script> tag (valid text, rendered safely via textContent in DOM)
    const scriptNote = "<script>alert('xss')</script>";
    const resScript = validateNote(scriptNote);
    assert.equal(resScript.ok, true);
    assert.equal(resScript.trimmed, scriptNote);
});

test("noteCounterText: computes trimmed length counter", () => {
    assert.equal(noteCounterText(""), "0 / 2000");
    assert.equal(noteCounterText(null), "0 / 2000");
    assert.equal(noteCounterText("  hello world  "), "11 / 2000");
    assert.equal(noteCounterText("a".repeat(150)), "150 / 2000");
});

test("buildPatchBody: constructs payload with and without note", () => {
    // With note
    assert.deepEqual(
        buildPatchBody("detected", "qualifying", "Client meeting scheduled"),
        {
            stage: "qualifying",
            expected_stage: "detected",
            note: "Client meeting scheduled",
        }
    );

    // Without note / empty note
    assert.deepEqual(
        buildPatchBody("detected", "qualifying", ""),
        {
            stage: "qualifying",
            expected_stage: "detected",
        }
    );
    assert.deepEqual(
        buildPatchBody("detected", "qualifying", "   "),
        {
            stage: "qualifying",
            expected_stage: "detected",
        }
    );
    assert.deepEqual(
        buildPatchBody("qualifying", "won", null),
        {
            stage: "won",
            expected_stage: "qualifying",
        }
    );
});

test("actorName: returns full name, username, or deleted user", () => {
    assert.equal(actorName({ full_name: "John Doe", username: "jdoe" }), "John Doe");
    assert.equal(actorName({ full_name: "  Jane Smith  ", username: "jsmith" }), "Jane Smith");
    assert.equal(actorName({ full_name: "", username: "jsmith" }), "jsmith");
    assert.equal(actorName({ full_name: null, username: "admin" }), "admin");
    assert.equal(actorName({ full_name: "", username: "" }), "Deleted user");
    assert.equal(actorName(null), "Deleted user");
    assert.equal(actorName(undefined), "Deleted user");
});

test("historyLabel: handles standard transitions and creation entries", () => {
    // Normal transition
    assert.equal(
        historyLabel({
            from_stage: "detected",
            from_stage_label: "Detected",
            to_stage: "qualifying",
            to_stage_label: "Qualifying",
        }),
        "Detected to Qualifying"
    );

    // Initial creation (empty from_stage)
    assert.equal(
        historyLabel({
            from_stage: "",
            from_stage_label: "",
            to_stage: "detected",
            to_stage_label: "Detected",
        }),
        "Created as Detected"
    );
    assert.equal(
        historyLabel({
            from_stage: null,
            to_stage: "qualifying",
            to_stage_label: "Qualifying",
        }),
        "Created as Qualifying"
    );

    // Fallback using stage codes when labels missing
    assert.equal(
        historyLabel({
            from_stage: "contacted",
            to_stage: "replied",
        }),
        "Contacted to Replied"
    );
});

test("canSubmitStage: validates stage change and busy state", () => {
    // Unchanged stage without note is disabled
    assert.equal(canSubmitStage("detected", "detected", "", false), false);

    // Unchanged stage even with note is disabled (must use Add note form instead)
    assert.equal(canSubmitStage("detected", "detected", "My transition note", false), false);

    // Changed stage without note is enabled
    assert.equal(canSubmitStage("detected", "qualifying", "", false), true);

    // Changed stage with note is enabled
    assert.equal(canSubmitStage("detected", "qualifying", "My note", false), true);

    // Changed stage while busy is disabled
    assert.equal(canSubmitStage("detected", "qualifying", "My note", true), false);
    assert.equal(canSubmitStage("detected", "qualifying", "", true), false);

    // Invalid or missing selected stage is disabled
    assert.equal(canSubmitStage("detected", "", "", false), false);
    assert.equal(canSubmitStage("detected", null, "", false), false);
    assert.equal(canSubmitStage("detected", undefined, "", false), false);
});

test("formatErrorMessage: ensures clean icon-free Error: prefix without duplication", () => {
    assert.equal(
        formatErrorMessage("Failed to load records."),
        "Error: Failed to load records."
    );
    assert.equal(
        formatErrorMessage("Error: Server responded with 500"),
        "Error: Server responded with 500"
    );
    assert.equal(
        formatErrorMessage("error: already prefixed lowercase"),
        "error: already prefixed lowercase"
    );
    assert.equal(
        formatErrorMessage(""),
        "Error: An unexpected error occurred."
    );
    assert.equal(
        formatErrorMessage(null),
        "Error: An unexpected error occurred."
    );
    assert.equal(
        formatErrorMessage(undefined),
        "Error: An unexpected error occurred."
    );
});


test("robustness: validateNote handles element-like object, number, null, undefined, normal string without throwing", () => {
    const elementLike = { value: "some text", tagName: "TEXTAREA" };
    assert.deepEqual(validateNote(elementLike), { ok: false, trimmed: "", error: "Note cannot be empty." });
    assert.deepEqual(validateNote(42), { ok: false, trimmed: "", error: "Note cannot be empty." });
    assert.deepEqual(validateNote(null), { ok: false, trimmed: "", error: "Note cannot be empty." });
    assert.deepEqual(validateNote(undefined), { ok: false, trimmed: "", error: "Note cannot be empty." });
    assert.deepEqual(validateNote("  Valid note content  "), { ok: true, trimmed: "Valid note content", error: null });
});

test("robustness: noteCounterText handles element-like object, number, null, undefined, normal string without throwing", () => {
    const elementLike = { value: "some text", tagName: "TEXTAREA" };
    assert.equal(noteCounterText(elementLike), "0 / 2000");
    assert.equal(noteCounterText(42), "0 / 2000");
    assert.equal(noteCounterText(null), "0 / 2000");
    assert.equal(noteCounterText(undefined), "0 / 2000");
    assert.equal(noteCounterText("Valid note"), "10 / 2000");
    assert.equal(noteCounterText("  Trimmed  "), "7 / 2000");
});

test("robustness: canSubmitStage handles element-like object, number, null, undefined, normal string without throwing", () => {
    const elementLike = { value: "some text", tagName: "TEXTAREA" };

    // Passed as note argument
    assert.equal(canSubmitStage("detected", "qualifying", elementLike, false), true);
    assert.equal(canSubmitStage("detected", "qualifying", 42, false), true);
    assert.equal(canSubmitStage("detected", "qualifying", null, false), true);
    assert.equal(canSubmitStage("detected", "qualifying", undefined, false), true);
    assert.equal(canSubmitStage("detected", "qualifying", "Normal note string", false), true);

    // Passed as stage arguments
    assert.equal(canSubmitStage(elementLike, "qualifying", "", false), true);
    assert.equal(canSubmitStage("detected", elementLike, "", false), false);
    assert.equal(canSubmitStage(42, "qualifying", "", false), true);
    assert.equal(canSubmitStage("detected", 42, "", false), false);
    assert.equal(canSubmitStage(null, "qualifying", "", false), true);
    assert.equal(canSubmitStage("detected", null, "", false), false);
    assert.equal(canSubmitStage(undefined, "qualifying", "", false), true);
    assert.equal(canSubmitStage("detected", undefined, "", false), false);
});

test("robustness: buildPatchBody handles element-like object, number, null, undefined, normal string without throwing", () => {
    const elementLike = { value: "some text", tagName: "TEXTAREA" };

    // Non-string notes are safely ignored / omitted
    assert.deepEqual(buildPatchBody("detected", "qualifying", elementLike), {
        stage: "qualifying",
        expected_stage: "detected",
    });
    assert.deepEqual(buildPatchBody("detected", "qualifying", 42), {
        stage: "qualifying",
        expected_stage: "detected",
    });
    assert.deepEqual(buildPatchBody("detected", "qualifying", null), {
        stage: "qualifying",
        expected_stage: "detected",
    });
    assert.deepEqual(buildPatchBody("detected", "qualifying", undefined), {
        stage: "qualifying",
        expected_stage: "detected",
    });
    assert.deepEqual(buildPatchBody("detected", "qualifying", "  Transition note  "), {
        stage: "qualifying",
        expected_stage: "detected",
        note: "Transition note",
    });

    // Non-string stages
    assert.deepEqual(buildPatchBody(elementLike, "qualifying"), {
        stage: "qualifying",
        expected_stage: "",
    });
    assert.deepEqual(buildPatchBody("detected", elementLike), {
        stage: "",
        expected_stage: "detected",
    });
});

test("page flow: type note text, check counter, submit, new note appears at top, textarea and counter reset", () => {
    // 1. Initial page state with existing notes
    const notesList = [
        { id: 1, text: "Existing first note", author: { full_name: "Alice" } },
    ];

    // Simulated DOM element references
    const textarea = { value: "", tagName: "TEXTAREA" };
    const counter = { textContent: noteCounterText(textarea.value) };
    const saveBtn = { disabled: true };

    assert.equal(counter.textContent, "0 / 2000");
    assert.equal(saveBtn.disabled, true);

    // 2. User types note text ("Discussed berthing window with agent")
    textarea.value = "Discussed berthing window with agent";

    // Input event handler logic (as in lead.js initNoteForm)
    counter.textContent = noteCounterText(textarea.value);
    const validationOnInput = validateNote(textarea.value);
    saveBtn.disabled = !validationOnInput.ok;

    assert.equal(counter.textContent, "36 / 2000");
    assert.equal(validationOnInput.ok, true);
    assert.equal(saveBtn.disabled, false);

    // 3. User submits note form
    const validationOnSubmit = validateNote(textarea.value);
    assert.equal(validationOnSubmit.ok, true);

    // Mock API response for created note
    const createdNote = {
        id: 2,
        text: validationOnSubmit.trimmed,
        author: { full_name: "Bob Agent" },
        created_at: "2026-11-05T14:00:00Z",
    };

    // Post-submit reset (as in lead.js initNoteForm)
    textarea.value = "";
    counter.textContent = noteCounterText(textarea.value);
    saveBtn.disabled = true;

    // Prepend new note immediately to the top of the notes list
    notesList.unshift(createdNote);

    // Assert new note appears at the top (index 0)
    assert.equal(notesList.length, 2);
    assert.equal(notesList[0].id, 2);
    assert.equal(notesList[0].text, "Discussed berthing window with agent");
    assert.equal(notesList[1].id, 1);

    // Assert textarea and counter are cleanly reset
    assert.equal(textarea.value, "");
    assert.equal(counter.textContent, "0 / 2000");
    assert.equal(saveBtn.disabled, true);

    // 4. Same note box in the stage form flow
    const stageSelect = { value: "contacted" };
    const stageTextarea = { value: "", tagName: "TEXTAREA" };
    const stageCounter = { textContent: noteCounterText(stageTextarea.value) };
    const stageUpdateBtn = { disabled: true };
    const currentOpportunity = { stage: "qualifying" };

    // Stage form input event
    stageTextarea.value = "Sent introductory email with tariff schedule";
    stageCounter.textContent = noteCounterText(stageTextarea.value);
    const canSubmit = canSubmitStage(
        currentOpportunity.stage,
        stageSelect.value,
        stageTextarea.value,
        false
    );
    stageUpdateBtn.disabled = !canSubmit;

    assert.equal(stageCounter.textContent, "44 / 2000");
    assert.equal(stageUpdateBtn.disabled, false);

    // Stage form submit / patch body creation
    const patchBody = buildPatchBody(
        currentOpportunity.stage,
        stageSelect.value,
        stageTextarea.value
    );
    assert.deepEqual(patchBody, {
        stage: "contacted",
        expected_stage: "qualifying",
        note: "Sent introductory email with tariff schedule",
    });

    // Reset stage note input after patch
    stageTextarea.value = "";
    stageCounter.textContent = noteCounterText(stageTextarea.value);
    assert.equal(stageTextarea.value, "");
    assert.equal(stageCounter.textContent, "0 / 2000");
});

test("noteFormState: handles empty, spaces only, 1 char, exactly 2000, 2001, and busy true", () => {
    // 1. empty (empty string, null, undefined)
    assert.deepEqual(noteFormState("", false), {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });
    assert.deepEqual(noteFormState(null, false), {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });
    assert.deepEqual(noteFormState(undefined, false), {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });

    // 2. spaces only
    assert.deepEqual(noteFormState("   \t\n  ", false), {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });

    // 3. 1 char
    assert.deepEqual(noteFormState("a", false), {
        trimmed: "a",
        counterText: "1 / 2000",
        canSubmit: true,
        error: null,
    });
    assert.deepEqual(noteFormState("   a   ", false), {
        trimmed: "a",
        counterText: "1 / 2000",
        canSubmit: true,
        error: null,
    });

    // 4. exactly 2000 chars
    const text2000 = "x".repeat(2000);
    assert.deepEqual(noteFormState(text2000, false), {
        trimmed: text2000,
        counterText: "2000 / 2000",
        canSubmit: true,
        error: null,
    });

    // 5. 2001 chars
    const text2001 = "x".repeat(2001);
    const res2001 = noteFormState(text2001, false);
    assert.equal(res2001.counterText, "2001 / 2000");
    assert.equal(res2001.canSubmit, false);
    assert.equal(res2001.error, "Ensure this field has no more than 2000 characters.");

    // 6. busy true
    assert.deepEqual(noteFormState("Follow up with charterer", true), {
        trimmed: "Follow up with charterer",
        counterText: "24 / 2000",
        canSubmit: false,
        error: null,
    });
});
