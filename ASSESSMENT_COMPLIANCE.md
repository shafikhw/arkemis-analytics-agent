# Assessment compliance review

Authoritative source: `AI Developer - Technical Assessment.pdf`, read in full before
this implementation pass. Status reflects executed evidence, not compile-only claims.

## Assessment sections

| Assessment requirement | Implementation status | Relevant files | Tests or evidence | Known limitations |
|---|---|---|---|---|
| 1. Data extraction across both organizations | Implemented | `src/api/wattics_client.py`, `src/data/discovery.py`, `src/data/extraction.py`, `scripts/sync_data.py` | `test_wattics_client.py`, `test_discovery.py`, `test_extraction.py`; live hierarchy/cache inspected | API source currently enables documented active power; non-electric meters remain metadata-only |
| 1. Dynamic site/meter discovery | Implemented | `src/data/discovery.py`, `src/data/schemas.py`, `src/llm/intent_routing.py`, `src/llm/fallback_renderers.py` | Discovery tests; deterministic UI regressions enumerate all cached organization/site/meter names | Similar organization name is explicitly reported; no hidden hardcoded IDs |
| 1. Local caching; no API per question | Implemented | `src/data/cache.py` | Cache/tool tests; queries read Parquet only | Per-query selected partitions are loaded into memory |
| 2. Missing intervals, gaps, duplicates | Implemented | `src/data/cleaning.py`, `src/data/quality.py`, `src/data/extraction.py` | Cleaning, quality, duplicate-sync, interrupted-sync tests | Incremental boundary sync does not repair an old internal gap automatically; targeted full refresh does |
| 2. Timestamp/timezone consistency | Implemented | `src/data/extraction.py`, `src/analytics/common.py` | Aggregation, analytics, quality tests | Source timezone is absent for some sites; configured IANA timezone is visibly labeled as assumed |
| 2. Hourly/daily/weekly/monthly aggregation | Implemented | `src/data/aggregation.py`, `src/analytics/consumption.py` | `test_aggregation.py` | Calendar semantics follow local operational time |
| 2. Cross-organization structure | Implemented | Canonical schema in `src/data/schemas.py`; comparison tools | Analytics/tool/evaluation tests | Parent/submeter topology is unavailable, so overlap warnings are required |
| 3. Total and average consumption | Implemented | `src/analytics/consumption.py` | Analytics/tool/evaluation tests | Partial periods are reported, never silently annualized |
| 3. Period-over-period absolute/percent change | Implemented | `src/analytics/comparison.py` | Analytics and evaluation tests | Percentage is unavailable when the prior value is zero |
| 3. Baseload and operational load | Implemented | `src/analytics/baseload.py` | Analytics tests; assessment live rerun | Per-meter 10th-percentile statistical estimate, not a physical measurement |
| 3. Peak demand and timestamp | Implemented | `src/analytics/peaks.py` | Exact question 10/10 live; semantic timestamp regressions | Demand is derived from active power where no direct demand channel exists |
| 3. Load factor | Implemented | `src/analytics/load_factor.py` | Analytics/tool tests | Mixed native intervals are rejected unless a safe common interval exists |
| 3. Weekday/weekend profile | Implemented | `src/analytics/profiles.py` | Analytics and evaluation tests | Saturday/Sunday definition; no holiday calendar |
| 3. Site ranking | Implemented | `src/analytics/ranking.py` | Analytics/tool/evaluation tests | Raw kWh ranking is scale-dependent and never labeled efficiency |
| 3. Anomaly detection | Implemented | `src/analytics/anomalies.py` | Analytics and live evaluation | Same local hour-of-week robust z-score using scaled MAD/IQR; cannot explain causes or gradual drift |
| 4. Explicit typed tool layer | Implemented | `src/tools/schemas.py`, `src/tools/registry.py`, `src/tools/energy_tools.py` | Tool-schema, malformed-argument, SDK-contract tests | JSON Schema is runtime validated; Python handlers use flexible result dictionaries |
| 5. LLM tool orchestration | Implemented | `src/llm/orchestrator.py`, `src/llm/intent_routing.py` | Orchestration, SDK contract, mocked and live evaluations | Complex planning remains model-assisted; deterministic plans cover obvious and assessment-critical intents |
| 5. Every number computed by code | Implemented | `src/llm/response_validation.py`, `src/llm/result_validation.py`, `src/llm/fallback_renderers.py` | Provenance/rounding/timestamp/no-new-arithmetic tests; 100% mocked grounding | Qualitative causal language cannot be proven solely by numeric provenance |
| 5. Raw data not handed to model | Implemented | Tool outputs expose aggregates/analytics only; native series withheld | Evaluation raw-dataset exclusion 100%; security scan | Structured anomaly records can include individual flagged intervals, not the raw corpus |
| 5. Out-of-scope handling | Implemented | `src/llm/scope.py` | 10/10 clearly unrelated cases; injection tests | Novel ambiguous language may ask clarification rather than refuse |
| 6. Web UI, question, answer, history | Implemented | `app.py`, `src/ui/streamlit_app.py` | Streamlit HTTP 200 plus rendered-browser control/status check with zero console errors | No production authentication or multi-tenant isolation |
| 6. Visible tool trace bonus | Implemented | `src/ui/streamlit_app.py`, `ToolTraceEntry` | UI smoke and orchestration tests | Result trace is summarized to avoid raw/private data exposure |
| 7. Missing/incomplete/empty behavior | Implemented | Analytics empty results, result validation, orchestration statuses | Missing-data, empty-tool, incomplete-period tests/evals | No interpolation of missing energy |
| 7. Wattics and LLM API errors | Implemented | `src/api/wattics_client.py`, `src/data/sync_manager.py`, `src/llm/orchestrator.py` | API mocks, stale-cache failure, synthesis-error fallback | Repeated upstream outage leaves an explicitly stale cache |
| 7. One year x 40 meters architecture | Implemented by design | Per-meter Parquet, 90-day windows, vectorized analytics, bounded model outputs | `tests/test_scalability.py` aggregates a full 35,040-row meter-year and verifies the 1,401,600-interval portfolio target | Larger deployments should use DuckDB/partition pruning instead of in-memory Pandas concatenation |
| 7. Token/cost accounting bonus | Implemented | `src/llm/usage_tracking.py`, `src/config.py`, UI | Exact `$0.030255` regression; live cost reports | Regional/data-residency uplifts are not applied unless configured |
| 7. Test questions bonus | Implemented | `evals/evaluation_cases.json`, `docs/EVALUATION_QUESTIONS.md` | 99-turn mocked suite; exact-query and assessment controlled live reruns | Live model calls are deliberately opt-in and billable |
| 8. Repository/readme/demonstration material | Implemented | `README.md`, `PRESENTATION_NOTES.md`, this review | Formatting/lint/type/test/eval/smoke commands executed | The supplied workspace had no `.git` directory; no repository publication was requested |

