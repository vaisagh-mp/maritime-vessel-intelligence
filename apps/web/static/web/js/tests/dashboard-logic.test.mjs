import { test } from "node:test";
import assert from "node:assert/strict";

import {
    dashboardTableQuery,
    fieldErrors,
    filterBds,
    formatDate,
    generatePassword,
    pageInfo,
    readPage,
    refreshStatusText,
    stageBars,
    statCards,
    timeAgo,
    waitingText,
    withPaging,
    withPort,
} from "../dashboard-logic.js";

test("statCards: eight cards in order, with zero for missing values", () => {
    const cards = statCards({ open: 12, hot: 3, inbound: "4" });
    assert.equal(cards.length, 8);
    assert.deepEqual(cards.slice(0, 3).map((c) => [c.key, c.value]), [["open", 12], ["hot", 3], ["inbound", 4]]);
    assert.equal(cards[7].value, 0);
    assert.equal(statCards(null).every((c) => c.value === 0), true);
});

test("statCards: links go to the right lists", () => {
    const byKey = Object.fromEntries(statCards({}).map((c) => [c.key, c.href]));
    assert.equal(byKey.zone_72h, "/priority/72h/");
    assert.equal(byKey.anchorage, "/priority/anchorage/");
    assert.equal(byKey.hot, "/priority/all/?band=HOT");
});

test("statCards: every card opens its own list, not the 24 hour page", () => {
    const byKey = Object.fromEntries(statCards({}).map((c) => [c.key, c.href]));
    assert.equal(byKey.open, "/priority/all/");
    assert.equal(byKey.inbound, "/priority/all/?inbound=1");
    assert.equal(byKey.in_pipeline, "/priority/all/?stage=pipeline");
    assert.equal(byKey.new_24h, "/priority/all/?new=1");
    assert.equal(byKey.zone_24h, "/priority/24h/");
});

test("withPort: adds a port only when it is a number", () => {
    assert.equal(withPort("/priority/24h/", "2"), "/priority/24h/?port=2");
    assert.equal(withPort("/priority/24h/?band=HOT", "2"), "/priority/24h/?band=HOT&port=2");
    assert.equal(withPort("/x/", ""), "/x/");
    assert.equal(withPort("/x/", "abc"), "/x/");
});

test("stageBars: widths are relative to the largest stage", () => {
    const bars = stageBars([
        { stage: "a", label: "A", count: 10 },
        { stage: "b", label: "B", count: 5 },
        { stage: "c", label: "C", count: 1 },
        { stage: "d", label: "D", count: 0 },
    ]);
    assert.deepEqual(bars.map((b) => b.pct), [100, 50, 10, 0]);
    assert.equal(stageBars([{ stage: "a", label: "A", count: 0 }])[0].pct, 0);
    assert.deepEqual(stageBars(null), []);
});

test("waitingText: hours, then days and hours", () => {
    assert.equal(waitingText(5), "5 h");
    assert.equal(waitingText(47), "47 h");
    assert.equal(waitingText(48), "2 d");
    assert.equal(waitingText(75), "3 d 3 h");
    assert.equal(waitingText(-3), "0 h");
});

test("timeAgo and refreshStatusText", () => {
    const now = Date.parse("2026-11-09T12:00:00Z");
    assert.equal(timeAgo(null, now), "—");
    assert.equal(timeAgo("2026-11-09T11:59:40Z", now), "just now");
    assert.equal(timeAgo("2026-11-09T11:30:00Z", now), "30 min ago");
    assert.equal(timeAgo("2026-11-09T09:00:00Z", now), "3 h ago");
    assert.equal(timeAgo("2026-11-05T12:00:00Z", now), "4 d ago");
    assert.equal(refreshStatusText(null, now), "Not refreshed yet");
    assert.equal(refreshStatusText({ status: null }, now), "Not refreshed yet");
    assert.equal(refreshStatusText({ status: "success", finished_at: "2026-11-09T11:30:00Z" }, now), "Updated 30 min ago");
    assert.match(refreshStatusText({ status: "failed", finished_at: "2026-11-09T11:30:00Z" }, now), /^Last attempt failed/);
});

