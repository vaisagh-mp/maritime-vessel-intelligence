/**
 * apps/web/static/web/js/email-templates.js
 * "Email templates" page: list, add, edit and switch off the messages used by the Send mail button.
 */
import { api } from "./api.js";
import { el, errorState, formatUtc, onReady, registerGlobalErrorHandlers, renderPageCrash, toast } from "./ui.js";
import { insertPlaceholder, unknownPlaceholders } from "./email-logic.js";
import { kindLabel } from "./outreach-logic.js";

let meta = { placeholders: [], kinds: [] };

function byId(id) {
    return document.getElementById(id);
}

function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
}

function card(t, reload) {
    const edit = el("button", { type: "button", class: "btn btn-secondary" }, "Edit");
    const toggle = el("button", { type: "button", class: "btn btn-secondary" }, t.active ? "Switch off" : "Switch on");
    edit.addEventListener("click", () => openEditor(t, reload));
    toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        try {
            await api.patch(`/api/v1/outreach/manage/templates/${t.id}/`, { active: !t.active });
            toast(t.active ? "Template switched off. It is no longer offered when sending." : "Template switched on.", "success");
            reload();
        } catch (err) {
            toast(err.message || "Could not change the template.", "error");
            toggle.disabled = false;
        }
    });
    return el("article", { class: `tpl-manage-card${t.active ? "" : " is-off"}` },
        el("div", { class: "tpl-card-top" },
            el("h2", { class: "tpl-manage-name" }, t.name),
            el("span", { class: `tpl-kind tpl-kind-${t.kind}` }, kindLabel(t.kind, t.kind_label)),
            t.active ? null : el("span", { class: "tpl-kind tpl-kind-off" }, "Switched off")),
        el("p", { class: "tpl-manage-subject" }, el("strong", {}, "Subject: "), t.subject),
        el("pre", { class: "tpl-manage-body" }, t.body),
        el("div", { class: "tpl-manage-foot" },
            el("span", { class: "text-muted" }, `Updated ${formatUtc(t.updated_at)}`),
            el("span", { class: "tpl-manage-actions" }, toggle, edit)));
}

