/**
 * apps/web/static/web/js/outreach.js
 * The "Send mail" button for one owner or manager on the vessel page.
 * A person always sees the full mail first and presses Send: nothing is sent automatically.
 */
import { api } from "./api.js";
import { el, toast } from "./ui.js";
import { safeMailto } from "./vessel-logic.js";
import { kindLabel, lastMailedText, modeNote, placeholderNote, sendLabel } from "./outreach-logic.js";

let templateCache = null;

async function loadTemplates() {
    if (!templateCache) templateCache = await api.get("/api/v1/outreach/templates/");
    return templateCache;
}

function field(label, control) {
    return el("div", { class: "form-group" }, el("label", { class: "form-label" }, label), control);
}

function openDialog(rel, company, onSent) {
    const dialog = el("dialog", { class: "modal mail-dialog", "aria-label": `Send mail to ${company.name}` });
    const form = el("form", { class: "modal-form", method: "dialog" });
    const banner = el("p", { class: "mail-banner", hidden: true });
    const toInput = el("input", { class: "form-input", type: "text", readonly: true });
    const picker = el("div", { class: "tpl-picker", role: "radiogroup", "aria-label": "Email template" });
    const select = { value: "" };   // the chosen template id, kept in the same shape the rest of the code reads
    const subject = el("input", { class: "form-input", type: "text", maxlength: "200" });
    const body = el("textarea", { class: "form-input mail-body", rows: "12" });
    const notes = el("div", { class: "mail-notes", role: "status" });
    const error = el("div", { class: "form-error", role: "alert" });
    const cancel = el("button", { type: "button", class: "btn btn-secondary" }, "Cancel");
    const send = el("button", { type: "button", class: "btn btn-primary" }, sendLabel());
    let needsConfirm = false;
    let canSend = false;

    form.append(
        el("div", { class: "mail-head" },
            el("span", { class: "mail-head-icon", "aria-hidden": "true" }, "\u2709"),
            el("div", {}, el("h2", { class: "modal-title" }, `Send mail to ${company.name}`),
                el("p", { class: "mail-head-sub" }, "Review the message, edit it if you like, then press Send."))),
        banner,
        field("To", toInput),
        el("div", { class: "form-group" }, el("span", { class: "form-label" }, "Template"), picker),
        field("Subject", subject),
        field("Message (you can edit it)", body),
        notes,
        error,
        el("div", { class: "modal-actions" }, cancel, send)
    );
    dialog.appendChild(form);
    document.body.appendChild(dialog);

    const close = () => { dialog.close(); dialog.remove(); };
    cancel.addEventListener("click", close);
    dialog.addEventListener("cancel", () => dialog.remove());

    function showNotes(warnings, unknown) {
        while (notes.firstChild) notes.removeChild(notes.firstChild);
        for (const w of warnings || []) notes.appendChild(el("p", { class: "mail-warning" }, w));
        const p = placeholderNote(unknown);
        if (p) notes.appendChild(el("p", { class: "mail-warning" }, p));
    }

    async function preview() {
        error.textContent = "";
        needsConfirm = false;
        send.textContent = sendLabel();
        try {
            const r = await api.post("/api/v1/outreach/preview/", { relationship_id: rel.id, template_id: Number(select.value) });
            toInput.value = r.to;
            subject.value = r.subject;
            body.value = r.body;
            showNotes(r.warnings, r.unknown_placeholders);
            canSend = r.can_send;
            if (!r.can_send) error.textContent = r.reason;
            send.disabled = !r.can_send;
        } catch (err) {
            error.textContent = err.message || "Could not prepare the mail.";
            send.disabled = true;
        }
    }

    async function doSend() {
        send.disabled = true;
        send.textContent = sendLabel({ busy: true });
        error.textContent = "";
        try {
            const r = await api.post("/api/v1/outreach/send/", {
                relationship_id: rel.id,
                template_id: Number(select.value) || null,
                subject: subject.value,
                body: body.value,
                confirm: needsConfirm,
            });
            toast(r.detail || "Mail sent.", "success");
            close();
            onSent();
        } catch (err) {
            const data = err.data || {};
            if (err.status === 409 && data.code === "needs_confirm") {
                needsConfirm = true;
                showNotes(data.warnings, []);
                error.textContent = "Check the warnings above, then press Send anyway.";
            } else {
                error.textContent = err.message || "The mail could not be sent.";
            }
            send.disabled = !canSend;
            send.textContent = sendLabel({ needsConfirm });
        }
    }

    send.addEventListener("click", doSend);
    for (const input of [subject, body]) {
        input.addEventListener("input", () => { error.textContent = ""; });
    }

    dialog.showModal();
    send.disabled = true;
    loadTemplates().then((data) => {
        if (data.mode === "test" || data.redirect_to) {
            banner.textContent = modeNote(data.mode, data.redirect_to);
            banner.hidden = false;
        }
        if (!data.enabled) {
            error.textContent = "Sending mail is switched off.";
            return;
        }
        if (data.templates.length === 0) {
            error.textContent = "There are no email templates yet. An Admin can add them in the Django admin under Email templates.";
            return;
        }
        // The reminder template is offered first when a first mail has already been sent.
        const cards = [];
        const choose = (id) => {
            select.value = String(id);
            for (const c of cards) c.node.setAttribute("aria-checked", String(c.id === id));
            preview();
        };
        for (const t of data.templates) {
            const node = el("button", { type: "button", role: "radio", "aria-checked": "false", class: "tpl-card" },
                el("span", { class: "tpl-card-top" },
                    el("span", { class: "tpl-name" }, t.name),
                    el("span", { class: `tpl-kind tpl-kind-${t.kind}` }, kindLabel(t.kind, t.kind_label))),
                el("span", { class: "tpl-subject" }, t.subject));
            node.addEventListener("click", () => choose(t.id));
            cards.push({ id: t.id, node });
            picker.appendChild(node);
        }
        choose(rel._suggestTemplateId || data.templates[0].id);
    }).catch((err) => { error.textContent = err.message || "Could not load the templates."; });
}

/**
 * Controls shown under one owner or manager: the button and the last-mailed line.
 * @param {Object} rel relationship from /api/v1/relationships/
 * @param {Object} company rel.company_detail
 * @param {Object|undefined} lastMail row from /api/v1/outreach/log/ for this company
 * @param {Function} onSent called after a mail was sent, to reload the section
 * @returns {HTMLElement}
 */
export function renderMailControls(rel, company, lastMail, onSent) {
    const box = el("div", { class: "mail-controls" });
    const last = lastMailedText(lastMail);
    if (!safeMailto(company.email)) {
        box.appendChild(el("span", { class: "mail-note" }, "No email address on file."));
    } else {
        const button = el("button", { type: "button", class: "btn btn-secondary" }, lastMail ? "Send another mail" : "Send mail");
        if (lastMail) {
            // A second mail is normally the 24 hour reminder.
            loadTemplates().then((d) => {
                const reminder = d.templates.find((t) => t.kind === "reminder");
                if (reminder) rel._suggestTemplateId = reminder.id;
            }).catch(() => {});
        }
        button.addEventListener("click", () => openDialog(rel, company, onSent));
        box.appendChild(button);
    }
    if (last) box.appendChild(el("span", { class: "mail-last" }, last));
    return box;
}