test("dashboardTableQuery: 24h tab and hot tab", () => {
    const a = new URLSearchParams(dashboardTableQuery("24h", "", 10));
    assert.equal(a.get("zone"), "24h");
    assert.equal(a.get("open"), "true");
    assert.equal(a.get("page_size"), "10");
    assert.equal(a.has("band"), false);
    const b = new URLSearchParams(dashboardTableQuery("hot", "3"));
    assert.equal(b.get("band"), "HOT");
    assert.equal(b.get("port"), "3");
    assert.equal(b.has("zone"), false);
});

test("withPaging, pageInfo and readPage", () => {
    assert.equal(new URLSearchParams(withPaging("?zone=24h", 2, 25)).get("page"), "2");
    assert.equal(new URLSearchParams(withPaging("", 0, 25)).get("page"), "1");
    assert.deepEqual(pageInfo(60, 2, 25), { from: 26, to: 50, total: 60, pages: 3, page: 2, hasPrev: true, hasNext: true });
    assert.deepEqual(pageInfo(0, 1, 25), { from: 0, to: 0, total: 0, pages: 1, page: 1, hasPrev: false, hasNext: false });
    assert.equal(pageInfo(60, 9, 25).page, 3);
    assert.equal(readPage("?page=4"), 4);
    assert.equal(readPage("?page=0"), 1);
    assert.equal(readPage("?page=abc"), 1);
    assert.equal(readPage(""), 1);
});

test("generatePassword: right length, all character kinds, no look-alikes", () => {
    let seed = 7;
    const fill = (arr) => {
        for (let i = 0; i < arr.length; i += 1) {
            seed = (seed * 1103515245 + 12345) & 0x7fffffff;
            arr[i] = seed;
        }
        return arr;
    };
    for (let n = 0; n < 50; n += 1) {
        const pw = generatePassword(fill, 14);
        assert.equal(pw.length, 14);
        assert.match(pw, /[A-Z]/);
        assert.match(pw, /[a-z]/);
        assert.match(pw, /[0-9]/);
        assert.match(pw, /[!@#$%&*?]/);
        assert.doesNotMatch(pw, /[Il1O0]/);
    }
});

test("filterBds: status and text search", () => {
    const rows = [
        { username: "asha", full_name: "Asha Rao", email: "asha@x.com", is_active: true },
        { username: "bela", full_name: "Bela Shah", email: "bela@x.com", is_active: false },
    ];
    assert.equal(filterBds(rows, { q: "", status: "" }).length, 2);
    assert.deepEqual(filterBds(rows, { q: "", status: "inactive" }).map((r) => r.username), ["bela"]);
    assert.deepEqual(filterBds(rows, { q: "RAO", status: "" }).map((r) => r.username), ["asha"]);
    assert.deepEqual(filterBds(rows, { q: "x.com", status: "active" }).map((r) => r.username), ["asha"]);
    assert.deepEqual(filterBds(null, null), []);
});

test("fieldErrors: first message per field", () => {
    assert.deepEqual(fieldErrors({ email: ["Bad email.", "Other"], username: "Taken" }), { email: "Bad email.", username: "Taken" });
    assert.deepEqual(fieldErrors(null), {});
    assert.deepEqual(fieldErrors({ detail: [] }), {});
});

test("formatDate: day month year in UTC", () => {
    assert.equal(formatDate("2026-11-05T23:30:00Z"), "05 Nov 2026");
    assert.equal(formatDate(null), "—");
    assert.equal(formatDate("nope"), "—");
});

import { allowanceLines } from "../dashboard-logic.js";

test("allowanceLines explains owner lookups and arrivals", () => {
    const lines = allowanceLines({
        ownership: { enabled: true, used: 30, cap: 480, remaining: 450, auto_budget_today: 12, manual_left_today: 4 },
        arrivals: [
            { port: "SGSIN", allowed_now: true },
            { port: "AEFJR", allowed_now: false, next_allowed_at: "2026-11-25T02:00:00Z" },
        ],
    });
    assert.equal(lines[0], "Owner lookups this month: 30 of 480 used (450 left).");
    assert.match(lines[1], /12 in the daily sync, 4 for the Look up owner button/);
    assert.equal(lines[2], "SGSIN: arrivals can be fetched now.");
    assert.equal(lines[3], "AEFJR: arrivals fetched, next call allowed 25/11 02:00 UTC.");
});

test("allowanceLines handles off and empty", () => {
    assert.deepEqual(allowanceLines(null), []);
    assert.deepEqual(allowanceLines({ ownership: { enabled: false } }), ["Owner lookup is switched off."]);
});
