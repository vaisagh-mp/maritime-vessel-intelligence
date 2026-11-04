"""Filesystem raw response storage for Kpler and MarineTraffic payloads."""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("vessel_intel")


def save_raw_response(service: str, label: str, payload) -> Path:
    """Saves a JSON payload in a structured envelope under KPLER_RAW_DIR/<service>/.

    Envelope: {"service": service, "label": label, "saved_at": iso_utc, "payload": payload}
    Never stores request URLs or secrets.
    Returns the Path to the written file.
    """
    raw_dir_setting = getattr(settings, "KPLER_RAW_DIR", None)
    if not raw_dir_setting:
        base_dir = getattr(settings, "BASE_DIR", Path(".")) / "data" / "kpler"
    else:
        base_dir = Path(raw_dir_setting)

    target_dir = base_dir / service
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp_str}_{label}.json"
    file_path = target_dir / filename

    envelope = {
        "service": service,
        "label": label,
        "saved_at": now.isoformat(),
        "payload": payload,
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)

    return file_path
