# Prompt for Antigravity: Vessel Arrival Intelligence, Phase B (Kpler as primary provider)

You are working in an existing Django project at `G:\Vessel Arrival BD Tracker\vessel_intel_phase1\vessel_intel`. Read this whole prompt before changing anything. **Verify every claim here against the actual code. If the code differs, trust the code and report the difference.**

## 1. Purpose of the project

A business-development platform for Splendour, a marine company selling underwater vessel services (hull cleaning, inspection). It:

1. Detects vessels arriving at, or already waiting at, Splendour's pilot ports: **Singapore (SGSIN) and Fujairah (AEFJR)**.
2. Identifies the owner and manager companies and their contact details (email, website).
3. Scores each lead.
4. Lets the BD team work leads through a pipeline (detected, contacted, quoted, won or lost).

Outreach automation is not built. When it is, a human approves every message. Registry data is never a verified contact: `VesselRelationship.verified` stays `False` for all provider data.

## 2. Decision already made

The project is **switching from DataDocked to Kpler**. DataDocked code is **kept**, behind provider toggles that can be set back to `"datadocked"` for rollback. Do not delete any DataDocked client, parser, task or test. The default provider values flip to `"kpler"` only in the final cutover step (Step B7), and only if the user confirms.

## 3. Stack and rules

- Django 5.0, DRF, SQLite fallback when `DB_NAME` is unset (Postgres in production), `requests`, `python-dotenv`. No Celery. Work runs through management commands.
- Layout: `apps/` (ports, vessels, companies, relationships, observations, opportunities, enrichment, common), `integrations/datadocked/`, `services/`, `tasks/`, `config/`. Tables are prefixed `vi_`.
- **Secrets only in `.env`** (git-ignored). Never put keys in code, tests, logs, commits or chat. Never print a key.
- **Parsers return plain dicts. `services/` must never know which provider produced them.**
- One logical change at a time. Show every migration to the user before applying it. Run the full test suite after each change. Baseline right now: 126 tests pass.
- Do not build parsers from documentation examples. Documentation samples for these APIs have been stale (2017 to 2021 timestamps, Piraeus) and have already misled this project once. Parsers are built from **saved real trial responses** in `data/kpler_trial/<UTC date>/` (see Section 6).
- Ask the user before deciding anything in Section 9.

## 4. Current state (already done, do not redo)

- `apps/common/utils.py`: `normalize_imo(value)` returns `None` for `None`, `""`, `"0"`, all-zero strings, `"null"`, `"none"`, `"-"`; converts numbers to `str`. `Vessel.save()` applies it. `enrich_vessel` uses it.
- Management command `setup_pilot_ports` (dry run by default, `--apply` to write): fixes Port Rashid `AEPRA` to `AEDXB`, keeps only SGSIN and AEFJR active, NULLs placeholder IMOs, lists MMSI-`99*` junk without deleting. The user runs this against the live database.
- `scripts/kpler_trial.py`: a standalone trial harness. It saves raw Kpler responses to `data/kpler_trial/<UTC date>/<service>_<port>_<HHMM>.json`. Each file is an envelope with `service`, `port`, `requested_at_utc`, `method`, `url` (key redacted), `params`, `status_code`, `elapsed_seconds`, `response_headers`, `body_text` (the raw body as a string) and `body_json_valid`. It is not wired into any pipeline. `/data/` is git-ignored.

## 5. Existing architecture you must preserve

**Models:** `Port` (`un_locode` unique, `latitude`, `longitude`, `anchorage_latitude`, `anchorage_longitude`, `geofence_radius_km`, `active`), `Vessel` (`imo` nullable, `mmsi` unique, `name`, `vessel_type`, `dwt`), `Company` (`name`, `company_type`, `priority`, `email`, `website`, `address`), `VesselRelationship` (`role` in owner, manager, operator; `source`; `verified`; unique on vessel, company, role), `VesselObservation` (append-only; `save()` raises if pk is set; fields `timestamp`, `latitude`, `longitude`, `speed`, `course`, `source` defaulting to `"datadocked.com"`), `Opportunity` (stage, zone 72h/24h/anchorage, score, eta), `EnrichmentLog` (`endpoint_called`, `success`, `credits_spent`, `error_message`, nullable vessel and port).

