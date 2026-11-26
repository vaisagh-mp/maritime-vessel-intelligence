/**
 * apps/web/static/web/js/bd.js
 * Business Developers page (Admin only): list, add, edit, reset password,
 * activate / deactivate. All networking goes through api.js; DOM through el().
 */

import { api } from "./api.js";
import { fieldErrors, filterBds, formatDate, generatePassword, timeAgo } from "./dashboard-logic.js";
import { el, errorState, onReady, registerGlobalErrorHandlers, renderPageCrash, toast } from "./ui.js";

const API = "/api/v1/business-developers/";

const state = {
    rows: [],
    filter: { q: "", status: "" },
    meId: Number(document.getElementById("main").dataset.meId) || 0,
};

function byId(id) {
    return document.getElementById(id);
}

function randomFill(arr) {
    return window.crypto.getRandomValues(arr);
}

/* ---------- Table ---------- */

function statusBadge(active) {
    return el("span", { class: active ? "badge badge-inbound" : "badge badge-low" }, active ? "Active" : "Inactive");
}

function nameCell(row) {
    const initial = (row.full_name || row.username || "?").trim().slice(0, 1).toUpperCase();
    return el(
        "div",
        { class: "person" },
        el("span", { class: "avatar avatar-sm", "aria-hidden": "true" }, initial),
        el(
            "div",
            { class: "cell-stack" },
            el("span", { class: "cell-title" }, row.full_name),
            el("span", { class: "cell-sub" }, `@${row.username}`)
        )
    );
}

function activityText(row) {
    const c = row.stage_changes;
    const n = row.notes;
    if (!c && !n) return "No activity yet";
    return `${c} stage change${c === 1 ? "" : "s"} · ${n} note${n === 1 ? "" : "s"}`;
}

function actionButtons(row) {
    const isMe = row.id === state.meId;
    const toggleLabel = row.is_active ? "Deactivate" : "Activate";
    const buttons = [
        el("button", { type: "button", class: "btn btn-secondary btn-sm", onClick: () => openEdit(row), "aria-label": `Edit ${row.full_name}` }, "Edit"),
        el("button", { type: "button", class: "btn btn-secondary btn-sm", onClick: () => openPassword(row), "aria-label": `Reset password for ${row.full_name}` }, "Reset password"),
    ];
    const toggle = el(
        "button",
        {
            type: "button",
            class: row.is_active ? "btn btn-quiet btn-sm btn-danger-text" : "btn btn-quiet btn-sm",
            disabled: isMe && row.is_active,
            title: isMe && row.is_active ? "You cannot deactivate your own account" : "",
            onClick: () => confirmToggle(row),
            "aria-label": `${toggleLabel} ${row.full_name}`,
        },
        toggleLabel
    );
    buttons.push(toggle);
    return el("div", { class: "row-actions" }, ...buttons);
}

function render() {
    const host = byId("bd-table-host");
    host.textContent = "";
    const rows = filterBds(state.rows, state.filter);
    const active = state.rows.filter((r) => r.is_active).length;
    byId("bd-summary").textContent = `${state.rows.length} business developer${state.rows.length === 1 ? "" : "s"} · ${active} active`;

    if (state.rows.length === 0) {
        host.appendChild(
            el(
                "div",
                { class: "empty-state", role: "status" },
                "No Business Developers yet. Use “Add Business Developer” to create the first one."
            )
        );
        return;
    }
    if (rows.length === 0) {
        host.appendChild(el("div", { class: "empty-state", role: "status" }, "No one matches these filters."));
        return;
    }
    const head = ["Business Developer", "Email", "Status", "Activity", "Last login", "Joined", "Actions"];
    const table = el(
        "table",
        { class: "data-table" },
        el("caption", { class: "visually-hidden" }, "Business Developers"),
        el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { scope: "col" }, h)))),
        el(
            "tbody",
            {},
            ...rows.map((r) =>
                el(
                    "tr",
                    {},
                    el("td", { "data-label": head[0] }, nameCell(r)),
                    el("td", { "data-label": head[1] }, r.email || "—"),
                    el("td", { "data-label": head[2] }, statusBadge(r.is_active)),
                    el("td", { "data-label": head[3] }, activityText(r)),
                    el("td", { "data-label": head[4] }, r.last_login ? timeAgo(r.last_login) : "Never"),
                    el("td", { "data-label": head[5] }, formatDate(r.date_joined)),
                    el("td", { "data-label": head[6] }, actionButtons(r))
                )
            )
        )
    );
    host.appendChild(el("div", { class: "table-scroll" }, table));
}