function openEditor(t, reload) {
    const isNew = !t;
    const name = el("input", { class: "form-input", type: "text", maxlength: "120", value: t ? t.name : "" });
    const kind = el("select", { class: "form-input" },
        ...meta.kinds.map((k) => el("option", { value: k.value }, k.label)));
    kind.value = t ? t.kind : "first_contact";
    const subject = el("input", { class: "form-input", type: "text", maxlength: "200", value: t ? t.subject : "" });
    const body = el("textarea", { class: "form-input email-body", rows: "12" });
    body.value = t ? t.body : "";
    const active = el("input", { type: "checkbox", id: "tpl-active" });
    active.checked = t ? t.active : true;
    const order = el("input", { class: "form-input", type: "number", min: "0", max: "100000", value: String(t ? t.sort_order : 100) });
    const error = el("div", { class: "form-error", role: "alert" });
    const hint = el("p", { class: "email-hint", role: "status" });
    const cancel = el("button", { type: "button", class: "btn btn-secondary" }, "Cancel");
    const save = el("button", { type: "submit", class: "btn btn-primary" }, isNew ? "Add template" : "Save changes");
    const errs = {};
    const group = (label, control, key, note) => {
        const e = el("div", { class: "form-error field-error" });
        errs[key] = e;
        return el("div", { class: "form-group" }, el("label", { class: "form-label" }, label), control, note || null, e);
    };

    let target = body;                              // the field a placeholder chip goes into
    subject.addEventListener("focus", () => { target = subject; });
    body.addEventListener("focus", () => { target = body; });
    const chips = el("div", { class: "email-chips", role: "group", "aria-label": "Insert a placeholder" },
        ...meta.placeholders.map((name_) => {
            const b = el("button", { type: "button", class: "email-chip", title: `Insert {{${name_}}}` }, `{{${name_}}}`);
            b.addEventListener("click", () => {
                const r = insertPlaceholder(target.value, target.selectionStart, target.selectionEnd, name_);
                target.value = r.value;
                target.focus();
                target.setSelectionRange(r.cursor, r.cursor);
                checkPlaceholders();
            });
            return b;
        }));
    function checkPlaceholders() {
        const bad = unknownPlaceholders(`${subject.value}\n${body.value}`, meta.placeholders);
        hint.textContent = bad.length ? `These placeholders are not known and will stay as typed: ${bad.map((n) => `{{${n}}}`).join(", ")}` : "";
    }
    subject.addEventListener("input", checkPlaceholders);
    body.addEventListener("input", checkPlaceholders);

    const dialog = el("dialog", { class: "modal tpl-dialog", "aria-label": isNew ? "New template" : "Edit template" });
    const form = el("form", { class: "modal-form", method: "dialog" },
        el("h2", { class: "modal-title" }, isNew ? "New template" : "Edit template"),
        group("Name", name, "name"),
        group("Used for", kind, "kind"),
        group("Subject", subject, "subject"),
        group("Message", body, "body"),
        el("div", { class: "form-group" }, el("span", { class: "form-label" }, "Placeholders (press one to insert it where the cursor is)"), chips, hint),
        el("div", { class: "form-group email-inline" }, group("Show order (lower comes first)", order, "sort_order"),
            el("label", { class: "email-check", for: "tpl-active" }, active, " Offer this template when sending")),
        error,
        el("div", { class: "modal-actions" }, cancel, save));
    dialog.appendChild(form);
    document.body.appendChild(dialog);
    const close = () => { dialog.close(); dialog.remove(); };
    cancel.addEventListener("click", close);
    dialog.addEventListener("cancel", () => dialog.remove());

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        error.textContent = "";
        for (const e of Object.values(errs)) e.textContent = "";
        save.disabled = true;
        const payload = { name: name.value, kind: kind.value, subject: subject.value, body: body.value,
            active: active.checked, sort_order: Number(order.value) || 0 };
        try {
            if (isNew) await api.post("/api/v1/outreach/manage/templates/", payload);
            else await api.patch(`/api/v1/outreach/manage/templates/${t.id}/`, payload);
            toast(isNew ? "Template added." : "Template saved.", "success");
            close();
            reload();
        } catch (err) {
            const fields = (err.data && err.data.errors) || {};
            for (const [k, msg] of Object.entries(fields)) if (errs[k]) errs[k].textContent = msg;
            error.textContent = err.message || "Could not save the template.";
            save.disabled = false;
        }
    });
    dialog.showModal();
    name.focus();
    checkPlaceholders();
}

async function load() {
    const host = byId("tpl-host");
    clear(host);
    host.appendChild(el("div", { class: "loading-state" }, "Loading…"));
    try {
        const data = await api.get("/api/v1/outreach/manage/templates/");
        meta = { placeholders: data.placeholders, kinds: data.kinds };
        const banner = byId("tpl-mode");
        banner.hidden = data.mode !== "test";
        banner.textContent = data.mode === "test" ? "Test mode: no mail server is set up, so mails are only printed in the server window and not delivered." : "";
        clear(host);
        if (data.templates.length === 0) {
            host.appendChild(el("div", { class: "empty-state" }, "There are no templates yet. Press New template to add the first one."));
            return;
        }
        for (const t of data.templates) host.appendChild(card(t, load));
    } catch (err) {
        clear(host);
        host.appendChild(errorState(err.message || "Could not load the templates", load));
    }
}

onReady(() => {
    registerGlobalErrorHandlers();
    const root = byId("tpl-host");
    if (!root) return;
    try {
        byId("tpl-new").addEventListener("click", () => openEditor(null, load));
        load();
    } catch (err) {
        renderPageCrash(root, "The page could not start", err);
    }
});
