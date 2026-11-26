# Kpler/MarineTraffic Integration — Discovery, Expected Arrivals, Ownership

Add Kpler as a **second, fully parallel data provider** alongside DataDocked
— not a replacement. This is an add-on to the already-built project. Do not
remove, disable, or bypass any existing DataDocked integration, task, or
service-layer function. Everything here must be toggleable per-feature via
settings, defaulting to DataDocked until each piece is proven out with real
live data.

**Why parallel, not a swap:** Kpler API access and pricing are still
unconfirmed at the time of this prompt. DataDocked's flat per-call pricing
has been specifically shown to suit high-traffic hub ports (Singapore,
Jebel Ali) better than a per-vessel-found model might. None of that has
changed. Build Kpler fully, but don't make it the default for anything
until it's been verified against real data and real cost.

## 0. Prerequisite fix — do this regardless of Kpler

**Port Rashid's `un_locode` is `AEPRA` in the live `Port` table — confirmed
wrong.** The correct code, per DataDocked's own port-calls data, is
`AEDXB`. Fix this first; every UN/LOCODE-keyed call (DataDocked or Kpler)
for this port is currently broken.

## 1. Settings additions (`config/settings.py`)

```python
KPLER_API_KEY = os.getenv("KPLER_API_KEY", "")
KPLER_REST_BASE_URL = "https://services.marinetraffic.com/api"
# GraphQL endpoint and auth mechanism for the Ownership & Particulars product
# are unconfirmed — do not guess. Leave as a placeholder and flag clearly
# in a code comment that this must be verified against real docs/access
# before the ownership integration can be tested live.
KPLER_GRAPHQL_URL = os.getenv("KPLER_GRAPHQL_URL", "")

# Per-feature provider toggle — all default to DataDocked. Flip individually
# once each path is proven live against Kpler.
DISCOVERY_PROVIDER = os.getenv("DISCOVERY_PROVIDER", "datadocked")  # "datadocked" | "kpler"
EXPECTED_ARRIVALS_PROVIDER = os.getenv("EXPECTED_ARRIVALS_PROVIDER", "datadocked")
ENRICHMENT_PROVIDER = os.getenv("ENRICHMENT_PROVIDER", "datadocked")

# Kpler credit costs are UNCONFIRMED. Use placeholder values and log a
# warning on every Kpler EnrichmentLog write until real numbers are known —
# do not treat these as trustworthy for cost tracking yet.
KPLER_AREA_SCAN_CREDITS_ESTIMATE = None  # unknown — per-call or per-vessel, unconfirmed
KPLER_EXPECTED_ARRIVALS_CREDITS_ESTIMATE = None
KPLER_OWNERSHIP_CREDITS_ESTIMATE = None
```

## 2. Model changes

### `apps/common/constants.py` — new relationship roles

```python
RELATIONSHIP_ROLE_CHOICES = [
    ("owner", "Owner"),
    ("manager", "Manager"),
    ("operator", "Operator"),
    ("commercial_manager", "Commercial Manager"),
    ("technical_manager", "Technical Manager"),
    ("ism_manager", "ISM Manager"),
]
```
Generate and apply the migration for `apps/relationships/models.py`. The
existing `UniqueConstraint(fields=["vessel", "company", "role"])` needs no
change — it automatically covers the new values.

**Required companion fix** — `services/scoring_service.py`'s
`_score_priority_manager()` currently filters `role="manager"` only. Update
it to treat `manager`, `commercial_manager`, `technical_manager`, and
`ism_manager` as equally eligible for the "priority manager" signal,
otherwise relationships created via the new roles will never contribute to
scoring even when linked to a high-priority company.

### `apps/ports/models.py` — Kpler-specific identifiers

```python
kpler_port_id = models.CharField(max_length=20, null=True, blank=True,
    help_text="MarineTraffic's internal numeric port ID, required for expectedarrivals.")
kpler_area_of_interest_id = models.CharField(max_length=50, null=True, blank=True,
    help_text="Pre-configured Area of Interest ID, required for Kpler's area-scan equivalent — Kpler has no lat/long/radius parameter.")
```
Both nullable — a port can be fully functional on DataDocked with these
blank. Populate them manually per port once each is looked up/configured on
Kpler's side (this is a dashboard/account step, not something the code can
automate).

### `apps/observations/models.py` — capture fields already being discarded

Add, while this pipeline is already being touched:
```python
navigational_status = models.CharField(max_length=50, blank=True)
destination = models.CharField(max_length=200, blank=True)
```
**Why now:** `parse_location_response()` already parses both fields from
DataDocked's response today — they're computed and silently thrown away.
Since Kpler's `expectedarrivals` will introduce a second source of this
same kind of data, fix the existing gap at the same time rather than
building a second pipeline with the same discard bug.

## 3. New integration module — `integrations/kpler/`

Mirror the existing `integrations/datadocked/` structure.

`client.py`:
```python
class KplerClient:
    """REST calls use api_key as a query parameter (not a header, unlike DataDocked)."""
    def get_vessels_in_area_of_interest(self, cursor=None, limit=1000): ...
    def get_expected_arrivals(self, port_id, extended=True): ...
    # GraphQL ownership client — separate method/class until auth mechanism
    # is confirmed; do not assume it shares the REST client's query-param auth.
```

