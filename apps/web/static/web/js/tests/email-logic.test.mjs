import { test } from "node:test";
import assert from "node:assert/strict";

import { historyQuery, insertPlaceholder, pagerText, statusInfo, unknownPlaceholders } from "../email-logic.js";

test("historyQuery only includes what is set", () => {
    assert.equal(historyQuery(), "");
    assert.equal(historyQuery({ q: " acme ", status: "sent", page: 3 }), "?q=acme&status=sent&page=3");
    assert.equal(historyQuery({ page: 1 }), "");
});

test("statusInfo names each result", () => {
    assert.equal(statusInfo("sent").label, "Sent");
    assert.equal(statusInfo("test").tone, "test");
    assert.equal(statusInfo("anything else").tone, "bad");
});

test("insertPlaceholder replaces the selection and moves the cursor", () => {
    assert.deepEqual(insertPlaceholder("Dear ,", 5, 5, "company_name"), { value: "Dear {{company_name}},", cursor: 21 });
    assert.deepEqual(insertPlaceholder("abc", 0, 3, "imo"), { value: "{{imo}}", cursor: 7 });
    assert.equal(insertPlaceholder("abc", undefined, undefined, "imo").value, "abc{{imo}}");
});

test("unknownPlaceholders lists the ones the server cannot fill", () => {
    assert.deepEqual(unknownPlaceholders("{{imo}} {{ foo }} {{foo}} {{bar}}", ["imo"]), ["bar", "foo"]);
    assert.deepEqual(unknownPlaceholders("", ["imo"]), []);
});

test("pagerText", () => {
    assert.equal(pagerText(1, 1), "");
    assert.equal(pagerText(2, 5), "Page 2 of 5");
});
