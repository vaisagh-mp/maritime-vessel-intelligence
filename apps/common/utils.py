"""Small shared helpers used by more than one domain app."""
from django.utils import timezone


def is_type_excluded(type_specific: str, exclusions) -> bool:
    """Case-insensitive substring blocklist check.

    Deliberately a blocklist, not an allowlist: unseen/new vessel type strings
    are NOT excluded by default, so the platform doesn't silently drop
    legitimate commercial vessel types that the data provider introduces later.
    """
    if not type_specific:
        return False
    haystack = type_specific.lower()
    return any(term.lower() in haystack for term in exclusions)


def utcnow():
    return timezone.now()


def normalize_imo(value):
    """Returns a clean IMO string, or None when the value means "no IMO".

    Providers use several placeholders for a missing IMO: ``None``, ``""``,
    ``"0"`` and all-zero strings. All of them become ``None`` so a
    placeholder is never stored or used as a lookup key. Numeric input (Kpler
    returns integers) is converted to ``str``.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("null", "none", "-") or set(text) == {"0"}:
        return None
    return text
