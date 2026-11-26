import { test } from "node:test";
import assert from "node:assert/strict";
import { formatCountdown, liveRefreshState, summaryMessage, LIVE_LABEL } from "../refresh-logic.js";

test("formatCountdown formats m:ss and clamps", () => {
    assert.equal(formatCountdown(72), "1:12");
    assert.equal(formatCountdown(120), "2:00");
    assert.equal(formatCountdown(5), "0:05");
    assert.equal(formatCountdown(0), "0:00");
    assert.equal(formatCountdown(-4), "0:00");
    assert.equal(formatCountdown(59.2), "1:00");
    assert.equal(formatCountdown(undefined), "0:00");
});

test("liveRefreshState: no port chosen", () => {
    const s = liveRefreshState({ locode: "", status: { enabled: true, cooldown_remaining: 0 } });
    assert.equal(s.disabled, true);
    assert.equal(s.label, LIVE_LABEL);
    assert.equal(s.message, "Choose a port first.");
});

test("liveRefreshState: idle and ready", () => {
    const s = liveRefreshState({ locode: "SGSIN", status: { enabled: true, cooldown_remaining: 0 } });
    assert.deepEqual(s, { disabled: false, label: LIVE_LABEL, message: "" });
});

test("liveRefreshState: works before status has loaded", () => {
    const s = liveRefreshState({ locode: "SGSIN", status: null });
    assert.equal(s.disabled, false);
});

test("liveRefreshState: cooldown shows countdown even without a port", () => {
    const s = liveRefreshState({ locode: "SGSIN", status: { enabled: true, cooldown_remaining: 72 } });
    assert.equal(s.disabled, true);
    assert.equal(s.label, "Available in 1:12");
    const t = liveRefreshState({ locode: "", status: { enabled: true, cooldown_remaining: 30 } });
    assert.equal(t.label, "Available in 0:30");
});

test("liveRefreshState: local remaining overrides server value", () => {
    const s = liveRefreshState({ locode: "SGSIN", status: { cooldown_remaining: 100 }, remaining: 0 });
    assert.equal(s.disabled, false);
    const t = liveRefreshState({ locode: "SGSIN", status: { cooldown_remaining: 0 }, remaining: 45 });
    assert.equal(t.label, "Available in 0:45");
});

test("liveRefreshState: busy and running", () => {
    assert.equal(liveRefreshState({ locode: "SGSIN", busy: true }).label, "Fetching…");
    const r = liveRefreshState({ locode: "SGSIN", status: { running: { run_id: 3 }, cooldown_remaining: 0 } });
    assert.equal(r.disabled, true);
    assert.equal(r.label, "Fetching…");
});

test("liveRefreshState: disabled by server wins", () => {
    const s = liveRefreshState({ locode: "SGSIN", status: { enabled: false }, busy: true });
    assert.equal(s.disabled, true);
    assert.equal(s.message, "Live refresh is disabled.");
});

test("summaryMessage: success with numbers", () => {
    const msg = summaryMessage({
        status: "success", port: "SGSIN",
        summary: { accepted: 1279, opportunities_created: 12, opportunities_updated: 92, errors: 0 },
    });
    assert.equal(msg, "Singapore: 1279 vessels read, 12 new leads, 92 updated.");
});

test("summaryMessage: row errors are mentioned", () => {
    const one = summaryMessage({ status: "success", port: "AEFJR", summary: { accepted: 5, opportunities_created: 1, opportunities_updated: 0, errors: 1 } });
    assert.match(one, /^Fujairah: 5 vessels read, 1 new leads, 0 updated\. 1 row could not be saved\.$/);
    const many = summaryMessage({ status: "success", port: "AEFJR", summary: { accepted: 5, errors: 3 } });
    assert.match(many, /3 rows could not be saved/);
});

test("summaryMessage: missing numbers and unknown port", () => {
    assert.equal(summaryMessage({ status: "success", port: "SGSIN", summary: {} }), "Singapore: refresh finished.");
    assert.equal(summaryMessage({ status: "success", port: "XXXXX" }), "XXXXX: refresh finished.");
});

test("summaryMessage: failure and null", () => {
    assert.equal(summaryMessage({ status: "failed", error: "Too many calls" }), "Refresh failed: Too many calls");
    assert.equal(summaryMessage({ status: "failed", error: "" }), "Refresh failed: unknown error");
    assert.equal(summaryMessage(null), "");
});

import { aisMessage, ownershipMessage } from "../refresh-logic.js";

test("aisMessage: shown only when AIS ran", () => {
    assert.equal(aisMessage({}), "");
    assert.equal(aisMessage({ ais_skipped: "no_area_filter" }), "");
    assert.equal(aisMessage({ ais_in_anchorage: 150, ais_opportunities_created: 12 }), " AIS: 150 in anchorage, 12 new anchorage leads.");
    assert.equal(aisMessage({ ais_in_anchorage: 0 }), " AIS: 0 in anchorage, 0 new anchorage leads.");
    assert.equal(aisMessage({ ais_error: "Rate limit" }), " AIS failed: Rate limit");
});

test("summaryMessage appends the AIS sentence", () => {
    const msg = summaryMessage({
        status: "success", port: "SGSIN",
        summary: { accepted: 10, opportunities_created: 1, opportunities_updated: 2, ais_in_anchorage: 5, ais_opportunities_created: 3 },
    });
    assert.equal(msg, "Singapore: 10 vessels read, 1 new leads, 2 updated. AIS: 5 in anchorage, 3 new anchorage leads.");
});


test("ownershipMessage: each outcome has its own sentence", () => {
    assert.equal(ownershipMessage(null), "");
    assert.equal(ownershipMessage({}), "");
    assert.match(ownershipMessage({ own_error: "Not entitled" }), /^ Owner lookup failed: Not entitled/);
    assert.equal(ownershipMessage({ own_skipped: "disabled" }), " Owner lookup is switched off.");
    assert.match(ownershipMessage({ own_skipped: "quota" }), /monthly limit/);
    assert.match(ownershipMessage({ own_skipped: "no_candidates" }), /already checked/);
    assert.equal(
        ownershipMessage({ own_requested: 1, own_relationships_created: 1 }),
        " Owners: 1 vessel looked up, 1 owner or manager link added."
    );
    assert.equal(
        ownershipMessage({ own_requested: 12, own_relationships_created: 0 }),
        " Owners: 12 vessels looked up, 0 owner or manager links added."
    );
});

test("summaryMessage: ownership sentence is appended after the AIS one", () => {
    const run = {
        status: "success", port: "SGSIN",
        summary: { accepted: 3, opportunities_created: 1, opportunities_updated: 2, ais_in_anchorage: 4,
                   ais_opportunities_created: 2, own_requested: 5, own_relationships_created: 9 },
    };
    const text = summaryMessage(run);
    assert.ok(text.indexOf("AIS:") < text.indexOf("Owners:"));
    assert.match(text, /5 vessels looked up, 9 owner or manager links added/);
});

import { summaryMessage as sm2 } from "../refresh-logic.js";

test("summaryMessage explains a skipped arrivals call and a used-up owner share", () => {
    const text = sm2({ status: "success", port: "SGSIN", summary: {
        arrivals_skipped: true, arrivals_next_at: "2026-11-25T02:00:00Z", own_skipped: "budget" } });
    assert.match(text, /already fetched today/);
    assert.match(text, /25 Nov, 02:00 UTC/);
    assert.match(text, /today's share is used up/);
});