**Services** (provider-agnostic, keep it that way): `services/vessel_service.get_or_create_vessel(raw)` reads `mmsi`, `name`, `typeSpecific`, `speed`; `observation_service.record_observation`; `opportunity_service.get_or_create_open_opportunity`, `classify_zone_by_eta`, `update_opportunity_eta`; `company_service.apply_management_data`; `scoring_service.calculate_score` (its `_score_priority_manager` filters `role="manager"` only, line ~119); `enrichment_service.enrich_vessel`.

**Normalised dict shapes the services and tasks already consume** (Kpler parsers must produce these):

- Area-scan record: `mmsi`, `name`, `typeSpecific`, `speed`, `course`, `latitude`, `longitude`.
- Expected-arrival record (list of): `mmsi` (str), `name`, `imo`, `type`, `year`, `country`, `gt`, `dw`, `sizes`, `eta` (aware datetime or None).
- Location result: `imo`, `mmsi`, `name`, `eta`, `destination`, `latitude`, `longitude`, `navigational_status`.
- Management result: `manager_*` and `registered_owner_*` (name, email, website, address).

**Tasks:** `tasks/discovery.py` (area scan, `run_discovery`), `tasks/expected_arrivals.py` (`run_expected_arrivals`; creates no observation because DataDocked has no position; logs one `EnrichmentLog` row per page with `vessel=None`). Both return a stats dict. Read them and mirror their structure.

## 6. What is known about the Kpler APIs (from the official docs, not yet from real responses)

### 6.1 Expected Arrivals (MarineTraffic REST)

```
GET https://services.marinetraffic.com/api/expectedarrivals/{api_key}
    ?v=4&portid=<MarineTraffic numeric port id>&msgtype=extended&protocol=jsono
```

- `api_key` is a **URL path segment**, not a query parameter or header. `portid` is MarineTraffic's own numeric ID, **not** the UN/LOCODE (read it from the port page URL on marinetraffic.com).
- Optional: `timespan` (days ahead, max 40), `shiptype` (7 Cargo, 8 Tanker), `dwt_min`, `dwt_max`, `gt_min`, `gt_max`, `fromportid`.
- Limit: 100 requests per minute. The contract allows **1 to 2 calls per port per day**.
- Documented fields (unverified): `IMO, MMSI, SHIP_ID, SHIPNAME, TYPE_NAME, SHIPTYPE, CALLSIGN, FLAG, LENGTH, WIDTH, DRAUGHT, GRT, DWT, YEAR_BUILT, LAT, LON, SPEED, COURSE, STATUS, ETA, ETA_CALC, ETA_UPDATED, LAST_PORT_*, PORT_*, CURRENT_PORT*, NEXT_PORT_*, TIMESTAMP`.
- Doubtful, verify against real data: values arrive as **strings**; `SPEED` is documented as knots times 10; `DRAUGHT` and `DWT` units look wrong in the sample (a 162 m passenger ship with DWT 1703); `IMO` and `NEXT_PORT_*` are sometimes blank; `ETA_CALC` and `ETA_UPDATED` were always blank; `STATUS` and `SHIPTYPE` are numeric codes with no confirmed mapping. **Do not use `dwt` for scoring until real data confirms the unit.**

### 6.2 AIS Latest (Kpler)

```
GET  https://api.kpler.com/v2/maritime/ais-latest?filter=<ECQL>&limit=<n>&fields=<csv>&format=json
POST https://api.kpler.com/v2/maritime/ais-latest   body: {"filter": "...", "limit": ..., "fields": "..."}
Header: Authorization: Basic <API_KEY>        (the key is used as given; this is what Kpler's own Python example does)
```

