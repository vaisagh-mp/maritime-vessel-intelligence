/**
 * apps/web/static/web/js/api.js
 * Centralized HTTP client for the Vessel Intelligence API.
 * The ONLY place in the frontend that calls fetch().
 */

export class ApiError extends Error {
    constructor(message, status, detail = null) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
    }
}

/**
 * Safely extract cookie value by name.
 */
export function getCookie(name) {
    if (!document.cookie) {
        return null;
    }
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + "=")) {
            return decodeURIComponent(cookie.substring(name.length + 1));
        }
    }
    return null;
}

/**
 * Perform an authenticated API request using session cookies and CSRF protection.
 */
export async function request(method, url, body = null, timeoutMs = 20000) {
    const headers = {
        "Accept": "application/json",
    };

    const isNonGet = method.toUpperCase() !== "GET" && method.toUpperCase() !== "HEAD";
    if (isNonGet) {
        headers["Content-Type"] = "application/json";
        const csrfToken = getCookie("csrftoken");
        if (csrfToken) {
            headers["X-CSRFToken"] = csrfToken;
        }
    }

    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = controller && timeoutMs > 0 ? setTimeout(() => {
        controller.abort();
    }, timeoutMs) : null;

    const options = {
        method,
        headers,
        credentials: "same-origin",
    };

    if (controller) {
        options.signal = controller.signal;
    }

    if (body !== null && isNonGet) {
        options.body = typeof body === "string" ? body : JSON.stringify(body);
    }

    let response;
    try {
        response = await fetch(url, options);
    } catch (err) {
        if (controller && controller.signal.aborted) {
            throw new ApiError(
                "Request timed out. Please retry.",
                408,
                "The server took too long to respond (20s)."
            );
        }
        throw err;
    } finally {
        if (timer) clearTimeout(timer);
    }

    if (response.status === 401 || response.status === 403) {
        const nextPath = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login/?next=${nextPath}`;
        throw new ApiError(
            `Authentication required (${response.status})`,
            response.status,
            "Session expired or unauthorized"
        );
    }

    if (response.status === 204) {
        return null;
    }

    let data = null;
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
        try {
            data = await response.json();
        } catch {
            data = null;
        }
    }

    if (!response.ok) {
        let detailText = null;
        if (data) {
            if (typeof data.detail === "string") {
                detailText = data.detail;
            } else if (Array.isArray(data.detail)) {
                detailText = data.detail.join(", ");
            } else if (typeof data.message === "string") {
                detailText = data.message;
            } else if (typeof data === "object") {
                // If validation error object e.g. { field: ["error"] }
                const firstKey = Object.keys(data)[0];
                if (firstKey) {
                    const val = data[firstKey];
                    detailText = Array.isArray(val) ? `${firstKey}: ${val.join(", ")}` : `${firstKey}: ${val}`;
                }
            }
        }
        const message = detailText || response.statusText || `HTTP ${response.status}`;
        throw new ApiError(message, response.status, detailText);
    }

    return data;
}

export const api = {
    get: (url, timeoutMs = 20000) => request("GET", url, null, timeoutMs),
    post: (url, body, timeoutMs = 20000) => request("POST", url, body, timeoutMs),
    patch: (url, body, timeoutMs = 20000) => request("PATCH", url, body, timeoutMs),
};

