"""Exceptions for Kpler and MarineTraffic client interactions."""


class KplerError(Exception):
    """Base exception for all Kpler and MarineTraffic client errors."""

    def __init__(self, message, endpoint=None, status_code=None, provider_code=None):
        super().__init__(message)
        self.message = message
        self.endpoint = endpoint
        self.status_code = status_code
        self.provider_code = provider_code

    def __str__(self):
        parts = [self.message]
        if self.endpoint:
            parts.append(f"endpoint={self.endpoint}")
        if self.status_code is not None:
            parts.append(f"status_code={self.status_code}")
        if self.provider_code is not None:
            parts.append(f"provider_code={self.provider_code}")
        return " | ".join(parts)


class CallLimitError(KplerError):
    """MarineTraffic error code 5 ('ABOVE SERVICE CALL LIMIT') or HTTP 429."""


class KplerAccessError(KplerError):
    """Vessels particulars and ownership are not enabled for this key (FORBIDDEN / 403 / access-denied)."""


class ParameterError(KplerError):
    """Missing or invalid parameter (e.g. MarineTraffic 2a12, 1o, or GraphQL validation failure)."""


class ServiceNotInContractError(KplerError):
    """MarineTraffic error code 12 ('SERVICE KEY DOES NOT MATCH SERVICE TYPE')."""


class NotEntitledError(KplerError):
    """GraphQL FORBIDDEN or HTTP 403. Carries the field name (e.g. 'management')."""

    def __init__(self, message, field=None, endpoint=None, status_code=None, provider_code=None):
        super().__init__(message, endpoint=endpoint, status_code=status_code, provider_code=provider_code)
        self.field = field

    def __str__(self):
        base = super().__str__()
        if self.field:
            return f"{base} | field={self.field}"
        return base


class AuthenticationError(KplerError):
    """HTTP 401 Unauthorized."""


class ProviderRequestError(KplerError):
    """Timeouts, network errors, HTTP 5xx, unparsable bodies, or other unexpected provider errors."""
