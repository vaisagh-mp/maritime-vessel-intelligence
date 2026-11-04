# Vessel Arrival Intelligence — Phase 1 Backend

> **Status: DataDocked removed; the Kpler integration is under construction, so no data is fetched until it lands.**

Django + DRF + PostgreSQL backend for detecting vessels approaching configured
service ports, resolving vessel-to-company relationships, and tracking the
resulting opportunities through a CRM-style lifecycle.

Scope: **vessel discovery, identity enrichment, and the data layer only.**
Scoring engine, AI outreach, WhatsApp/email sending, human contact-name
resolution, and the frontend are Phase 3+ and are intentionally not built here.

## Architecture

```
apps/            Domain modules (ports, vessels, companies, relationships,
                  observations, opportunities, enrichment) — models, admin,
                  DRF serializers/views/urls, tests.
integrations/     External providers, isolated from Django views/models.
                  (the data provider (Kpler, added in Steps 4 to 6) will live here)
services/        Cross-domain business logic (the actual workflows):
    vessel_service.py        vessel upsert + type-exclusion filter
    observation_service.py   append-only observation writer
    opportunity_service.py   dedup + zone classification
    company_service.py       case-insensitive company matching + relationships
    enrichment_service.py    orchestrates enrichment, logs to EnrichmentLog
tasks/           Scheduled/cron-runnable work.
utils/           Small shared technical helpers.
config/          Django settings, URL root, WSGI/ASGI.
```

Request flow: **DRF View → Serializer → Service layer → PostgreSQL /
Integration layer → the data provider (Kpler, added in Steps 4 to 6).** Views never talk to
the data provider directly or contain business logic directly.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in DB credentials
# Without DB_NAME set, settings.py falls back to sqlite for quick local runs.

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Running discovery

```bash
# Enrich one vessel manually:
python manage.py enrich_vessel <vessel_id>
# or: POST /api/v1/vessels/{id}/enrich/
```

Celery/Redis (`apps/enrichment/tasks.py`, `REDIS_URL` in `.env`) can be wired
in later as the async execution layer for both discovery and enrichment
without changing any service-layer code.

## API

All endpoints are under `/api/v1/`:

| Resource | Methods |
|---|---|
| `ports/` | full CRUD (admin-managed) |
| `companies/` | full CRUD (admin-managed) |
| `vessels/` | read-only + `GET /vessels/{id}/observations/`, `POST /vessels/{id}/enrich/` |
| `observations/` | read-only |
| `opportunities/` | read-only + `PATCH /opportunities/{id}/` (stage only) |
| `enrichment/` | read-only (EnrichmentLog) |

## Tests

```bash
python manage.py test
```

Covers: dedup (no duplicate open Opportunity per vessel+port across repeated
polls), zone classification at boundary values (proximity and ETA-based),
type-exclusion blocklist behavior including unknown-type inclusion, and
Opportunity PATCH-only stage editing.

## Key design decisions (from the project plan)

- **MMSI is the discovery dedup key** — the area-scan endpoint doesn't return IMO.
- **Type exclusion is a blocklist, not an allowlist** — new/unseen vessel
  types are included by default rather than silently dropped.
- **Enrichment is never triggered inside the discovery loop** — it runs on
  its own trigger (new qualifying vessel, or a manual flag) so one discovery
  batch can't fire hundreds of paid calls at once.
- **VesselObservation is append-only** — every poll inserts, never updates.
- **Registry-derived company relationships are `verified=False`** — data
  from the provider is public registry data, not a human-confirmed contact, and
  must never be treated as equivalent to a verified decision-maker later in
  the pipeline.
- **Every enrichment call is logged** (success or failure) to `EnrichmentLog`
  for auditable credit spend.