`parsers.py` — critically, **normalize Kpler's raw fields into the exact
same internal dict shape DataDocked's parsers already produce.** This is
what lets `vessel_service.py`, `observation_service.py`, and
`opportunity_service.py` stay provider-agnostic, exactly as the ground-truth
investigation confirmed they currently are. Specific casts needed:
- `IMO`/`MMSI` are integers in Kpler's JSON — cast to `str()`, same pattern
  already used in `parse_expected_arrivals_response` for DataDocked.
- `TYPE_NAME`/`SHIPTYPE` → normalize to the same key `vessel_service`
  already expects (`typeSpecific`'s equivalent) so the existing exclusion
  filter logic (`is_vessel_type_excluded`) needs no changes.
- `ETA` is ISO 8601 already — no multi-strategy parsing needed, unlike
  DataDocked's `formattedETA`.

Do not write directly into `Vessel`/`Opportunity`/`Company` from the parser
— parsers return normalized dicts; the existing service-layer functions
consume them, unchanged.

## 4. Service layer changes

### `services/vessel_service.py`
No change needed if Kpler parsers normalize correctly per section 3 —
`get_or_create_vessel()` should accept the same shape regardless of source.
Verify this holds; if any Kpler-specific field genuinely has no DataDocked
equivalent (there shouldn't be one for core identity fields), handle it
explicitly rather than silently dropping it.

### `services/observation_service.py`
**New capability, deliberate decision, not automatic:** Kpler's
`expectedarrivals` (extended mode) includes live `LAT`/`LON` — DataDocked's
version does not, which is why `tasks/expected_arrivals.py` currently never
creates a `VesselObservation` from that path. When
`EXPECTED_ARRIVALS_PROVIDER == "kpler"` and position data is present, create
an observation the same way area-scan discovery does. When running against
DataDocked, behavior is unchanged (no observation, as today).

### `services/company_service.py`
Extend `apply_management_data()` (or add a Kpler-specific variant called
from the same orchestration point) to loop over **all six** ownership
roles returned by the ownership product, not just manager + owner. Match-or
-create `Company` the same way for each; create `VesselRelationship` rows
with the new role values from section 2. Confirm this still prevents
duplicate `Company` rows when the same company fills multiple roles (the
existing WAN HAI 501 case — same company as both manager and owner —
is the direct precedent to test against).

### `services/enrichment_service.py`
Add a Kpler-path equivalent to `enrich_vessel()` (or branch on
`settings.ENRICHMENT_PROVIDER` inside the existing function) that calls the
Kpler ownership client instead of DataDocked's, but produces the same
downstream effects: update `Opportunity.eta`/zone, call
`apply_management_data()`, log to `EnrichmentLog`. Use the
`KPLER_*_CREDITS_ESTIMATE` settings for `credits_spent`, and log a warning
on every write that the cost figure is unconfirmed, until real pricing is
known.

## 5. Tasks — new, parallel to existing ones

`tasks/kpler_discovery.py` — structurally different from
`tasks/discovery.py`: Kpler's area-scan has no lat/long/radius call shape,
it queries a pre-configured Area of Interest with cursor pagination. Mirror
the stats-dict return shape (`port`, `seen`, `new_vessels`,
`new_opportunities`, `excluded`, `errors`) for consistency, but the fetch
logic itself is genuinely different — don't try to force it into
`discovery.py`'s existing function signatures. Only runs for ports with
`kpler_area_of_interest_id` set.

`tasks/kpler_expected_arrivals.py` — mirrors `tasks/expected_arrivals.py`'s
structure. Only runs for ports with `kpler_port_id` set.

### Management commands
`run_kpler_discovery` and `run_kpler_expected_arrivals`, same shape as the
existing `run_discovery`/`run_expected_arrivals` commands. Keep them
separate commands rather than flags on the existing ones — this preserves
a clean, deliberate boundary between "run the proven DataDocked pipeline"
and "run the pipeline we're still validating," consistent with how
discovery and expected-arrivals are already kept as separate concerns.

## 6. Tests

- Parser normalization tests: confirm Kpler's raw area-scan/expected-arrivals
  payloads produce dicts identical in shape to what DataDocked's parsers
  produce, for the fields both providers share.
- Role migration tests: all six `RELATIONSHIP_ROLE_CHOICES` values can be
  stored; `UniqueConstraint` still prevents duplicate (vessel, company, role).
- Scoring test: a `VesselRelationship` with `role="technical_manager"`
  linked to a `priority="high"` `Company` contributes the +20
  priority-manager signal — this is the regression the role migration
  specifically needs covered.
- Observation creation test: `EXPECTED_ARRIVALS_PROVIDER="kpler"` with
  position data present creates a `VesselObservation`;
  `EXPECTED_ARRIVALS_PROVIDER="datadocked"` does not, unchanged from today.
- Provider toggle test: flipping each `*_PROVIDER` setting routes to the
  correct client/task without affecting the other two toggles.
- Regression: full existing test suite (DataDocked discovery, expected
  arrivals, enrichment, scoring, auth) passes unchanged with all three
  toggles left at their `"datadocked"` defaults.

## Out of scope for this prompt

- `port-congestion` and `predictive-arrivals` — not requested in this
  round; no model work for either here.
- No cutover of any default provider setting — all three toggles stay on
  DataDocked until independently verified against live Kpler data.
- No removal of any DataDocked code, client method, or task.
