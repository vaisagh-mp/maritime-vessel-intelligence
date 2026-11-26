import { test } from "node:test";
import assert from "node:assert/strict";

import { indexByCompany, lastMailedText, modeNote, placeholderNote, sendLabel } from "../outreach-logic.js";

test("lastMailedText shows date, person, template and count", () => {
    assert.equal(lastMailedText(null), "");
    assert.equal(lastMailedText({}), "");
    assert.equal(
        lastMailedText({ sent_at: "2026-11-25T08:14:00Z", sent_by: "Asha Rao", template: "First contact", count: 1, status: "sent" }),
        "Last mailed 25 Nov 2026 by Asha Rao (First contact)");
    assert.equal(
        lastMailedText({ sent_at: "2026-11-25T08:14:00Z", sent_by: "Asha Rao", count: 3, status: "test" }),
        "Last mailed 25 Nov 2026 by Asha Rao, 3 mails in all · test mode, not delivered");
    assert.equal(lastMailedText({ sent_at: "garbage" }), "");
});

test("indexByCompany, modeNote, placeholderNote, sendLabel", () => {
    assert.deepEqual(Object.keys(indexByCompany([{ company_id: 4 }, { company_id: 9 }])), ["4", "9"]);
    assert.deepEqual(indexByCompany(null), {});
    assert.match(modeNote("test"), /not delivered/);
    assert.equal(modeNote("live"), "");
    assert.match(modeNote("live", "me@gmail.com"), /me@gmail.com instead of the company/);
    assert.equal(placeholderNote([]), "");
    assert.equal(placeholderNote(["nope", "x"]), "Replace these before sending: {{nope}}, {{x}}");
    assert.equal(sendLabel(), "Send mail");
    assert.equal(sendLabel({ needsConfirm: true }), "Send anyway");
    assert.equal(sendLabel({ busy: true, needsConfirm: true }), "Sending…");
});

import { kindLabel } from "../outreach-logic.js";
test("kindLabel gives a short badge text", () => {
    assert.equal(kindLabel("first_contact"), "First mail");
    assert.equal(kindLabel("reminder"), "Reminder");
    assert.equal(kindLabel("zzz", "Custom"), "Custom");
    assert.equal(kindLabel("zzz"), "Other");
});
