import test from "node:test";
import assert from "node:assert/strict";

import {
    defaultFilters,
    activeFilterCount,
    readFilters,
    toQuery,
    apiQuery,
    roleLabel,
    roleChips,
    pageNumbers,
} from "../companies-logic.js";

test("defaultFilters: returns clean defaults", () => {
    const f = defaultFilters();
    assert.deepEqual(f, {
        q: "",
        country: "",
        type: "",
        role: "",
        has_open_leads: false,
        ordering: "name",
    });
});

test("activeFilterCount: all defaults gives 0", () => {
    assert.equal(activeFilterCount(defaultFilters()), 0);
    assert.equal(activeFilterCount(null), 0);
    assert.equal(activeFilterCount(undefined), 0);
});

test("activeFilterCount: single active filters", () => {
    assert.equal(activeFilterCount({ ...defaultFilters(), q: "acme" }), 1);
    assert.equal(activeFilterCount({ ...defaultFilters(), country: "Singapore" }), 1);
    assert.equal(activeFilterCount({ ...defaultFilters(), type: "manager" }), 1);
    assert.equal(activeFilterCount({ ...defaultFilters(), role: "owner" }), 1);
    assert.equal(activeFilterCount({ ...defaultFilters(), has_open_leads: true }), 1);
    assert.equal(activeFilterCount({ ...defaultFilters(), ordering: "-vessels" }), 1);
});

test("activeFilterCount: ordering=name is not counted", () => {
    assert.equal(activeFilterCount({ ...defaultFilters(), ordering: "name" }), 0);
});

test("activeFilterCount: multiple active", () => {
    const f = { ...defaultFilters(), q: "test", type: "owner", has_open_leads: true };
    assert.equal(activeFilterCount(f), 3);
});

test("readFilters: parses valid params", () => {
    const f = readFilters("?q=acme&country=SG&type=manager&role=owner&has_open_leads=1&ordering=-vessels");
    assert.equal(f.q, "acme");
    assert.equal(f.country, "SG");
    assert.equal(f.type, "manager");
    assert.equal(f.role, "owner");
    assert.equal(f.has_open_leads, true);
    assert.equal(f.ordering, "-vessels");
});

test("readFilters: ignores invalid ordering", () => {
    const f = readFilters("?ordering=invalid");
    assert.equal(f.ordering, "name");
});

test("readFilters: empty string gives defaults", () => {
    const f = readFilters("");
    assert.deepEqual(f, defaultFilters());
});

test("toQuery: serializes non-default filters", () => {
    const f = { ...defaultFilters(), q: "fleet", type: "owner", has_open_leads: true, ordering: "hottest" };
    const qs = toQuery(f);
    assert.ok(qs.includes("q=fleet"));
    assert.ok(qs.includes("type=owner"));
    assert.ok(qs.includes("has_open_leads=1"));
    assert.ok(qs.includes("ordering=hottest"));
});

test("toQuery: defaults produce empty string", () => {
    assert.equal(toQuery(defaultFilters()), "");
    assert.equal(toQuery(null), "");
});

test("apiQuery: includes page and page_size", () => {
    const qs = apiQuery(defaultFilters(), 2, 24);
    assert.ok(qs.includes("page=2"));
    assert.ok(qs.includes("page_size=24"));
    assert.ok(qs.includes("ordering=name"));
});

test("apiQuery: includes filter params", () => {
    const f = { ...defaultFilters(), q: "test", role: "manager", has_open_leads: true };
    const qs = apiQuery(f, 1, 24);
    assert.ok(qs.includes("q=test"));
    assert.ok(qs.includes("role=manager"));
    assert.ok(qs.includes("has_open_leads=true"));
});

test("roleLabel: formats role strings", () => {
    assert.equal(roleLabel("technical_manager"), "Technical Manager");
    assert.equal(roleLabel("owner"), "Owner");
    assert.equal(roleLabel(""), "");
    assert.equal(roleLabel(null), "");
});

test("roleChips: returns sorted chips", () => {
    const chips = roleChips({ manager: 5, owner: 3 });
    assert.equal(chips.length, 2);
    assert.equal(chips[0].role, "manager");
    assert.equal(chips[0].count, 5);
    assert.equal(chips[0].label, "Manager");
    assert.equal(chips[1].role, "owner");
    assert.equal(chips[1].count, 3);
});

test("roleChips: handles null/empty", () => {
    assert.deepEqual(roleChips(null), []);
    assert.deepEqual(roleChips({}), []);
});

test("pageNumbers: all pages when few, ellipsis when many", () => {
    assert.deepEqual(pageNumbers(1, 1), [1]);
    assert.deepEqual(pageNumbers(2, 3), [1, 2, 3]);
    assert.deepEqual(pageNumbers(1, 12), [1, 2, "…", 12]);
    assert.deepEqual(pageNumbers(6, 12), [1, "…", 5, 6, 7, "…", 12]);
    assert.deepEqual(pageNumbers(12, 12), [1, "…", 11, 12]);
    assert.deepEqual(pageNumbers(4, 6), [1, 2, 3, 4, 5, 6]);
    assert.deepEqual(pageNumbers(99, 3), [1, 2, 3]);
    assert.deepEqual(pageNumbers("x", "y"), [1]);
});
