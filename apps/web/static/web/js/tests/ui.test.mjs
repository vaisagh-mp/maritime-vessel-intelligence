import { test } from "node:test";
import assert from "node:assert/strict";
import { onReady, formatErrorMessage } from "../ui.js";

test("onReady: attaches DOMContentLoaded listener when readyState is loading", () => {
    let listenerAdded = false;
    let eventName = null;
    let callbackCalled = false;

    const fakeDoc = {
        readyState: "loading",
        addEventListener(event, fn, opts) {
            listenerAdded = true;
            eventName = event;
            fn();
        },
    };

    const origDoc = global.document;
    global.document = fakeDoc;

    try {
        onReady(() => {
            callbackCalled = true;
        });
        assert.equal(listenerAdded, true);
        assert.equal(eventName, "DOMContentLoaded");
        assert.equal(callbackCalled, true);
    } finally {
        global.document = origDoc;
    }
});

test("onReady: invokes callback immediately when readyState is interactive or complete", () => {
    let callbackCount = 0;

    const fakeDoc = {
        readyState: "interactive",
        addEventListener() {
            assert.fail("Should not call addEventListener when readyState is interactive");
        },
    };

    const origDoc = global.document;
    global.document = fakeDoc;

    try {
        onReady(() => {
            callbackCount++;
        });
        assert.equal(callbackCount, 1);

        fakeDoc.readyState = "complete";
        onReady(() => {
            callbackCount++;
        });
        assert.equal(callbackCount, 2);
    } finally {
        global.document = origDoc;
    }
});

test("formatErrorMessage: prefixes Error: cleanly without duplication", () => {
    assert.equal(formatErrorMessage("Network failure"), "Error: Network failure");
    assert.equal(formatErrorMessage("Error: Already prefixed"), "Error: Already prefixed");
    assert.equal(formatErrorMessage(""), "Error: An unexpected error occurred.");
    assert.equal(formatErrorMessage(null), "Error: An unexpected error occurred.");
});