- Limit: 300 requests per minute. Returns **one latest position per vessel from the past 7 days**.
- The area is an **ECQL filter string**, not an area ID. Examples: `INTERSECTS(position, POLYGON((lon lat, ...)))`, `bbox(position, minLon, minLat, maxLon, maxLat)`, `DWITHIN(position, POINT(lon lat), metres, meters)`. Coordinates are **longitude, latitude**. A `%` must be URL-encoded as `%25` in a GET; use POST for long filters.
- Other filter examples: `vesselType IN ('LNG Tanker')`, `NOT vesselType IN ('Yacht','Pleasure Craft')`, `sog >= 10`, `imo IN (...)`, `mmsi IN (...)`, `dateDifference(now(), posDt, 'm') <= 10`.
- Response: a **GeoJSON FeatureCollection**: `features[]`, each with `id`, `geometry` (WGS84, lon/lat), `properties`; plus `totalFeatures`, `numberMatched`, `numberReturned`, `timeStamp`.
- Documented property names: `vesselUid, mmsi, imo, longitude, latitude, sog, cog, rot, heading, navStatus, posMsgType, posSrc, vesselName, callsign, flag, vesselTypeAis, vesselType, length, width, dwt, grt, destination, eta, draught, staticMsgType, staticSrc, posDt, staticDt, insertDt`.
- `navStatus` is a **numeric AIS code** (0 under way using engine, 1 at anchor, and so on), not text. `eta` is ISO 8601 and is the vessel-reported AIS ETA.
- The full list of valid `vesselType` strings is a download linked from `developers.kpler.com/api/tutorials/AIS`. Kpler's type names may not match `VESSEL_TYPE_EXCLUSIONS` in `config/settings.py` (Tug, Pilot, Buoy, and so on). Build the exclusion from the downloaded list, not from guesses.
- **The Singapore and Fujairah areas are not final.** The user is waiting for Kpler to confirm them. Keep the area as per-port configuration; do not invent coordinates.

### 6.3 Vessel Ownership and Particulars (Kpler, GraphQL)

```
POST https://api.kpler.com/v2/maritime/vessels/graphql
```

- **Auth header is not documented on the spec page. Do not guess.** It is probably the same `Authorization: Basic <key>` as AIS, but this is unconfirmed. Make the header name and scheme configurable and confirm on the first real call.
- Example query: `vessels(first: 10, where: {filters: [{field: "identifier.imo", op: EQ, values: "9389679"}], operator: AND}) { pageInfo { hasNextPage endCursor } nodes { identifier { imo mmsi callSign shipId } management { ... } particulars { ... } } }`. Operators: EQ, NOT_EQ, GE, LE, LIKE, IN, NOT_IN. Pagination: `first` (max 1000) and `after`/`endCursor`. Rate limit 300 requests per minute.
- `management` has six roles: `beneficialOwner`, `registeredOwner`, `commercialManager`, `operator`, `technicalManager`, `ismManager`. Each has `current` (an object) and `historical` (a list). Each entry has `name, country, address, website, email, startDate, endDate`. In the documentation sample nearly every `website` and `email` is null. Kpler says they are filled "where available".
- `particulars.tonnage` has `grossTonnage`, `deadweightTonnage`; `particulars.general` has `name, commercialFleet, generalVesselType, detailedVesselType, serviceStatus, flag`.
- Kpler IMO and MMSI are **integers**.
- Contract: **500 unique IMOs per month, 6,000 per year, 100 calls per day** peak. There is **no API trial**: Kpler fills in a coverage file for 20 sample IMOs.

### 6.4 MarineTraffic Vessel Master Data (new, not yet agreed with Kpler)

`GET https://services.marinetraffic.com/api/vesselmasterdata/{api_key}` (key in path). The sample has `OWNER, MANAGER, FINANCIAL_OWNER, TECHNICAL_MANAGER`, plus `MANAGER_WEBSITE`, `OWNER_WEBSITE`, and country/town fields, but **no email**. Do not build on it. Ask the user whether their contract covers it; it may be a fallback if Kpler ownership returns too few emails.

