# Presentation notes

## Ten-minute best-case demo

### 0:00-1:00 - State the contract

"The model interprets; Python calculates. Raw intervals never enter the model context,
and every displayed energy number can be traced to an allow-listed deterministic tool."

Show `.env.example` and `.gitignore`, not `.env`.

### 1:00-2:00 - Validate and inspect

```powershell
.\.venv\Scripts\python.exe scripts\validate_access.py
.\.venv\Scripts\python.exe scripts\inspect_cache.py
```

Explain normalized name matching and exact stable ID retention. Mention that the API
uses the plural `Best Resorts Hotels`, while the brief uses the singular.

### 2:00-3:00 - Launch

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Point out cache freshness, last successful synchronization, failed meters,
conversation history, and the trace expander. Use **Refresh data** to demonstrate the
non-blocking synchronization lock. Explain that refreshes request only new or changed
meter intervals, deduplicate observations, write atomically, and retain the last valid
cache if the API is unavailable.

### 3:00-5:00 - Consumption and grounding

Ask: "What was total consumption at Food Corp. last month?"

Open the trace. Show explicit date boundaries, entity filter, result unit, completeness,
and timezone assumption. Emphasize that the final wording is model-authored but the
value is not.

Then ask: "When did Food Corp. reach peak demand in June 2026?"

Show that the deterministic router selects `get_peak_demand`, the structured result is
validated once, and readable timestamps and rounded values retain field-level
provenance. If structured synthesis fails twice, the same successful tool result is
rendered deterministically rather than discarded. This regression passed 10
consecutive live executions.

### 5:00-6:30 - Operational profile

Ask: "How does weekend consumption compare between the two organizations in March
2026?"

Explain local-date classification. The cached March sample showed a weekend/weekday
average-day ratio of approximately 1.258 for Food Corp. and 1.004 for Best Resorts
Hotels. Present this only as profile shape. The hotel selection contains multiple meter
streams and may contain overlap; it is not an efficiency comparison.

### 6:30-7:30 - Baseload

Ask: "What is the baseload at each site in March 2026?"

Explain the per-meter 10th percentile, site summation, and energy-above-baseline
decomposition. In the validated cache, site estimates differ materially, but Alpha and
Beta combine many streams, so topology overlap is a first-class caveat. Baseload is an
estimate, not a measured physical quantity.

### 7:30-8:30 - Anomaly and data quality

Ask: "Was anything unusual about Best Resorts Hotels in March 2026?"

Show hour-of-week median/MAD/IQR evidence and the affected meter/timestamp. Then ask:
"Which sites had incomplete data in March 2026?" Point out that gaps are quality events,
not low-energy anomalies.

### 8:30-9:15 - Safe limitation

Ask: "Is Best Resorts Hotels more energy efficient than Food Corp.?"

Expected answer: no defensible efficiency claim is possible from raw kWh. Floor area,
occupancy/guest nights, production, weather, and verified topology/denominators are
needed.

### 9:15-10:00 - Close on production path

Show the model, service tier, input/cached/cache-write/output tokens, estimated cost,
pricing source, and pricing date. Summarize: topology metadata, timezone enrichment,
contextual denominators, DuckDB, structured final provenance, golden datasets, and
consultant-review monitoring.

## Five-minute deliberately weak example

Question: "Predict next year's electricity bill for Best Resorts Hotels and weather
normalize it."

Why the system handles it badly by design:

1. The cache has electricity observations, not a validated tariff model.
2. It has no future weather forecast or weather-normalization model.
3. It has no occupancy/business forecast.
4. The current tools do not forecast or price.
5. Any numeric answer would be fabricated.

The correct behavior is a concise refusal of the calculation, followed by the missing
inputs and the supported historical analyses. This is a safety success, not a demo
failure.

## Key architecture decisions

- Separate remote extraction from interactive questions.
- Combine deterministic capability/entity/metric matching with a structured
  four-state scope decision; a suitable deterministic tool match overrides an
  uncertain classifier refusal.
