# Vessel Intelligence (Splendour)

Django + Django REST Framework app that finds vessels inbound to or at
**Singapore (SGSIN)** and **Fujairah (AEFJR)**, identifies their owners and
managers, scores each vessel as a lead, and tracks leads through a BD pipeline.

Outreach is **not built**. Any message to a company must be approved by a person.

## Data sources

| Source | Used for | Setting |
|---|---|---|
| MarineTraffic Expected Arrivals | 24 h and 72 h columns (1 call per 2 minutes) | `MARINETRAFFIC_API_KEY` |
| Kpler AIS Latest | Anchorage column and position updates, by area filter | `KPLER_AIS_API_KEY` (falls back to `KPLER_API_KEY`) |
| Kpler Vessels (GraphQL) | Particulars, owners and managers | `KPLER_API_KEY` |

Keys live only in `.env`. They are never logged or written to files.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
# create .env with the keys above (see "Settings" below)
python manage.py migrate
python manage.py setup_roles
python manage.py setup_pilot_ports
python manage.py createsuperuser
python manage.py runserver
```

Without `DB_NAME` the app uses SQLite. Set `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
`DB_HOST`, `DB_PORT` to use PostgreSQL.

Each port needs an AIS area. Paste the filter Kpler gives you into the port's
`ais_filter` (Django admin, Ports), for example
`BBOX(position, minLon, minLat, maxLon, maxLat)` (longitude first).

## Using it

Open `http://127.0.0.1:8000/`, sign in, and use the lead board.

- **Refresh data (live)** fetches the selected port in three steps: Expected
  Arrivals, then AIS Latest for the anchorage, then (only when
  `KPLER_OWNERSHIP_ENABLED` is true) an owner and manager lookup from Kpler for
  that port's best unchecked leads. One port per click, 2 minute cooldown.
  A failure in the AIS or owner step never fails the run.
  Choose a port in the Port filter first. **Reload** only re-reads the database.
- Columns: 24 hour priority, 72 hour approach, Anchorage / port.
- Roles: admin and BD manager can refresh; others can read.

## Commands

```bash
# Arrivals (MarineTraffic). Add --dry-run to roll back.
python manage.py ingest_expected_arrivals --mode arrivals --port SGSIN --live

# Anchorage and positions (Kpler AIS Latest). Always dry-run first.
python manage.py ingest_ais_latest --port SGSIN --live --dry-run
python manage.py ingest_ais_latest --port SGSIN --live
python manage.py ingest_ais_latest --port SGSIN --from-file data/kpler/kpler_ais/<saved>.json

# Owners and managers (needs Kpler ownership access on the key)
python manage.py enrich_ownership --from-file <file>

# Recompute scores
python manage.py rescore_opportunities --dry-run

# Cleanup (all dry-run unless --apply)
python manage.py purge_ais_small_craft         # AIS vessels with unknown size, no human work
python manage.py purge_placeholder_vessels     # unused MMSI-99 vessels (buoys, placeholders)
python manage.py purge_fake_fixture_data       # old invented test data
```

### Rules the AIS ingest follows

- A new vessel is created only if it is at anchor **and** its gross tonnage is
  known and between `EXPECTED_ARRIVALS_GT_MIN` and `EXPECTED_ARRIVALS_GT_MAX`.
- Known vessels get new positions but keep their name, flag and type.
- At anchor means navStatus 1, or speed at or below `AIS_ANCHORAGE_MAX_SOG`.
  Moored means navStatus 5. Positions older than `AIS_MAX_POSITION_AGE_HOURS`
  are rejected.
- A lead is created or updated only for anchored vessels with a known size.
- The raw provider response is saved under `data/kpler/` for audit.

## API

All under `/api/v1/`, session or JWT login required.

| Resource | Methods |
|---|---|
| `ports/`, `companies/` | CRUD (admin) |
| `vessels/`, `observations/`, `enrichment/` | read-only |
| `opportunities/` | read, `PATCH` stage, notes, history, CSV export |
| `relationships/` | read |
| `ingest/refresh/` | `POST {"port": "SGSIN"}`: 202 started, 400 invalid port, 409 already running, 429 cooldown (Retry-After), 503 disabled or not configured |
| `ingest/status/`, `ingest/runs/<id>/` | read |

## Settings (environment variables)

