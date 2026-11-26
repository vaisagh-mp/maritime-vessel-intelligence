#!/usr/bin/env python3
"""Kpler trial harness (Phase A). Standalone: no Django, no models, no pipelines.

Saves every RAW response untouched to
    data/kpler_trial/<UTC date>/<service>_<port>_<HHMM>.json
(envelope: request info with secrets redacted, status code, timing, raw body)
before any parsing. Never prints or logs an API key.

Usage (from the project root, where .env lives):
    python scripts/kpler_trial.py                    # all configured calls
    python scripts/kpler_trial.py --service expected # only Expected Arrivals
    python scripts/kpler_trial.py --service ais --port singapore
    python scripts/kpler_trial.py --dry-run          # show what would be called

Configuration comes from .env (see .env.kpler_trial.example).
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is in requirements.txt
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "data" / "kpler_trial"
LOG_FILE = OUT_ROOT / "trial.log"
TIMEOUT = 60
PORTS = ["singapore", "fujairah"]

log = logging.getLogger("kpler_trial")


def setup_logging():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def env(name, default=""):
    return (os.getenv(name) or default).strip()


def redact(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def save(service, port, now, envelope):
    day_dir = OUT_ROOT / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{service}_{port}_{now.strftime('%H%M')}.json"
    n = 1
    while path.exists():  # never overwrite a saved response
        n += 1
        path = day_dir / f"{service}_{port}_{now.strftime('%H%M')}_{n}.json"
    path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def do_call(service, port, method, url_for_log, request_kwargs, secrets, dry_run):
    """Make one call, save the raw result whatever happens. Returns True on HTTP 2xx."""
    now = datetime.now(timezone.utc)
    if dry_run:
        log.info("[dry-run] %s %s -> %s", service, port, url_for_log)
        return True
    envelope = {
        "service": service, "port": port, "requested_at_utc": now.isoformat(),
        "method": method, "url": url_for_log,
        "params": request_kwargs.get("params"),
    }
    start = time.monotonic()
    try:
        resp = requests.request(method, timeout=TIMEOUT, **request_kwargs)
        envelope.update(
            status_code=resp.status_code,
            elapsed_seconds=round(time.monotonic() - start, 3),
            response_headers={k: v for k, v in resp.headers.items()
                              if k.lower() in ("content-type", "content-length", "date", "retry-after")},
            body_text=redact(resp.text, secrets),  # raw body, untouched except key redaction
        )
        try:
            envelope["body_json_valid"] = bool(resp.json() is not None)
        except ValueError:
            envelope["body_json_valid"] = False
        ok = resp.ok
        if not ok:
            log.warning("%s/%s HTTP %s: %s", service, port, resp.status_code, redact(resp.text[:200], secrets))
        elif not resp.text.strip():
            log.warning("%s/%s: empty body", service, port)
        elif not envelope["body_json_valid"]:
            log.warning("%s/%s: non-JSON body", service, port)
    except requests.RequestException as exc:
        envelope.update(status_code=None, elapsed_seconds=round(time.monotonic() - start, 3),
                        error=redact(f"{type(exc).__name__}: {exc}", secrets))
        log.error("%s/%s request failed: %s", service, port, envelope["error"])
        ok = False
    path = save(service, port, now, envelope)
    log.info("%s/%s -> status=%s %.1fs saved %s", service, port,
             envelope.get("status_code"), envelope.get("elapsed_seconds", 0), path.relative_to(ROOT))
    return ok


def run_expected(port, dry_run):
    key = env("MARINETRAFFIC_API_KEY")
    portid = env(f"KPLER_EXPECTED_PORTID_{port.upper()}")
    base = env("MARINETRAFFIC_BASE_URL", "https://services.marinetraffic.com/api")
    if not key or not portid:
        log.warning("expected/%s skipped: MARINETRAFFIC_API_KEY or KPLER_EXPECTED_PORTID_%s not set",
                    port, port.upper())
        return None
    # api_key is a URL PATH segment for this API.
    url = f"{base.rstrip('/')}/expectedarrivals/{key}"
    params = {"v": "4", "portid": portid, "msgtype": "extended", "protocol": "jsono"}
    shown = f"{base.rstrip('/')}/expectedarrivals/***"
    return do_call("expected", port, "GET", shown, {"url": url, "params": params}, [key], dry_run)


def run_ais(port, dry_run):
    """AIS Latest: format is UNKNOWN until taken from the Kpler portal, so nothing is
    hard-coded. URL, method, auth header and parameters all come from .env."""
    key = env("KPLER_API_KEY")
    url = env(f"KPLER_AIS_URL_{port.upper()}") or env("KPLER_AIS_URL")
    if not key or not url:
        log.warning("ais/%s skipped: KPLER_API_KEY or KPLER_AIS_URL(_%s) not set", port, port.upper())
        return None
    method = env("KPLER_AIS_METHOD", "GET").upper()
    header = env("KPLER_AIS_AUTH_HEADER", "Authorization")
    scheme = env("KPLER_AIS_AUTH_SCHEME", "Bearer")  # set empty for a raw key
    headers = {header: f"{scheme} {key}".strip(), "Accept": "application/json"}
    raw = env(f"KPLER_AIS_PARAMS_JSON_{port.upper()}") or env("KPLER_AIS_PARAMS_JSON")
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        log.error("ais/%s skipped: KPLER_AIS_PARAMS_JSON(_%s) is not valid JSON", port, port.upper())
        return None
    kwargs = {"url": url, "headers": headers}
    kwargs["params" if method == "GET" else "json"] = payload
    return do_call("ais", port, method, url, kwargs, [key], dry_run)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--service", choices=["expected", "ais", "all"], default="all")
    ap.add_argument("--port", choices=PORTS + ["all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    setup_logging()
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    ports = PORTS if args.port == "all" else [args.port]
    results = []
    for port in ports:
        if args.service in ("expected", "all"):
            results.append(("expected", port, run_expected(port, args.dry_run)))
        if args.service in ("ais", "all"):
            results.append(("ais", port, run_ais(port, args.dry_run)))
    for svc, port, r in results:
        print(f"{svc:9s}{port:10s}{'SKIPPED (not configured)' if r is None else ('ok' if r else 'FAILED')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
