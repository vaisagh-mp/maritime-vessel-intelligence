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
export async function request(method, url, body = null) {
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

    const options = {
        method,
        headers,
        credentials: "same-origin",
    };

    if (body !== null && isNonGet) {
        options.body = typeof body === "string" ? body : JSON.stringify(body);
    }

    const response = await fetch(url, options);

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
    get: (url) => request("GET", url),
    post: (url, body) => request("POST", url, body),
    patch: (url, body) => request("PATCH", url, body),
};

