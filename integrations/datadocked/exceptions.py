class DataDockedError(Exception):
    """Base exception for the DataDocked integration layer."""

    def __init__(self, message, endpoint=None, status_code=None):
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code


class DataDockedRequestError(DataDockedError):
    """Raised for network-level failures (timeout, connection error)."""


class DataDockedResponseError(DataDockedError):
    """Raised when DataDocked returns a non-2xx status or an unparseable body."""