async function load() {
    const host = byId("bd-table-host");
    host.textContent = "";
    host.appendChild(el("div", { class: "loading-state", role: "status" }, "Loading Business Developers…"));
    try {
        const data = await api.get(API);
        state.rows = data.results || [];
        render();
    } catch (err) {
        host.textContent = "";
        host.appendChild(errorState(err.message || "Could not load Business Developers", load));
    }
}

/* ---------- Form helpers ---------- */

function clearErrors(form) {
    for (const node of form.querySelectorAll(".field-error")) node.textContent = "";
    for (const input of form.querySelectorAll("[aria-invalid]")) input.removeAttribute("aria-invalid");
    const top = form.querySelector(".form-error");
    if (top) top.textContent = "";
}

function showErrors(form, err) {
    const fields = fieldErrors(err && err.data);
    let first = null;
    for (const [name, message] of Object.entries(fields)) {
        const input = form.elements[name];
        const slot = form.querySelector(`[data-error-for="${name}"]`);
        if (input && slot) {
            slot.textContent = message;
            input.setAttribute("aria-invalid", "true");
            if (!first) first = input;
        }
    }
    if (first) {
        first.focus();
        return;
    }
    const top = form.querySelector(".form-error");
    if (top) top.textContent = (err && err.message) || "Something went wrong. Try again.";
}

function setBusy(form, busy) {
    const submit = form.querySelector('button[type="submit"]');
    if (submit) {
        submit.disabled = busy;
        submit.dataset.label = submit.dataset.label || submit.textContent;
        submit.textContent = busy ? "Saving…" : submit.dataset.label;
    }
}

function wireDialog(id) {
    const dlg = byId(id);
    for (const btn of dlg.querySelectorAll("[data-close]")) {
        btn.addEventListener("click", () => dlg.close());
    }
    dlg.addEventListener("click", (e) => {
        if (e.target === dlg) dlg.close();
    });
    return dlg;
}

function wirePasswordTools(form) {
    const input = form.elements.password;
    const gen = form.querySelector("[data-generate]");
    const show = form.querySelector("[data-show]");
    if (gen) {
        gen.addEventListener("click", () => {
            input.value = generatePassword(randomFill);
            input.type = "text";
            if (show) show.checked = true;
            input.focus();
            input.select();
        });
    }
    if (show) {
        show.addEventListener("change", () => {
            input.type = show.checked ? "text" : "password";
        });
    }
}

/* ---------- Add ---------- */

function openAdd() {
    const dlg = byId("dlg-add");
    const form = byId("form-add");
    form.reset();
    clearErrors(form);
    form.elements.password.type = "password";
    dlg.showModal();
    form.elements.first_name.focus();
}

async function submitAdd(e) {
    e.preventDefault();
    const form = e.currentTarget;
    clearErrors(form);
    setBusy(form, true);
    const body = {
        first_name: form.elements.first_name.value,
        last_name: form.elements.last_name.value,
        username: form.elements.username.value,
        email: form.elements.email.value,
        password: form.elements.password.value,
    };
    try {
        const created = await api.post(API, body);
        byId("dlg-add").close();
        toast(`${created.full_name} was added. Share the password with them securely.`, "success");
        await load();
    } catch (err) {
        showErrors(form, err);
    } finally {
        setBusy(form, false);
    }
}

