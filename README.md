# Ark Energy Analytics Assistant

A production-minded prototype for asking plain-language questions about energy
consumption across Ark Energy client organizations. The language model selects
strict, allow-listed functions; Python performs every calculation over a local
processed cache; the model receives only structured analytical results and writes
the consultant-facing explanation.

The implementation was built against the official
[Wattics API v1 reference](https://developers.wattics.com/) and the official
[OpenAI function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).
It targets Python 3.11+.

## Architecture and data flow

```text
Wattics API
  -> dynamic organization/site/meter discovery
  -> <=90-day UTC active-power requests
  -> raw JSON cache (private, ignored)
  -> explicit W -> kW -> interval kWh conversion
  -> validation, duplicate policy, quality metrics
  -> partitioned Parquet cache by meter (private, ignored)

Consultant question
  -> structured deterministic-first scope decision
  -> deterministic intent/entity/period hints for obvious requests
  -> OpenAI Responses API with strict JSON-schema tools when planning is needed
  -> allow-listed Python tool execution
  -> structured tool-result validation
  -> structured final-answer synthesis
  -> semantic field provenance check
  -> one same-result synthesis retry
  -> deterministic renderer if synthesis still fails
  -> consultant answer + visible trace + usage
```

Raw interval records are never inserted into the model context. The model has no
filesystem, SQL, shell, Python, or arbitrary-code tool. It can call only the
schemas in `src/tools/schemas.py`.

### Repository structure

```text
app.py                         Streamlit entry point
src/config.py                  Environment configuration and validation
src/api/                       Wattics client and typed errors
src/data/                      Discovery, extraction, cache, cleaning, quality
src/analytics/                 Deterministic energy analytics
src/tools/                     Strict schemas, allow-list, handlers
src/llm/                       Prompt, Responses loop, grounding, usage
src/evaluation/                Reproducible behavioral evaluation runner
src/ui/streamlit_app.py        Chat, status, history, trace
scripts/validate_access.py     Metadata-only access validation
scripts/sync_data.py           Incremental/backfill synchronization
scripts/refresh_data.py        Locked manual refresh used for operations/debugging
scripts/inspect_cache.py       Safe metadata inspection
scripts/smoke_test.py          Offline deterministic smoke test
scripts/run_evaluations.py     Mocked-LLM, real-cache behavioral evaluation
scripts/run_live_evaluations.py Controlled billable final workflow check
tests/                         Synthetic unit and orchestration tests
data/                          Private cache roots (contents ignored)
PRESENTATION_NOTES.md          Demo and technical-presentation guide
ASSESSMENT_COMPLIANCE.md       Requirement-by-requirement assessment review
EVALUATION_REPORT.md           Mocked and controlled live-model metrics
VERIFICATION_REPORT.md         Executed command and smoke-test evidence
docs/EVALUATION_QUESTIONS.md   Expected behavior evaluation set
docs/RELIABILITY_FIX.md        Root-cause reproduction and correction
```

## Setup

Do not use the system Python if it is older than 3.11.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If local execution policy allows activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

Activation is optional; every command below can use
`.\.venv\Scripts\python.exe` directly.

### Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
```

## Environment variables

| Variable | Required for | Meaning |
|---|---|---|
| `WATTICS_API_TOKEN` | validation/sync | API token passed in the documented `Authorization` header |
| `WATTICS_API_BASE_URL` | sync | Defaults to `https://api.wattics.com/api/v1` |
| `OPENAI_API_KEY` | UI questions | OpenAI API key |
| `OPENAI_MODEL` | UI questions | Defaults to `gpt-5.6-terra` |
| `OPENAI_SERVICE_TIER` | UI/cost | `standard`; translated to the Responses API's `default` label |
| `OPENAI_*_PRICE_PER_MILLION` | cost | Versioned input, cached-input, cache-write, and output rates |
| `OPENAI_PRICING_SOURCE` | cost | Displayed official pricing reference |
| `OPENAI_PRICING_CONFIG_DATE` | cost | Date the configured price table was reviewed |
| `DEFAULT_TIMEZONE` | sync/analytics | IANA timezone used only when source site metadata omits/invalidates timezone |
| `CACHE_ROOT` | cache | Defaults to `data` |
| `WATTICS_TIMEOUT_SECONDS` | sync | Per-request timeout |
| `WATTICS_MAX_RETRIES` | sync | GET retries for connection, 429, and transient server failures |
| `MAX_TOOL_ROUNDS` | LLM | Hard tool-calling loop limit |
| `CACHE_STALE_HOURS` | UI/ops | Age threshold for the UI's stale-cache warning |
| `DATA_AUTO_SYNC` | sync | Enables freshness-aware automatic incremental updates |
| `DATA_SYNC_INTERVAL_MINUTES` | sync | Cache freshness interval; defaults to 60 minutes |
| `DATA_SYNC_ON_STARTUP` | sync | Check and refresh a missing/stale cache at UI startup |
| `DATA_SYNC_BEFORE_QUERY_IF_STALE` | sync | Lightweight freshness check immediately before a question |
| `DATA_SYNC_MAX_RETRIES` | sync | Bounded update attempts |
| `DATA_SYNC_INITIAL_LOOKBACK_DAYS` | sync | Initial cache horizon only; later updates are incremental |
| `DATA_SYNC_LOCK_TIMEOUT_SECONDS` | sync | Stale-lock recovery threshold |
| `NUMERIC_*_TOLERANCE` | grounding | Relative, absolute, and percentage semantic tolerances |
| `ANSWER_DECIMAL_PLACES` | rendering | Consultant-facing fallback precision |

`.env` and every private cache file are ignored. `.env.example` contains placeholders
only.

## Validate organization access

```powershell
.\.venv\Scripts\python.exe scripts\validate_access.py
```

The command downloads no energy data and prints names and stable identifiers only.
Matching is case/punctuation normalized. A near match is reported separately (for
example, the assessment's singular display name versus an API plural). A 403 is
reported as permission denial. When an organization is absent from the list endpoint,
the script correctly says "not found or not visible": without a stable ID, the API
cannot prove whether an invisible organization exists.

`list_wattics_orgs.py` remains as a backward-compatible safe wrapper. The original
version's full-response printing and embedded observed IDs were removed.

## Synchronize Wattics data

The official API documents:

- `GET /organizations`
- `GET /sites?organization_id=...`
- `GET /meters?organization_id=...&site_id=...`
- `GET /meters/{id}/raw_data`
- raw-data windows no longer than 90 days
- UTC request/response timestamps
- `active_power`, with `show_phases=false`, returning a total power value

The adapter validates every list/object before using fields. It discovers all IDs;
none are hardcoded.

Example:

```powershell
# Default: assessment organizations, trailing 365 days
.\.venv\Scripts\python.exe scripts\sync_data.py

# Explicit UTC period (start inclusive, end exclusive)
.\.venv\Scripts\python.exe scripts\sync_data.py `
  --start 2026-06-01 --end 2026-07-01

# One organization or meter, by exact name or stable ID
.\.venv\Scripts\python.exe scripts\sync_data.py `
  --organization "Food Corp." --meter "Main Meter" `
  --start 2026-06-01 --end 2026-07-01

# Re-download and replace only the requested slice; preserve outside periods
.\.venv\Scripts\python.exe scripts\sync_data.py `
  --start 2026-06-01 --end 2026-07-01 --full-refresh
```

Normal sync extends both historical and forward cache boundaries. It does not
automatically repair internal gaps; use `--full-refresh` for the affected period.
Writes are atomic. State is updated after each successful meter, so an interrupted
operation resumes from per-meter boundaries. Duplicate intervals are deterministically
removed. API/validation failures are isolated in
`data/metadata/failed_meters.json`, and a failed refresh never replaces the previous
valid Parquet partition.

The UI creates an `AutoSyncManager` on startup. It reads synchronization metadata
without downloading data, refreshes only when the cache exceeds
`DATA_SYNC_INTERVAL_MINUTES`, and performs the same lightweight check before a query.
A nonblocking, cross-process `data/metadata/sync.lock` prevents concurrent writers.
The UI exposes a manual **Refresh data** control and displays last success, running/error
status, cache age, latest cached observation, failed meters, and whether each answer
used fresh or stale cached data.

The same locked manual-refresh path is available from the terminal:

```powershell
.\.venv\Scripts\python.exe scripts\refresh_data.py
```

Locks record the owning process and host. A live owner remains protected, while a lock
left by a terminated local process is reclaimed immediately; unreadable or remote locks
retain the configured age-based recovery threshold.

Non-electric meters are discovered and retained in hierarchy metadata but intentionally
skipped by the energy cache. Electricity meters with missing interval metadata infer a
native interval only when a timestamp-difference mode has at least 75% support. No
readings means no interval is invented.

## Measurement normalization

The currently enabled extractor requests documented electricity `active_power`.
For a known native interval:

```text
demand_kw = active_power_w / 1000
energy_kwh = demand_kw * interval_minutes / 60
```

Demand is labeled `derived_from_documented_active_power_w`; it is never presented as a
direct demand measurement. The original numeric value and `W` unit are preserved.
Other measurement kinds must receive an explicit adapter before entering the canonical
energy cache. Cumulative readings, pulse counts, gas, water, and arbitrary numeric
values are never silently treated as kWh.

## Cleaning, timezone, and missing-data policies

- Canonical timestamps are timezone-aware UTC.
- Operational dates/hours are derived in the source timezone.
- If source timezone metadata is absent, `DEFAULT_TIMEZONE` is stored with
  `timezone_assumed=true` and every affected result warns.
- Fully identical rows are removed.
- Same-meter/same-timestamp rows with different values are conflicts. Both are excluded,
  written to a private conflict file, and counted; they are never summed.
- Invalid timestamps, invalid intervals, and negative derived interval energy are
  conservatively excluded and counted. Negative values may represent export in another
  deployment; production should add an import/export semantic adapter rather than
  guessing.
- Missing intervals remain missing. They are never filled with zero.
- Completeness is `observed / expected`, calculated per meter over the requested local
  period and returned as both ratio and percentage.
- Aggregates include observation counts, expected counts, completeness, and
  `is_partial`.

Inspect status without exposing raw data:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_cache.py
```

## Analytics definitions

All date parameters use an inclusive local `start_date` and exclusive local `end_date`.

### Consumption

Total is the sum of valid interval kWh. Average interval energy and average demand are
also returned. The internal aggregation layer supports native, hourly, daily, weekly,
and monthly resolution. LLM-callable schemas expose hourly through monthly only; native
rows are deliberately withheld. Aggregate series are capped at 500 records while the
summary still covers the full selection.

### Period change

Current and previous total kWh, absolute difference, percentage difference, exact
boundaries, and completeness are returned. If previous dates are omitted, application
code chooses the immediately preceding equal-duration period. A zero previous value
produces `null` percentage plus a warning.

### Baseload

For each meter, the default is the 10th percentile of valid interval demand. Site
baseload is the sum of meter estimates. For each interval, baseline energy uses
`min(actual demand, baseline demand) * interval hours`; operational energy is energy
above that baseline. The percentile and minimum observation count are explicit tool
parameters.

This is a statistical low-load estimate, not a physical measurement. It does not assume
factory and hotel operating hours are the same. Short/incomplete periods are warned.

### Peak demand

For one meter, peak is its maximum valid demand. For multiple meters at one shared
native interval, the tool first makes a coincident sum by timestamp and then takes the
maximum. It returns the peak, UTC/local timestamp, interval, entity scope, contributing
meter count, completeness, and source. Mixed native intervals require a narrower filter.

### Load factor

`average coincident demand / peak coincident demand`. Both inputs, ratio, percentage,
common interval, and meter count are returned. Zero peaks safely produce no factor.

### Weekday/weekend

Saturday/Sunday classification uses local operational dates, never UTC dates. The tool
returns totals, average daily consumption, weekend-relative percentage difference,
complete day counts, overall completeness, and optional local-hour profiles.

### Ranking and cross-organization comparisons

Site ranking supports total consumption, average daily consumption, coincident load
factor, and completeness with explicit direction and units. Entity comparison also
supports weekday/weekend ratio.

Raw kWh and kWh/day are scale-dependent. The system does not claim efficiency without
denominators such as floor area, occupancy, guest nights, production, or weather.
Although the live hierarchy contains some contextual numeric meters, they are not used
as normalization denominators until their semantics, coverage, and entity mapping are
explicitly modeled.

The Wattics meter response does not expose parent/main/submeter topology. Any selection
with more than one meter therefore returns a warning that summing streams may
double-count overlap. This is a material known limitation, not hidden.

### Anomalies

For each meter, valid interval kWh is grouped by local hour of week. A robust baseline
uses the group median. Dispersion is scaled median absolute deviation, with scaled IQR
fallback. A configurable absolute robust-score threshold and minimum sample count decide
flags. Results include actual/baseline/deviation values, score, direction, supporting
sample size, meter, site, and timestamp.

This explainable method catches abrupt departures from repeated weekly patterns. It can
miss gradual drift, cannot explain causes, and can produce very large scores when the
baseline and dispersion are near zero. Missing readings are excluded as quality events,
not energy anomalies.

## Guardrails and LLM orchestration

Every request receives one structured scope state:

- `in_scope`
- `energy_but_unsupported`
- `out_of_scope`
- `needs_clarification`

The scope record includes confidence, a reason, deterministic matches, a suggested
tool, and missing information for internal logging. Matching checks registered tool
capabilities, discovered organization/site/meter names and aliases, supported metrics,
date expressions, energy vocabulary, and recent conversation history. A deterministic
tool or known-entity match overrides an uncertain unrelated classification.

Unsupported energy questions receive a precise missing-data/capability explanation and
the closest historical analysis. Unrelated and prompt-injection requests receive a
brief Ark Energy limitation. Unresolved follow-ups ask one focused question.

The runtime state machine is:

1. validate request and scope;
2. choose a deterministic plan or a constrained/model plan;
3. validate arguments and resolve aliases to stable IDs;
4. execute each allow-listed tool once;
5. validate its structured result;
6. synthesize an `AnswerEnvelope` with `status`, `answer`, `facts`, `warnings`, and
   `limitations`;
7. validate every analytic number/timestamp and fact source field;
8. retry synthesis once with the same results and no tools;
9. use a deterministic tool-specific renderer if the retry fails.

The original successful trace is never discarded, and synthesis failure never becomes
an out-of-scope decision. Obvious peak, consumption, anomaly, baseload, quality,
load-factor, profile, ranking, and weekday/weekend intents receive deterministic hints.
Period-less assessment comparisons select the latest complete cached periods rather
than partial recent slices.

### Semantic numeric grounding

The validator flattens each validated result into field-level provenance records. It
recognizes ISO/readable timestamps, `Z`/`+00:00`/`UTC`, 12/24-hour formats, commas,
units, trailing zeros, configured rounding, and ratio/percentage representations.
Large values use relative tolerance, small values absolute tolerance, and percentages a
separate point tolerance. Formatting `188.70695999999998` as `188.707 kW` is valid;
adding two returned values into a new unreturned total is not.

The intermittent peak refusal was caused by the previous validator splitting a readable
time into independent numbers: `4:25 PM` was compared literally with ISO hour `16`.
When both model attempts used readable time, a successful tool result was replaced by a
generic grounding failure. Timestamp normalization and deterministic fallback remove
that path. See `docs/RELIABILITY_FIX.md`.

### GPT-5.6 Terra usage and cost

Usage extraction reads total input, cached input, cache-write, output, and total tokens
when reported. Unreported cache details are treated as zero and labeled. Configured
Standard short-context rates are centralized in `Settings` and `PricingConfiguration`:

```text
uncached_input = max(input - cached_input, 0)
cost = uncached_input / 1M * 2.50
     + cached_input / 1M * 0.25
     + cache_write / 1M * 3.125
     + output / 1M * 15.00
```

The regression `9,924` input plus `363` output tokens produces exactly `$0.030255`
internally and displays `$0.0303`.

## Run the application

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The UI shows configuration/cache status, synchronization controls, freshness, chat
history, a loading state, expandable scope and tool traces, grounding/fallback state,
fresh-versus-stale answer metadata, and complete token/cost accounting. It never sends
the raw interval dataset to the model.

## Tests and offline smoke check

```powershell
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts app.py list_wattics_orgs.py
.\.venv\Scripts\python.exe -m ruff check src tests scripts app.py list_wattics_orgs.py
.\.venv\Scripts\python.exe -m mypy src scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_evaluations.py
.\.venv\Scripts\python.exe scripts\smoke_test.py `
  --start 2026-03-01 --end 2026-04-01
```

Tests use synthetic data and mocked model responses; no live API is required. Coverage
includes duplicate/conflict policy, gaps, timezone conversion, all aggregation
resolutions, partial periods, zero division, power conversion, baseload, peak, load
factor, weekday/weekend, ranking, anomalies, empty/invalid tools, structured
orchestration, four-state guardrails, semantic provenance, deterministic fallback,
pricing, empty/fresh/stale/incremental/interrupted/duplicate/concurrent sync, and the
exact peak regression.

The controlled live command is deliberately opt-in because it is billable:

```powershell
.\.venv\Scripts\python.exe scripts\run_live_evaluations.py `
  --confirm-live --peak-runs 10 --include-assessment
```

It persists no answer values, only workflow status, tool names, grounding, latency,
tokens, and cost. Current evidence is summarized in `EVALUATION_REPORT.md`.

## Scalability

One year at 15-minute resolution across 40 meters is about 1.4 million intervals, within
the intended design:

- one Parquet partition per meter
- entity filters choose meter files before reading
- columnar compression and vectorized Pandas/PyArrow operations
- API calls split into documented 90-day windows
- incremental forward sync and historical backfill
- per-meter atomic writes, resumable failure state, and a cross-process writer lock

The prototype still loads all selected meter partitions into memory for a query. At
substantially larger scale, keep the schema/tool interfaces and replace the cache query
implementation with DuckDB over partitioned Parquet, plus compaction and concurrency
controls.

## Security

- No token or key appears in source, tests, documentation, logs, or example files.
- The local assessment PDF contains a credential and is explicitly ignored.
- `.env`, raw/processed/metadata caches, Parquet, databases, and logs are ignored.
- Request logging contains methods and endpoint paths only; never headers or tokens.
- The access validator does not dump response bodies.
- API error messages do not include credentials or raw payloads.
- No automatic Git initialization, commit, push, or external publication is performed.

The starting folder was not a Git repository, so there was no Git history to audit.
The existing source helper contained an observed organization response in comments; it
was removed from current files.

## Known limitations and production improvements

1. Source site timezone was absent in the validated live list response, so the configured
   timezone is an explicit assumption.
2. Parent/main/submeter topology is absent, so multi-meter sums can double-count.
3. Only documented electricity active power is normalized; other meter kinds are
   discovered but skipped.
4. Negative power/energy is excluded pending explicit import/export semantics.
5. Internal cache gaps need a targeted full refresh.
6. Anomaly detection has no weather, occupancy, event, or maintenance context.
7. No forecasting, tariff/billing prediction, weather normalization, or causal diagnosis.
8. No user authentication, tenancy isolation, encrypted cache, background job queue, or
   production observability.
9. Live OpenAI execution sends structured analytics results to the configured provider.
   Deployment requires an explicit data-governance decision; raw records are never sent.
10. Field provenance proves displayed analytic values, but it cannot prove every
    qualitative sentence's causal interpretation.

Recommended next steps are topology metadata, explicit contextual-denominator adapters,
timezone enrichment, import/export modeling, DuckDB partition pruning, golden datasets,
continuous regression/eval monitoring, and consultant feedback workflows.
