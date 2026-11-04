/**
 * apps/web/static/web/js/home.js
 * Home page verification script: probes the opportunities API endpoint.
 */

import { api } from "./api.js";
import { toast } from "./ui.js";

async function checkApi() {
    const statusEl = document.getElementById("api-status");
    if (!statusEl) {
        return;
    }

    try {
        const data = await api.get("/api/v1/opportunities/?ordering=-score");
        const count = data && typeof data.count === "number"
            ? data.count
            : (data && Array.isArray(data.results) ? data.results.length : 0);

        statusEl.textContent = `Connected. Open opportunities: ${count}`;
    } catch (err) {
        const errorDetail = err.detail || err.message || "Unknown error";
        statusEl.textContent = `Could not reach the API: ${errorDetail}`;
        toast(`Could not reach the API: ${errorDetail}`, "error");
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", checkApi);
} else {
    checkApi();
}

