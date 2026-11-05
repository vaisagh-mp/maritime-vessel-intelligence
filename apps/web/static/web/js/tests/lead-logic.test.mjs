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
    buildPatchBody,
    actorName,
    historyLabel,
} from "../lead-logic.js";
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
