import { test } from "node:test";
import assert from "node:assert/strict";

import { buildQuery, companyMeta, dateChips, fetchText, pageText, splitCompanies, utcText } from "../latest-logic.js";

test("buildQuery only includes what is set", () => {
    assert.equal(buildQuery(), "");
    assert.equal(buildQuery({ port: "SGSIN", band: "HOT", page: 3 }), "?port=SGSIN&band=HOT&page=3");
    assert.equal(buildQuery({ port: "5", page: 1 }), "?port=5");
    assert.equal(buildQuery({ date: "2026-11-24", port: "AEFJR" }), "?date=2026-11-24&port=AEFJR");
});

test("utcText and fetchText", () => {
    assert.equal(utcText("2026-11-24T02:05:00Z"), "24 Nov, 02:05 UTC");
    assert.equal(utcText("bad"), "");
    assert.equal(
        fetchText({ name: "Fujairah", port: "AEFJR", fetched_at: "2026-11-25T08:14:00Z", vessels: 22, with_owner: 5, with_manager: 7 }),
        "Port of Fujairah: fetched 25 Nov, 08:14 UTC \u00b7 22 vessels \u00b7 5 with owner data \u00b7 7 with manager data");
    assert.match(fetchText({ name: "X", fetched_at: "2026-11-25T08:14:00Z", vessels: 1, approximate: true }), /1 vessel \u00b7.*may be incomplete/);
    assert.equal(fetchText({ name: "Singapore", port: "SGSIN", fetched_at: null }), "Port of Singapore: no live fetch on this date");
});

test("splitCompanies and companyMeta", () => {
    const { owners, managers } = splitCompanies([{ group: "owner", name: "A" }, { group: "manager", name: "B" }, { group: "manager", name: "C" }]);
    assert.equal(owners.length, 1);
    assert.equal(managers.length, 2);
    assert.deepEqual(splitCompanies(null), { owners: [], managers: [] });
    assert.equal(companyMeta({ country: "Greece" }), "Greece");
    assert.equal(companyMeta({}), "");
});

test("pageText", () => {
    assert.equal(pageText(1, 1), "");
    assert.equal(pageText(2, 5), "Page 2 of 5");
});

test("dateChips shortens recent dates", () => {
    assert.deepEqual(dateChips(["2026-11-25", "2026-11-24", "2026-11-20"], 2), [
        { value: "2026-11-25", label: "25 Nov" }, { value: "2026-11-24", label: "24 Nov" }]);
    assert.deepEqual(dateChips(null), []);
});