- Use exact API IDs internally; names are discovery/display aliases.
- Store UTC, group in local time, and surface assumptions.
- Convert active power to interval kWh only with a known/inferred reliable interval.
- Partition Parquet by meter for practical pruning and atomic recovery.
- Synchronize incrementally under a file lock and preserve the last known-good cache.
- Keep analytics as typed pure-ish functions over canonical frames.
- Expose many narrow tools, never arbitrary SQL/code.
- Bound model rounds and preserve every call/result link, including synthesis retries.
- Validate answer values semantically against explicit source fields, with timestamp,
  unit, ratio/percentage, and configured rounding normalization.
- Fall back to deterministic tool-specific rendering after two invalid synthesis
  attempts, without executing the analytics tool again.
- Warn about absent meter topology rather than hiding possible double counting.

## Raw data and privacy

The model needs intent, tool definitions, and compact structured results. It does not
need hundreds of thousands of intervals. Keeping raw data local reduces context size,
cost, leakage risk, and the chance that the model performs uncontrolled arithmetic.
Deployment still needs approval to send derived client analytics to an external LLM.

## Baseload definition and limitations

The 10th percentile is robust to isolated spikes and makes no shared operating-hours
assumption. It can still be distorted by shutdowns, missing intervals, export, or mixed
meter topology. It is a statistical benchmark, not guaranteed essential load.

## Anomaly definition and limitations

Same-local-hour-of-week median establishes an explainable weekly reference. Scaled MAD
resists outliers; IQR is the fallback when MAD is zero. It misses slow drift, seasonal
change, and contextual causes. Near-zero baselines can produce very large robust scores
for modest absolute changes, so consultants must inspect actual deviation and meter
context, not score alone.

## Incomplete data behavior

- Missing is never zero.
- Exact and conflicting duplicates are counted separately.
- Conflicts and invalid observations are excluded.
- Every aggregate includes expected/observed counts and partial status.
- Comparison periods keep separate completeness.
- Gaps are never labeled energy anomalies.

## Scalability

Forty meters at 15-minute resolution for one year is about 1.4 million rows. Per-meter
Parquet, 90-day remote windows, vectorized analytics, and incremental/backfill state are
adequate. For larger portfolios, move cache queries to DuckDB without changing the tool
contracts.

## Actual-data observations (bounded and caveated)

These observations came from the locally downloaded March 2026 cache, not invented
examples:

- Food Corp.'s average daily consumption was about 2,626.55 kWh/day over the selected
  electricity stream, with about 99.96% interval completeness.
- Best Resorts Hotels' summed meter-stream average was about 2,716.63 kWh/day, with
  about 99.69% completeness. Because parent/submeter topology is absent, this sum may
  double-count and must not be called organization efficiency.
- The weekend/weekday average-day ratio was about 1.258 for Food Corp. and 1.004 for
  Best Resorts Hotels, suggesting a stronger weekend shift in the Food Corp. stream and
  a flatter hotel portfolio shape.
- Coincident load factor was about 0.578 for Food Corp. and 0.668 for the summed hotel
  streams. This is an operational-shape observation subject to the same topology caveat.
- Source timezone metadata was unavailable; these profiles used the configured UTC
  assumption and must be rerun after timezone enrichment.

Do not generalize from one month or infer business causes without operational context.

## Detecting wrong consultant-facing answers

1. Deterministic calculations remain the source of truth.
2. Attach field-level provenance IDs to final structured answers.
3. Retain tool calls, validated arguments, results, model/version, and prompt version.
4. Require completeness and assumption indicators.
5. Run regression questions on every code/prompt/model change, including 10
   consecutive executions of the peak-demand false-refusal case.
6. Maintain synthetic golden datasets for exact edge-case values.
7. Check invariants: ratios in range, totals equal component sums, no missing-as-zero,
   no invalid units, comparison periods equal duration when intended.
8. Compare sampled tool output with direct DuckDB/SQL queries.
9. Alert when final text contains numeric tokens absent from tool output.
10. Capture user corrections and thumbs-down reasons.
11. Sample high-impact answers for consultant review.
12. Monitor tool-selection distributions, empty/error rates, grounding retries,
    completeness, and answer-quality graders over time.

## Known limitations

See README for the complete list. The presentation-critical limitations are missing
meter topology, assumed timezone, active-power-only normalization, no validated
denominators, no forecasting/weather/tariff tools, and finite live-model evaluation
coverage. Semantic provenance validates existing tool fields and approved formatting
transformations; it intentionally rejects new model-authored arithmetic.