### 6.5 Pricing and use

Subscription based, not per-call. For every Kpler call write `EnrichmentLog.credits_spent = 0`. Kpler confirmed in writing that internal BD use, including direct outreach, is permitted. MCP is not included. The renewal discount requires finalising by **13 November 2026**. The trial for Expected Arrivals and AIS Latest runs **4 to 7 November 2026**.

## 7. Plan

Do the steps in order. Steps B1 to B3 need no real responses. Steps B4 onward need saved trial responses; **stop and ask the user for them** before starting B4.

**B1. Settings (`config/settings.py`).** Read keys and URLs from `.env` via `os.getenv`. Add: `MARINETRAFFIC_API_KEY`, `MARINETRAFFIC_BASE_URL` (default `https://services.marinetraffic.com/api`), `KPLER_API_KEY`, `KPLER_AIS_URL` (default `https://api.kpler.com/v2/maritime/ais-latest`), `KPLER_OWNERSHIP_URL` (default `https://api.kpler.com/v2/maritime/vessels/graphql`), `KPLER_AUTH_HEADER` (default `Authorization`), `KPLER_AUTH_SCHEME` (default `Basic`, flagged in a code comment as unconfirmed for ownership). Provider toggles `DISCOVERY_PROVIDER`, `EXPECTED_ARRIVALS_PROVIDER`, `ENRICHMENT_PROVIDER`, **all defaulting to `"datadocked"`** until Step B7. Usage guards: `KPLER_OWNERSHIP_MAX_CALLS_PER_DAY = 100`, `KPLER_OWNERSHIP_MAX_UNIQUE_IMOS_PER_MONTH = 500`, `KPLER_EXPECTED_ARRIVALS_MAX_CALLS_PER_PORT_PER_DAY = 2`, `KPLER_AIS_MAX_CALLS_PER_AREA_PER_DAY = 2`. Enforce them by counting today's `EnrichmentLog` rows.

