import test from "node:test";
import assert from "node:assert/strict";

import {
    readFilters,
    toQuery,
    apiQueryForZone,
    exportQuery,
    etaRelative,
    etaSourceLabel,
    summarise,
} from "../board-logic.js";

test("readFilters: parses valid query parameters", () => {
    const search = "?port=290&band=HOT&stage=contacted&q=tanker&sort=eta&inbound=1&closed=1";
    const filters = readFilters(search);

    assert.equal(filters.port, "290");
    assert.equal(filters.band, "HOT");
    assert.equal(filters.stage, "contacted");
    assert.equal(filters.q, "tanker");
    assert.equal(filters.sort, "eta");
    assert.equal(filters.inbound, true);
    assert.equal(filters.closed, true);
});

test("readFilters: ignores invalid values and applies defaults", () => {
    const search = "?port=invalid&band=UNKNOWN&stage=fake_stage&sort=invalid_sort&inbound=abc&closed=xyz";
    const filters = readFilters(search);

    assert.equal(filters.port, "");
    assert.equal(filters.band, "");
    assert.equal(filters.stage, "");
    assert.equal(filters.q, "");
    assert.equal(filters.sort, "-score");
    assert.equal(filters.inbound, false);
    assert.equal(filters.closed, false);
});

test("readFilters: handles empty or missing string", () => {
    const filters = readFilters("");
    assert.equal(filters.port, "");
    assert.equal(filters.band, "");
    assert.equal(filters.stage, "");
    assert.equal(filters.q, "");
    assert.equal(filters.sort, "-score");
    assert.equal(filters.inbound, false);
    assert.equal(filters.closed, false);
});

test("toQuery: serializes non-default filters to query string", () => {
    const filters = {
        port: "290",
        band: "HIGH",
        stage: "qualifying",
        q: "pacific",
        sort: "eta",
        inbound: true,
        closed: true,
    };
    const qs = toQuery(filters);
    assert.ok(qs.startsWith("?"));
    assert.ok(qs.includes("port=290"));
    assert.ok(qs.includes("band=HIGH"));
    assert.ok(qs.includes("stage=qualifying"));
    assert.ok(qs.includes("q=pacific"));
    assert.ok(qs.includes("sort=eta"));
    assert.ok(qs.includes("inbound=1"));
    assert.ok(qs.includes("closed=1"));
});

test("toQuery: omits default or empty values", () => {
    const filters = {
        port: "",
        band: "",
        stage: "",
        q: "",
        sort: "-score",
        inbound: false,
        closed: false,
    };
    assert.equal(toQuery(filters), "");
});

test("apiQueryForZone: includes zone, sets open=true unless closed is checked", () => {
    // 1. When closed is false: sends open=true
    const openQuery = apiQueryForZone({ inbound: true, sort: "-score" }, "24h");
    assert.ok(openQuery.includes("zone=24h"));
    assert.ok(openQuery.includes("open=true"));
    assert.ok(openQuery.includes("is_inbound=true"));
    assert.ok(openQuery.includes("ordering=-score"));

    // 2. When closed is true: omits open=true
    const closedQuery = apiQueryForZone({ closed: true }, "72h");
    assert.ok(closedQuery.includes("zone=72h"));
    assert.ok(!closedQuery.includes("open=true"));
});

test("exportQuery: produces query without zone or page", () => {
    const filters = {
        port: "790",
        band: "HOT",
        stage: "detected",
        q: "alpha",
        sort: "eta",
        inbound: true,
        closed: false,
    };
    const eq = exportQuery(filters);

    assert.ok(!eq.includes("zone="));
    assert.ok(!eq.includes("page="));
    assert.ok(!eq.includes("page_size="));
    assert.ok(eq.includes("open=true"));
    assert.ok(eq.includes("is_inbound=true"));
    assert.ok(eq.includes("port=790"));
    assert.ok(eq.includes("band=HOT"));
    assert.ok(eq.includes("ordering=eta"));
});

test("etaRelative: returns expected relative text", () => {
    const now = 1700000000000;

    // Past ETA
    const past = new Date(now - 3600 * 1000).toISOString();
    assert.equal(etaRelative(past, now), "ETA passed");

    // Exact now
    assert.equal(etaRelative(new Date(now).toISOString(), now), "ETA passed");

    // Future hours (< 24h)
    const in5h = new Date(now + 5 * 3600 * 1000).toISOString();
    assert.equal(etaRelative(in5h, now), "in 5 h");

    // Future days (>= 24h)
    const in2d = new Date(now + 48 * 3600 * 1000).toISOString();
    assert.equal(etaRelative(in2d, now), "in 2 d");

    // Null or invalid
    assert.equal(etaRelative(null, now), "No ETA");
    assert.equal(etaRelative("", now), "No ETA");
    assert.equal(etaRelative("invalid-date", now), "No ETA");
});

test("etaSourceLabel: converts source codes to words", () => {
    assert.equal(etaSourceLabel("eta_calc"), "provider calculated");
    assert.equal(etaSourceLabel("ais_eta"), "AIS declared");
    assert.equal(etaSourceLabel(""), "");
    assert.equal(etaSourceLabel(null), "");
    assert.equal(etaSourceLabel("other"), "");
});

test("summarise: computes total, hot, and inbound counts", () => {
    const items = [
        { band: "HOT", is_inbound: true },
        { band: "HIGH", is_inbound: true },
        { band: "HOT", is_inbound: false },
        { band: "LOW", is_inbound: false },
    ];

    const result = summarise(items);
    assert.equal(result.total, 4);
    assert.equal(result.hot, 2);
    assert.equal(result.inbound, 2);

    assert.deepEqual(summarise([]), { total: 0, hot: 0, inbound: 0 });
    assert.deepEqual(summarise(null), { total: 0, hot: 0, inbound: 0 });
});
