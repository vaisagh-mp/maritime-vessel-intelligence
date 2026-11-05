"""
apps/web/middleware.py
Content Security Policy middleware for vessel_intel web application.
"""

from django.conf import settings

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class ContentSecurityPolicyMiddleware:
    """Applies Content Security Policy to HTML responses, excluding admin and API JSON."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        mode = getattr(settings, "WEB_CSP_MODE", "enforce")
        if mode == "off":
            return response

        # Do not apply to Django admin
        if request.path_info.startswith("/admin/"):
            return response

        # Do not apply to /api/ or JSON responses
        content_type = response.get("Content-Type", "")
        if request.path_info.startswith("/api/") or "application/json" in content_type:
            return response

        header_name = (
            "Content-Security-Policy-Report-Only"
            if mode == "report-only"
            else "Content-Security-Policy"
        )
        response[header_name] = CSP_POLICY
        return response

