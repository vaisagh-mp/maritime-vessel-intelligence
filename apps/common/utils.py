"""Small shared helpers used by more than one domain app."""
from django.utils import timezone


def is_type_excluded(type_specific: str, exclusions) -> bool:
    """Case-insensitive substring blocklist check.

    Deliberately a blocklist, not an allowlist: unseen/new vessel type strings
    are NOT excluded by default, so the platform doesn't silently drop
    legitimate commercial vessel types that DataDocked introduces later.
    """
    if not type_specific:
        return False
    haystack = type_specific.lower()
    return any(term.lower() in haystack for term in exclusions)


def utcnow():
    return timezone.now()