`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, database variables above,
`MARINETRAFFIC_API_KEY`, `KPLER_API_KEY`, `KPLER_AIS_API_KEY`, `KPLER_AIS_URL`
(leave unset to use the default), `KPLER_OWNERSHIP_ENABLED`,
`KPLER_OWNERSHIP_MONTHLY_IMO_CAP`, `INGEST_REFRESH_ENABLED`,
`INGEST_REFRESH_COOLDOWN_SECONDS` (120), `INGEST_REFRESH_AIS_ENABLED`,
`INGEST_REFRESH_OWNERSHIP_ENABLED` (True) and `INGEST_REFRESH_OWNERSHIP_MAX_IMOS`
(20 vessels per click, also limited by `KPLER_OWNERSHIP_MONTHLY_IMO_CAP`), `AIS_ANCHORAGE_MAX_SOG` (1.0),
`AIS_MAX_POSITION_AGE_HOURS` (24), `AIS_LATEST_LIMIT`,
`EXPECTED_ARRIVALS_GT_MIN` (3000), `EXPECTED_ARRIVALS_GT_MAX` (500000).

The session and CSRF cookies are named `vi_sessionid` and `vi_csrftoken` so that
other local Django apps on 127.0.0.1 do not log this one out.

## Tests

```bash
python manage.py test
```

No test makes a real network call. A guard fails any test that tries.

## Design decisions

- **MMSI is the dedup key** for vessels; IMO is filled in by enrichment.
- **Observations are append-only**: every poll inserts a row, never updates.
- **Registry ownership is `verified=False`**: public data is not a confirmed
  decision-maker.
- **Provider calls are never retried** and are logged without keys.
- **`services/` must not import `integrations/`** (enforced by a test).

## Daily sync and provider limits

`python manage.py daily_sync` is meant to run once a day (02:00 UTC). On Windows, point Task Scheduler at `scripts\daily_sync.bat` (it writes `logs\daily_sync.log`). Use `--dry-run` to see the plan without any call.

* MarineTraffic arrivals: one extended call per port (SGSIN, AEFJR) per day. A port fetched in the last 23 hours is skipped, and the Refresh button obeys the same rule. A 429 is retried once.
* Kpler owners and managers: 480 IMOs per period (`KPLER_OWNERSHIP_MONTHLY_IMO_CAP`, period starts on `KPLER_QUOTA_RESET_DAY`, default 1). Spending is paced evenly with carry-over. `OWNERSHIP_MANUAL_DAILY_RESERVE` (4) of each day's share is kept for the "Look up owner" button on the vessel page.
* Order of lookups: 24h, 72h, anchorage-bound, anchorage; then score; then size (GRT). LOW leads and stale ETAs are skipped. A vessel is re-checked after `OWNERSHIP_RECHECK_DAYS` (180).
* The dashboard "Data freshness" panel shows the allowances. No migration is needed for this feature.

## Send mail to owners and managers

On a vessel page, each owner or manager with an email address has a "Send mail" button. It opens a dialog with a template picker, the filled-in subject and message (editable), and the warnings. Nothing is sent until a person presses Send, and one mail goes to one company at a time.

* Templates: the **Email templates** page in the sidebar (Admin and BD Manager). Add, edit or switch off a template; press a placeholder chip to insert it. Placeholders: `{{company_name}}`, `{{vessel_name}}`, `{{imo}}`, `{{vessel_type}}`, `{{grt}}`, `{{flag}}`, `{{port}}`, `{{eta}}`, `{{role}}`, `{{sender_name}}`, `{{sender_first_name}}`. Two starter templates (72 hour first contact, 24 hour reminder) are created by the migration.
* Mail server (SMTP): add the lines below to `.env`, restart the server, then run `python manage.py check_mail --to your@address.com`. It shows the settings (never the password), tests the login and sends one test mail. With no `EMAIL_HOST` the app stays in test mode: mails are printed in the server window and the page says "test mode, not delivered".

  Gmail / Google Workspace (create an app password at myaccount.google.com/apppasswords; two-step verification must be on):

  ```
  EMAIL_HOST=smtp.gmail.com
  EMAIL_PORT=587
  EMAIL_USE_TLS=True
  EMAIL_HOST_USER=you@yourcompany.com
  EMAIL_HOST_PASSWORD=<16 character app password>
  DEFAULT_FROM_EMAIL=Splendour <you@yourcompany.com>
  ```

  Microsoft 365 (SMTP AUTH must be allowed for the mailbox by your admin):

  ```
  EMAIL_HOST=smtp.office365.com
  EMAIL_PORT=587
  EMAIL_USE_TLS=True
  EMAIL_HOST_USER=you@yourcompany.com
  EMAIL_HOST_PASSWORD=<mailbox password or app password>
  DEFAULT_FROM_EMAIL=Splendour <you@yourcompany.com>
  ```

  Another provider: use its SMTP host and port. For port 465 set `EMAIL_USE_SSL=True` and `EMAIL_USE_TLS=False`. `EMAIL_TIMEOUT` (20 seconds) stops a slow server freezing the page. Mails go out from `DEFAULT_FROM_EMAIL`, and replies go to the person who pressed Send.
* Safe testing: set `OUTREACH_TEST_RECIPIENT=your.test@gmail.com` and every mail is delivered to that address instead of the company (subject starts with "[TEST for company@address]", the dialog shows a "Safe test" banner, the log records the test address, no hidden copy is sent). Remove the line to go live.
* Other settings: `OUTREACH_ENABLED` (True), `OUTREACH_BCC` (hidden copy to a shared mailbox), `OUTREACH_RESEND_BLOCK_DAYS` (3, asks for confirmation when the same company was already mailed about the same vessel), `OUTREACH_DAILY_LIMIT_PER_USER` (50).
* Every mail is recorded and listed on the **Email log** page in the sidebar. The vessel page shows "Last mailed <date> by <person>" under the contact.