/* ---------- Edit ---------- */

let editing = null;

function openEdit(row) {
    editing = row;
    const form = byId("form-edit");
    clearErrors(form);
    form.elements.first_name.value = row.first_name;
    form.elements.last_name.value = row.last_name;
    form.elements.email.value = row.email;
    byId("edit-username").textContent = `@${row.username}`;
    byId("dlg-edit").showModal();
    form.elements.first_name.focus();
}

async function submitEdit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    if (!editing) return;
    clearErrors(form);
    setBusy(form, true);
    try {
        await api.patch(`${API}${editing.id}/`, {
            first_name: form.elements.first_name.value,
            last_name: form.elements.last_name.value,
            email: form.elements.email.value,
        });
        byId("dlg-edit").close();
        toast("Details saved.", "success");
        await load();
    } catch (err) {
        showErrors(form, err);
    } finally {
        setBusy(form, false);
    }
}

/* ---------- Reset password ---------- */

let resetting = null;

function openPassword(row) {
    resetting = row;
    const form = byId("form-password");
    form.reset();
    clearErrors(form);
    form.elements.password.type = "password";
    byId("password-name").textContent = row.full_name;
    byId("dlg-password").showModal();
    form.elements.password.focus();
}

async function submitPassword(e) {
    e.preventDefault();
    const form = e.currentTarget;
    if (!resetting) return;
    clearErrors(form);
    setBusy(form, true);
    try {
        await api.post(`${API}${resetting.id}/reset-password/`, { password: form.elements.password.value });
        byId("dlg-password").close();
        toast("Password updated. Share it with them securely.", "success");
    } catch (err) {
        showErrors(form, err);
    } finally {
        setBusy(form, false);
    }
}

/* ---------- Activate / deactivate ---------- */

let toggling = null;

function confirmToggle(row) {
    toggling = row;
    const turningOff = row.is_active;
    byId("confirm-title").textContent = turningOff ? `Deactivate ${row.full_name}?` : `Activate ${row.full_name}?`;
    byId("confirm-text").textContent = turningOff
        ? "They will no longer be able to sign in. Their notes and stage changes stay on the leads."
        : "They will be able to sign in again.";
    const go = byId("confirm-go");
    go.textContent = turningOff ? "Deactivate" : "Activate";
    go.className = turningOff ? "btn btn-danger" : "btn btn-primary";
    byId("confirm-error").textContent = "";
    byId("dlg-confirm").showModal();
}

async function doToggle() {
    if (!toggling) return;
    const go = byId("confirm-go");
    go.disabled = true;
    try {
        await api.patch(`${API}${toggling.id}/`, { is_active: !toggling.is_active });
        byId("dlg-confirm").close();
        toast(toggling.is_active ? "Deactivated." : "Activated.", "success");
        await load();
    } catch (err) {
        byId("confirm-error").textContent = err.message || "Could not change the status.";
    } finally {
        go.disabled = false;
    }
}

/* ---------- Start ---------- */

onReady(async () => {
    registerGlobalErrorHandlers();
    try {
        for (const id of ["dlg-add", "dlg-edit", "dlg-password", "dlg-confirm"]) wireDialog(id);
        wirePasswordTools(byId("form-add"));
        wirePasswordTools(byId("form-password"));
        byId("btn-add-bd").addEventListener("click", openAdd);
        byId("form-add").addEventListener("submit", submitAdd);
        byId("form-edit").addEventListener("submit", submitEdit);
        byId("form-password").addEventListener("submit", submitPassword);
        byId("confirm-go").addEventListener("click", doToggle);

        let timer = null;
        byId("bd-search").addEventListener("input", (e) => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                state.filter.q = e.target.value;
                render();
            }, 200);
        });
        byId("bd-status").addEventListener("change", (e) => {
            state.filter.status = e.target.value;
            render();
        });
        await load();
    } catch (err) {
        renderPageCrash(byId("main") || document.body, "Business Developers page failed to start", err);
    }
});