## Additional verification checklist

| Requirement | Status | Evidence | Limitation |
|---|---|---|---|
| Automatic incremental updates | Implemented | `AutoSyncManager`; empty/fresh/stale/success/failure tests | Initial population uses configured lookback |
| Per-meter resume after interruption | Implemented | State written after every successful meter; interrupted update test | A failed meter is retried on the next run |
| Atomic writes and previous-cache preservation | Implemented | Temp-file + `os.replace`; failure tests | Filesystem must support atomic replace within the cache volume |
| Concurrent refresh protection | Implemented | `FileSyncLock`; simultaneous-active, dead-owner recovery, and stale-lock tests; successful live locked refresh | Remote/unreadable locks use the configurable age threshold |
| Cache status/freshness/failed meters in UI | Implemented | Rendered-browser verification of four status metrics, captions, stale warning, and manual refresh | Streamlit refresh is synchronous but bounded |
| Data-current timestamp and stale/fresh label | Implemented | `latest_cached_observation` and freshness in the dashboard status area | It is cache-wide, not a per-answer minimum across selected meters |
| Four exact scope states with confidence/reason | Implemented | `ScopeDecision`; evaluation records | Internal decision state is intentionally not rendered to consultants |
| Deterministic capability/entity/date/term checks | Implemented | `scope.py`, `intent_routing.py`, cache alias resolver | Not a general semantic ontology |
| Contextual follow-ups | Implemented | History-aware scope and direct period/entity parsing; nine sequences including standalone-query context isolation | Very long histories are limited to recent turns |
| False-refusal prevention state machine | Implemented | One retry, no tool re-execution, deterministic fallback | Fallback wording is structured rather than stylistically rich |
| Primary-tool fallback renderers | Implemented | All 11 required analytics names plus four metadata/availability names registered and tested | Unknown extension tools receive a generic scalar summary |
| Structured final answer | Implemented | Strict `AnswerEnvelope` JSON Schema | Falls back safely if a provider/model cannot honor the schema |
| Semantic timestamps/rounding/percentages | Implemented | Validator regressions and live diagnosis | Tolerances are configurable and should be monitored |
| Fact-to-tool-field provenance | Implemented | `source_tool`, JSONPath resolution, provenance records | Non-numeric text uses exact/contained source text matching |
| GPT-5.6 Terra Standard pricing | Implemented | Central config, API `default` tier translation, UI display | Price table must be reviewed when OpenAI pricing changes |
| Conversation history | Implemented | Streamlit session state | No durable server-side history |
| Security/credential handling | Implemented | `.gitignore`, redacted errors, raw-data exclusion, credential scan | Local cache encryption is not included |
| README completeness | Implemented | Setup, architecture, methodology, sync, pricing, tests, limitations | Deployment hardening remains outside prototype scope |
| Presentation notes | Implemented | Demo flow, weak example, design defenses, monitoring discussion | Live observations depend on the current private cache |

## Final assessment summary

All eight assessment sections are implemented and exercised. The core reliability
defect was reproduced and traced to literal timestamp token comparison, then corrected
with semantic field provenance and a result-preserving synthesis fallback. The final
mocked evaluation meets every requested target; the exact peak question succeeded 10
consecutive times against the configured live model; and all five assessment examples
answered in the final affected-case live rerun.

Remaining limitations are explicit: missing source timezone/topology/contextual
denominators, no forecasting/tariffs/weather/carbon factors, in-memory selected-partition
queries, no production identity/tenancy, and cache-wide rather than per-answer freshness
coverage.
