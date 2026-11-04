/**
 * apps/web/static/web/js/ui.js
 * DOM manipulation, data formatters, badges, and notification toasts.
 * Strictly uses safe DOM methods (createElement / textContent); avoids raw HTML sinks.
 */

const EM_DASH = "\u2014";

/**
 * Safe DOM element factory.
 * @param {string} tag
 * @param {Object} [attrs]
 * @param {...(Node|string|number)} children
 * @returns {HTMLElement}
 */
export function el(tag, attrs = {}, ...children) {
    const element = document.createElement(tag);

    if (attrs) {
        for (const [key, value] of Object.entries(attrs)) {
            if (value === null || value === undefined) {
                continue;
            }
            if (key === "className" || key === "class") {
                element.className = value;
            } else if (key.startsWith("on") && typeof value === "function") {
                const eventName = key.substring(2).toLowerCase();
                element.addEventListener(eventName, value);
            } else if (key.startsWith("data-") || key.startsWith("aria-")) {
                element.setAttribute(key, value);
            } else if (key in element) {
                try {
                    element[key] = value;
                } catch {
                    element.setAttribute(key, value);
                }
            } else {
                element.setAttribute(key, value);
            }
        }
    }

    for (const child of children) {
        if (child === null || child === undefined) {
            continue;
        }
        if (child instanceof Node) {
            element.appendChild(child);
        } else {
            element.appendChild(document.createTextNode(String(child)));
        }
    }

    return element;
}

/**
 * Return formatted UTC datetime string e.g. "2026-11-05 14:00 UTC" or em dash.
 */
export function formatUtc(isoString) {
    if (!isoString) {
        return EM_DASH;
    }
    const d = new Date(isoString);
    if (isNaN(d.getTime())) {
        return EM_DASH;
    }
    const year = d.getUTCFullYear();
    const month = String(d.getUTCMonth() + 1).padStart(2, "0");
    const day = String(d.getUTCDate()).padStart(2, "0");
    const hours = String(d.getUTCHours()).padStart(2, "0");
    const minutes = String(d.getUTCMinutes()).padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
}

/**
 * Format numbers with thousands separators or em dash if null/undefined.
 */
export function formatNumber(n) {
    if (n === null || n === undefined || isNaN(Number(n))) {
        return EM_DASH;
    }
    return Number(n).toLocaleString("en-US");
}

/**
 * Fallback to em dash if value is null, undefined, or empty string.
 */
export function dash(value) {
    if (value === null || value === undefined || value === "") {
        return EM_DASH;
    }
    return String(value);
}

/**
 * Render a score band badge element.
 * Color is accompanied by band word text.
 */
export function bandBadge(bandName) {
    const raw = String(bandName || "").toUpperCase();
    const normalized = ["HOT", "HIGH", "MEDIUM", "LOW"].includes(raw) ? raw : "LOW";
    const modifierClass = `badge-${normalized.toLowerCase()}`;
    return el("span", { class: `badge ${modifierClass}` }, normalized);
}

/**
 * Display a self-dismissing toast notification.
 */
export function toast(message, kind = "info") {
    const container = document.getElementById("toast-region");
    if (!container) {
        return;
    }

    const toastClass = kind === "error" ? "toast toast-error" : (kind === "success" ? "toast toast-success" : "toast");
    const toastElement = el("div", { class: toastClass, role: "status" }, message);

    container.appendChild(toastElement);

    setTimeout(() => {
        if (toastElement.parentNode === container) {
            container.removeChild(toastElement);
        }
    }, 5000);
}

