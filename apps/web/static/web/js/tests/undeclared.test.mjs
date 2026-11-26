/**
 * apps/web/static/web/js/tests/undeclared.test.mjs
 * Regression guard: detects undeclared identifiers and leftovers in frontend controllers.
 * Tests pure controller note-handling smoke path and static scope consistency.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { noteFormState } from "../lead-logic.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const jsDir = path.resolve(__dirname, "..");

test("regression guard: no undeclared leftovers like trimmedNote exist in controller files", () => {
    const controllers = ["lead.js", "vessel.js", "dashboard.js", "priority.js", "bd.js", "sidebar.js", "lead-table.js", "dashboard-logic.js", "ui.js", "api.js"];
    const forbiddenUndeclared = ["trimmedNote"];

    for (const filename of controllers) {
        const filepath = path.join(jsDir, filename);
        const content = fs.readFileSync(filepath, "utf8");

        for (const token of forbiddenUndeclared) {
            const regex = new RegExp(`\\b${token}\\b`, "g");
            const matches = [...content.matchAll(regex)];

            if (matches.length > 0) {
                // Must be explicitly declared in the same scope via const/let/var/param/import
                const isDeclared =
                    new RegExp(`\\b(const|let|var|import)\\s+[^;]*?\\b${token}\\b`).test(content) ||
                    new RegExp(`\\bfunction\\s+[^)]*?\\b${token}\\b`).test(content);
                assert.ok(
                    isDeclared,
                    `File ${filename} uses undeclared identifier '${token}' without declaring it in scope!`
                );
            }
        }
    }
});

test("regression guard: all function calls in lead.js are declared, imported, or standard builtins", () => {
    const leadCode = fs.readFileSync(path.join(jsDir, "lead.js"), "utf8");

    // Extract imported symbols
    const importedSymbols = new Set();
    const importRegex = /import\s*\{([^}]+)\}\s*from/g;
    let match;
    while ((match = importRegex.exec(leadCode)) !== null) {
        match[1].split(",").forEach((s) => {
            const sym = s.trim().split(/\s+as\s+/).pop().trim();
            if (sym) importedSymbols.add(sym);
        });
    }

    // Extract declared functions in lead.js
    const declaredSymbols = new Set([
        ...importedSymbols,
        "initBackLink",
        "renderHeader",
        "renderProgressStrip",
        "populateStageSelect",
        "updateStageButtonState",
        "initStageForm",
        "executeStagePatch",
        "renderNoteItem",
        "loadNotes",
        "initNoteForm",
        "renderHistoryItem",
        "loadHistory",
        "renderVesselSummary",
    ]);

    // Known standard built-ins / globals
    const allowedGlobals = new Set([
        "Boolean", "String", "Number", "Array", "Object", "Date", "Math", "Set", "Map", "Promise",
        "Error", "TypeError", "RangeError", "parseInt", "parseFloat", "isNaN",
        "encodeURIComponent", "decodeURIComponent", "clearTimeout", "setTimeout",
        "fetch", "alert", "confirm",
    ]);

    // Strip comments and strings
    const cleanCode = leadCode
        .replace(/\/\*[\s\S]*?\*\//g, " ")
        .replace(/\/\/.*/g, " ")
        .replace(/"(?:\\.|[^"\\])*"/g, '""')
        .replace(/'(?:\\.|[^'\\])*'/g, "''")
        .replace(/`(?:\\[\s\S]|[^`\\])*`/g, "``");

    // Matches word followed by '(' but not preceded by '.' or keywords
    const callRegex = /(?<![.\w$])([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(/g;
    const keywords = new Set(["if", "for", "while", "switch", "catch", "function", "return", "typeof", "super", "import", "async"]);

    const unknownCalls = [];
    while ((match = callRegex.exec(cleanCode)) !== null) {
        const fnName = match[1];
        if (keywords.has(fnName)) continue;
        if (!declaredSymbols.has(fnName) && !allowedGlobals.has(fnName)) {
            unknownCalls.push(fnName);
        }
    }

    assert.deepEqual(
        unknownCalls,
        [],
        `Found function calls to undeclared/unimported symbols in lead.js: ${unknownCalls.join(", ")}`
    );
});

test("smoke test: noteFormState handles empty, spaces only, 1 char, exactly 2000, 2001, and busy true without throwing", () => {
    // 1. empty (empty string, null, undefined)
    const emptyRes = noteFormState("", false);
    assert.deepEqual(emptyRes, {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });

    const nullRes = noteFormState(null, false);
    assert.deepEqual(nullRes, {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });

    const undefRes = noteFormState(undefined, false);
    assert.deepEqual(undefRes, {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });

    // 2. spaces only
    const spacesRes = noteFormState("   \t\n  ", false);
    assert.deepEqual(spacesRes, {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });

    // 3. 1 char
    const oneCharRes = noteFormState("a", false);
    assert.deepEqual(oneCharRes, {
        trimmed: "a",
        counterText: "1 / 2000",
        canSubmit: true,
        error: null,
    });

    const oneCharPadded = noteFormState("   b   ", false);
    assert.deepEqual(oneCharPadded, {
        trimmed: "b",
        counterText: "1 / 2000",
        canSubmit: true,
        error: null,
    });

    // 4. exactly 2000 chars
    const text2000 = "x".repeat(2000);
    const res2000 = noteFormState(text2000, false);
    assert.deepEqual(res2000, {
        trimmed: text2000,
        counterText: "2000 / 2000",
        canSubmit: true,
        error: null,
    });

    // 5. 2001 chars
    const text2001 = "x".repeat(2001);
    const res2001 = noteFormState(text2001, false);
    assert.equal(res2001.counterText, "2001 / 2000");
    assert.equal(res2001.canSubmit, false);
    assert.equal(res2001.error, "Ensure this field has no more than 2000 characters.");

    // 6. busy true
    const busyRes = noteFormState("Meeting confirmed with charterer", true);
    assert.deepEqual(busyRes, {
        trimmed: "Meeting confirmed with charterer",
        counterText: "32 / 2000",
        canSubmit: false,
        error: null,
    });

    // Non-string / defensive checks
    const elemRes = noteFormState({ value: "textarea", tagName: "TEXTAREA" }, false);
    assert.deepEqual(elemRes, {
        trimmed: "",
        counterText: "0 / 2000",
        canSubmit: false,
        error: "Note cannot be empty.",
    });
});

test("dynamic controller smoke test: lead.js initializes without ReferenceError and fills header", async () => {
    class FakeNode {}
    globalThis.Node = FakeNode;

    const elements = new Map();

    function makeElement(tag, id = "") {
        const el = Object.assign(new FakeNode(), {
            tagName: tag.toUpperCase(),
            id,
            textContent: "",
            value: id === "stage-select" ? "qualifying" : "",
            href: "",
            dataset: {},
            classList: {
                add() {},
                remove() {},
                contains() { return false; },
            },
            children: [],
            appendChild(c) {
                this.children.push(c);
                return c;
            },
            removeChild(c) {
                const idx = this.children.indexOf(c);
                if (idx >= 0) this.children.splice(idx, 1);
                return c;
            },
            get firstChild() {
                return this.children[0] || null;
            },
            addEventListener() {},
            setAttribute(k, v) {
                this[k] = v;
            },
            getAttribute(k) {
                return this[k] || null;
            },
            querySelector() {
                return null;
            },
        });
        return el;
    }

    const mainEl = makeElement("main");
    mainEl.dataset.leadId = "678";

    const headerEl = makeElement("header", "page-header");
    const vesselLink = makeElement("a", "header-vessel-link");
    const stageSelect = makeElement("select", "stage-select");
    const stageTextarea = makeElement("textarea", "stage-note-input");
    const stageBtn = makeElement("button", "stage-update-btn");
    const noteTextarea = makeElement("textarea", "note-text-input");
    const noteSaveBtn = makeElement("button", "note-save-btn");

    elements.set("page-header", headerEl);
    elements.set("header-vessel-link", vesselLink);
    elements.set("stage-select", stageSelect);
    elements.set("stage-note-input", stageTextarea);
    elements.set("stage-update-btn", stageBtn);
    elements.set("note-text-input", noteTextarea);
    elements.set("note-save-btn", noteSaveBtn);

    globalThis.document = {
        readyState: "complete",
        querySelector(sel) {
            if (sel.includes("data-lead-id")) return mainEl;
            return null;
        },
        getElementById(id) {
            if (!elements.has(id)) {
                elements.set(id, makeElement("div", id));
            }
            return elements.get(id);
        },
        createElement(tag) {
            return makeElement(tag);
        },
        createTextNode(txt) {
            return Object.assign(new FakeNode(), { textContent: String(txt) });
        },
        addEventListener() {},
        body: makeElement("body"),
    };

    globalThis.window = {
        location: { pathname: "/leads/678/", search: "", href: "/leads/678/" },
        history: { replaceState() {} },
        addEventListener() {},
    };

    globalThis.sessionStorage = {
        getItem() { return null; },
        setItem() {},
        removeItem() {},
    };

    // Mock API responses
    const { api } = await import("../api.js");
    api.get = async (url) => {
        if (url.includes("/opportunities/678/notes/")) {
            return { results: [], next: null };
        }
        if (url.includes("/opportunities/678/history/")) {
            return { results: [], next: null };
        }
        if (url.includes("/opportunities/678/")) {
            return {
                id: 678,
                vessel: 12,
                stage: "qualifying",
                vessel_summary: {
                    id: 12,
                    name: "PACIFIC VOYAGER",
                    imo: 9123456,
                    mmsi: 563000123,
                    vessel_type: "Bulk Carrier",
                    grt: 45000,
                    flag: "SG",
                },
                port_summary: {
                    name: "Singapore",
                    un_locode: "SGSIN",
                },
            };
        }
        return {};
    };

    // Dynamically import lead.js - triggers onReady execution
    await import("../lead.js");

    // Wait a short tick for async promises to complete
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Header vessel link must be populated with data from API without error
    assert.equal(vesselLink.textContent, "PACIFIC VOYAGER");
    assert.equal(vesselLink.href, "/vessels/12/");
});