**B2. Models and migrations (show each migration before applying).**
- `Port`: add `kpler_port_id` (CharField, null, blank; the MarineTraffic numeric ID) and `kpler_ais_filter` (TextField, blank; the ECQL spatial clause for this port's anchorage and approach area, for example `INTERSECTS(position, POLYGON((...)))`).
- `VesselObservation`: add `navigational_status` (CharField, blank, default empty) and `destination` (CharField, blank). Keep `navigational_status` as the provider text, and add a small mapping from AIS numeric codes to text in `apps/common/constants.py`. Make `source` set per provider (`"kpler-ais"`, `"marinetraffic-expectedarrivals"`, `"datadocked.com"`).
- Roles: **the user approved adding `commercial_manager`, `technical_manager`, `ism_manager`** to `RELATIONSHIP_ROLE_CHOICES` in `apps/common/constants.py`. Add a migration. Update `scoring_service._score_priority_manager` so all four manager-type roles (`manager`, `commercial_manager`, `technical_manager`, `ism_manager`) count toward the +20 signal.
- Persist `destination` and `navigational_status` from DataDocked's location response too (they are currently parsed and discarded).

**B3. `integrations/kpler/` clients (no parsers yet).** Three separate clients in separate modules, because the services differ: `marinetraffic.py` (REST, key in the URL path, never log the URL with the key), `ais.py` (GET and POST, ECQL filter, `Authorization: Basic`), `ownership.py` (GraphQL POST, configurable auth header). Custom exceptions mirroring `integrations/datadocked/exceptions.py`. 15 to 60 second timeouts. Handle HTTP errors, timeouts, empty and non-JSON bodies. Never log a key.

**B4. Parsers, built from the real saved trial responses.** `integrations/kpler/parsers.py`, pure functions, no HTTP or ORM. Normalise to the Section 5 shapes. Rules: `MMSI` and `IMO` to `str` via `normalize_imo`; `SHIPNAME`/`vesselName` to `name`; `TYPE_NAME`/`vesselType` to `type`/`typeSpecific`; `DWT`/`dwt` to `dw`; `GRT`/`grt` to `gt`; `ETA` ISO 8601 to an aware datetime; `SPEED` and `sog` to a float in knots (confirm the x10 scaling on real data before dividing); numeric `navStatus` to text via the mapping. One bad record must not abort the batch.

**B5. Tasks and commands.** `tasks/kpler_expected_arrivals.py` (for ports with `kpler_port_id`; creates a `VesselObservation` when `LAT`/`LON` are present), `tasks/kpler_discovery.py` (for ports with `kpler_ais_filter`; AIS Latest plus the existing exclusion filters), with the same stats-dict shape as the DataDocked tasks. Commands `run_kpler_expected_arrivals` and `run_kpler_discovery`. Each task honours the usage guards and writes `EnrichmentLog` rows with `endpoint_called` starting `marinetraffic:` or `kpler:` and `credits_spent=0`. Branch on the `*_PROVIDER` setting so the existing `run_discovery` and `run_expected_arrivals` commands route to the chosen provider.

**B6. Enrichment and ownership.**
- Replace the per-vessel "location" step with an AIS Latest lookup by IMO (`imo IN (...)`, POST) when `ENRICHMENT_PROVIDER == "kpler"`.
- Ownership: query by IMO, create `Company` and `VesselRelationship` rows for all six roles using `current` only (not `historical`). Match Companies by case-insensitive name as `_match_or_create_company` does today, so one company in several roles never creates duplicate Companies. Set `source` to the Kpler product name and `verified=False`.
- **Spend discipline:** only look up IMOs that pass the exclusion filters and are worth contacting, cache results, and skip any IMO already looked up this month, to stay under 500 unique IMOs a month.

**B7. Cutover (only if the user confirms).** Flip the three provider defaults to `"kpler"`. Keep `"datadocked"` selectable. Update the README, the scheduling instructions and `.env` documentation.

## 8. Tests

- Parser tests built from the **saved real trial responses**, copied into a `fixtures/` folder with keys and any personal data removed. Never from documentation samples.
- Normalisation tests: Kpler records produce dicts with the same keys and types as the DataDocked parsers for shared fields.
- Role tests: all six role values store; uniqueness on (vessel, company, role) still holds; a `technical_manager` relationship to a `priority="high"` company earns the +20 signal; one company in several roles creates one `Company`.
- `imo` of `""`, `None`, `"0"` and the integer `0` is treated as missing.
- Provider toggle tests: each `*_PROVIDER` setting routes to the right client without affecting the other two.
- Usage guard tests: calls stop at the daily limit and at the monthly unique-IMO limit.
- Observation test: with the Kpler expected-arrivals provider and `LAT`/`LON` present an observation is created; with DataDocked none is created, as today.
- Regression: the full existing suite (126 tests) passes unchanged with every toggle at `"datadocked"`.

## 9. Ask the user before deciding

1. The MarineTraffic numeric port IDs for Singapore and Fujairah.
2. The AIS anchorage and approach areas for both ports (WKT polygon or bbox, lon/lat order), once Kpler confirms them.
3. The ownership endpoint's auth header (confirm on the first real call).
4. Whether the `vesselType` exclusion list should be taken from Kpler's downloadable list.
5. Whether `kpler_ais_filter` should be a single ECQL clause per port (recommended) or structured coordinates.
6. Whether MarineTraffic Vessel Master Data is covered by the contract (Section 6.4).
7. When to run the Step B7 cutover, given the 13 November deadline and no ownership trial.

## 10. Do not

- Do not remove or change DataDocked behaviour or defaults before Step B7.
- Do not put secrets anywhere except `.env`.
- Do not guess endpoints, auth, field meanings or units.
- Do not apply a migration without showing it first.
- Do not present registry data as verified.
