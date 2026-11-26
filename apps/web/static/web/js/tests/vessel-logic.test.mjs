/**
 * apps/web/static/web/js/tests/vessel-logic.test.mjs
 * Unit tests for vessel detail pure functions using node:test.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

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
} from "../vessel-logic.js";

test("navStatusLabel: handles standard ITU-R codes", () => {
    assert.equal(navStatusLabel(0), "Under way using engine");
    assert.equal(navStatusLabel("0"), "Under way using engine");
    assert.equal(navStatusLabel(1), "At anchor");
    assert.equal(navStatusLabel(2), "Not under command");
    assert.equal(navStatusLabel(3), "Restricted manoeuvrability");
    assert.equal(navStatusLabel(4), "Constrained by draught");
    assert.equal(navStatusLabel(5), "Moored");
    assert.equal(navStatusLabel(6), "Aground");
    assert.equal(navStatusLabel(7), "Engaged in fishing");
    assert.equal(navStatusLabel(8), "Under way sailing");
    assert.equal(navStatusLabel(14), "AIS-SART");
    assert.equal(navStatusLabel(15), "Undefined");
});

test("navStatusLabel: handles unconfirmed codes 98, 99 and unknown values", () => {
    assert.equal(navStatusLabel(99), "Unknown (code 99)");
    assert.equal(navStatusLabel(98), "Unknown (code 98)");
    assert.equal(navStatusLabel("99"), "Unknown (code 99)");
    assert.equal(navStatusLabel("random_status"), "Unknown (code random_status)");
});

test("navStatusLabel: handles null, undefined and empty values", () => {
    assert.equal(navStatusLabel(null), "—");
    assert.equal(navStatusLabel(undefined), "—");
    assert.equal(navStatusLabel(""), "—");
});

test("portAreaLabel: formats known and fallback areas", () => {
    assert.equal(portAreaLabel("inbound"), "Inbound");
    assert.equal(portAreaLabel("IN_PORT"), "In Port");
    assert.equal(portAreaLabel("anchorage"), "Anchorage");
    assert.equal(portAreaLabel("anchorage_bound"), "Anchorage Bound");
    assert.equal(portAreaLabel("unknown"), "Unknown");
    assert.equal(portAreaLabel("coastal"), "coastal");
    assert.equal(portAreaLabel(null), "—");
    assert.equal(portAreaLabel(""), "—");
});

test("safeHttpUrl: accepts valid http and https URLs", () => {
    assert.deepEqual(safeHttpUrl("https://example.com"), {
        href: "https://example.com/",
        text: "https://example.com",
    });
    assert.deepEqual(safeHttpUrl("http://company.com/fleet"), {
        href: "http://company.com/fleet",
        text: "http://company.com/fleet",
    });
});

test("safeHttpUrl: prepends https:// for valid domains without scheme", () => {
    assert.deepEqual(safeHttpUrl("example.com"), {
        href: "https://example.com/",
        text: "example.com",
    });
    assert.deepEqual(safeHttpUrl("sub.shipping.co.uk/portal"), {
        href: "https://sub.shipping.co.uk/portal",
        text: "sub.shipping.co.uk/portal",
    });
});

test("safeHttpUrl: rejects dangerous schemes and invalid inputs", () => {
    assert.equal(safeHttpUrl("javascript:alert(1)"), null);
    assert.equal(safeHttpUrl("data:text/html,x"), null);
    assert.equal(safeHttpUrl("file:///etc/passwd"), null);
    assert.equal(safeHttpUrl(""), null);
    assert.equal(safeHttpUrl("   "), null);
    assert.equal(safeHttpUrl(null), null);
    assert.equal(safeHttpUrl("not a valid url with spaces"), null);
});

test("safeMailto: validates well-formed emails", () => {
    assert.equal(safeMailto("ops@shipping.com"), "mailto:ops@shipping.com");
    assert.equal(safeMailto("  chartering@angloeastern.com  "), "mailto:chartering@angloeastern.com");
});

test("safeMailto: rejects invalid and injection payloads", () => {
    assert.equal(safeMailto("ops@@shipping.com"), null);
    assert.equal(safeMailto("ops @shipping.com"), null);
    assert.equal(safeMailto("<script>alert(1)</script>@test.com"), null);
    assert.equal(safeMailto("ops@domain<tag>"), null);
    assert.equal(safeMailto("not-an-email"), null);
    assert.equal(safeMailto(""), null);
    assert.equal(safeMailto(null), null);
});

test("groupContacts: orders roles strictly according to preferred hierarchy", () => {
    const rawRels = [
        { role: "operator", role_label: "Operator", company_detail: { name: "Operator Co" } },
        { role: "manager", role_label: "Manager", company_detail: { name: "Manager Co" } },
        { role: "registered_owner", role_label: "Registered Owner", company_detail: { name: "Reg Owner Co" } },
        { role: "technical_manager", role_label: "Technical Manager", company_detail: { name: "Tech Co" } },
        { role: "custom_agent", role_label: "Custom Agent", company_detail: { name: "Agent Co" } },
        { role: "beneficial_owner", role_label: "Beneficial Owner", company_detail: { name: "Ben Owner Co" } },
    ];

    const groups = groupContacts(rawRels);
    const roleOrder = groups.map(g => g.role);

    assert.deepEqual(roleOrder, [
        "registered_owner",
        "beneficial_owner",
        "technical_manager",
        "operator",
        "manager",
        "custom_agent",
    ]);

    assert.equal(groups[0].items.length, 1);
    assert.equal(groups[0].items[0].company_detail.name, "Reg Owner Co");
});

test("groupContacts: handles empty and null lists", () => {
    assert.deepEqual(groupContacts([]), []);
    assert.deepEqual(groupContacts(null), []);
    assert.deepEqual(groupContacts(undefined), []);
});

test("vesselAge: calculates age accurately", () => {
    assert.equal(vesselAge(2009, 2026), "2009, 17 years");
    assert.equal(vesselAge("2009", 2026), "2009, 17 years");
    assert.equal(vesselAge(2025, 2026), "2025, 1 year");
    assert.equal(vesselAge(2026, 2026), "2026, 0 years");
    assert.equal(vesselAge(null), "—");
    assert.equal(vesselAge(0), "—");
    assert.equal(vesselAge("invalid"), "—");
});

test("positionAgeHours: calculates elapsed hours and stale detection", () => {
    const now = new Date("2026-11-05T12:00:00Z").getTime();

    // 5 hours old
    const fiveHoursAgo = new Date("2026-11-05T07:00:00Z").toISOString();
    assert.equal(positionAgeHours(fiveHoursAgo, now), 5);

    // 25 hours old (stale)
    const twentyFiveHoursAgo = new Date("2026-11-04T11:00:00Z").toISOString();
    assert.equal(positionAgeHours(twentyFiveHoursAgo, now), 25);

    // Future or zero diff
    assert.equal(positionAgeHours("2026-11-05T12:00:00Z", now), 0);
    assert.equal(positionAgeHours(null, now), null);
    assert.equal(positionAgeHours("invalid-date", now), null);
});

test("osmUrl: formats OpenStreetMap map link from valid coordinates", () => {
    assert.equal(
        osmUrl(1.23456, 103.85195),
        "https://www.openstreetmap.org/?mlat=1.23456&mlon=103.85195#map=12/1.23456/103.85195"
    );
    assert.equal(osmUrl(null, 103.85), null);
    assert.equal(osmUrl(1.23, null), null);
    assert.equal(osmUrl("abc", 103.85), null);
});

test("formatCoord: formats to 5 decimal places with fallback", () => {
    assert.equal(formatCoord(1.2345678), "1.23457");
    assert.equal(formatCoord("103.851951"), "103.85195");
    assert.equal(formatCoord(null), "—");
    assert.equal(formatCoord(""), "—");
    assert.equal(formatCoord("invalid"), "—");
});

test("formatting helpers: formatMetres, formatNumber, formatDate, formatDateTimeUtc", () => {
    assert.equal(formatMetres(225.4), "225.4 m");
    assert.equal(formatMetres(null), "—");
    assert.equal(formatMetres(0), "—");

    assert.equal(formatNumber(125000), "125,000");
    assert.equal(formatNumber(0), "—");
    assert.equal(formatNumber(null), "—");

    assert.equal(formatDate("2025-08-15T00:00:00Z"), "2025-08-15");
    assert.equal(formatDate(null), "—");

    assert.equal(formatDateTimeUtc("2026-11-04T14:30:00Z"), "2026-11-04 14:30 UTC");
    assert.equal(formatDateTimeUtc(null), "—");
});

test("verificationText: says who confirmed it and when, only when verified", () => {
    assert.equal(verificationText({ verified: false }), "");
    assert.equal(verificationText(null), "");
    assert.equal(
        verificationText({ verified: true, verified_by_name: "Asha Rao", last_verified_date: "2026-11-24" }),
        "Confirmed by Asha Rao on 2026-11-24"
    );
    assert.equal(verificationText({ verified: true, verified_by_name: "", last_verified_date: null }), "Confirmed");
    assert.equal(verificationText({ verified: true, verified_by_name: "Asha Rao" }), "Confirmed by Asha Rao");
});

import { ownerLookupText } from "../vessel-logic.js";

test("ownerLookupText separates never looked up from no data returned", () => {
    assert.equal(ownerLookupText(null, false), "Owner not looked up yet.");
    assert.match(ownerLookupText("2026-11-20T01:00:00Z", false), /^Checked on .*no data returned\.$/);
    assert.match(ownerLookupText("2026-11-20T01:00:00Z", true), /^Owner data last checked on /);
});
