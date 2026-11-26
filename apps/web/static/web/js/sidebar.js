/**
 * apps/web/static/web/js/sidebar.js
 * Opens and closes the sidebar on small screens. No networking.
 */

import { onReady } from "./ui.js";

onReady(() => {
    const toggle = document.getElementById("sidebar-toggle");
    const scrim = document.getElementById("sidebar-scrim");
    if (!toggle) return;

    function setOpen(open) {
        document.body.classList.toggle("sidebar-open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
        if (scrim) scrim.hidden = !open;
    }

    toggle.addEventListener("click", () => setOpen(!document.body.classList.contains("sidebar-open")));
    if (scrim) scrim.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && document.body.classList.contains("sidebar-open")) {
            setOpen(false);
            toggle.focus();
        }
    });
});
