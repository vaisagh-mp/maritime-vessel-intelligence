/**
 * apps/web/static/web/js/ui.js
 * DOM manipulation, data formatters, badges, notification toasts, and shared error states.
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
 * Format error message with icon-free text prefix ("Error: ") if not already prefixed.
 * Pure function safe for both Node and browser runtimes.
 * @param {string|null|undefined} message
 * @returns {string}
 */
export function formatErrorMessage(message) {
    const raw = String(message || "An unexpected error occurred.").trim();
    if (raw.length === 0) {
        return "Error: An unexpected error occurred.";
    }
    return raw.toLowerCase().startsWith("error:") ? raw : `Error: ${raw}`;
}

/**
 * Render a reusable error-state DOM element with message and optional Retry button.
 * Formats message with icon-free text prefix ("Error: ") if not already prefixed.
 * @param {string} message - Error description text
 * @param {Function} [onRetry] - Optional retry callback function
 * @returns {HTMLElement}
 */
export function errorState(message, onRetry = null) {
    const formatted = formatErrorMessage(message);
    const errorSpan = el("span", { class: "error-text" }, formatted);
    const children = [errorSpan];

    if (typeof onRetry === "function") {
        const retryBtn = el(
            "button",
            {
                type: "button",
                class: "btn btn-sm btn-retry",
                onClick: (e) => {
                    e.preventDefault();
                    onRetry();
                },
            },
            "Retry"
        );
        children.push(retryBtn);
    }

    return el("div", { class: "error-state", role: "alert" }, ...children);
}

/**
 * Replace container children with the shared error-state element.
 * @param {HTMLElement} container
 * @param {string} message
 * @param {Function} [onRetry]
 */
export function renderError(container, message, onRetry = null) {
    if (!container) return;
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }
    container.appendChild(errorState(message, onRetry));
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
