# Evaluation report

Generated for the July 29-30, 2026 assessment verification.

## Reproducible mocked evaluation

Command:

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluations.py
```

The runner uses the real cache, analytics, schemas, scope guard, orchestrator, result
validation, and fallback renderers with a scripted model. It persists no answer text.

| Metric | Result |
|---|---:|
| Executed turns | 99 |
| Peak regression | 10/10 |
| Tool-selection accuracy | 100% |
| Tool-argument accuracy | 100% |
| Answer success | 100% |
| Required/forbidden answer-content checks | 100% |
| Numeric-grounding/provenance pass | 100% |
| False-refusal rate | 0% |
| Clearly unrelated refusal precision | 100% |
| Unsupported-energy handling | 100% |
| Raw-dataset exclusion | 100% |
| Unhandled exceptions | 0 |
| Average latency | 1.470 s |
| Average mocked tokens/query | 745.859 |
| Total mocked estimated cost | $0.22010 |

The corpus contains 72 single-case definitions and nine multi-turn sequences. The peak
question expands to 10 consecutive runs, producing 99 executed turns. Coverage includes
the five assessment examples; metadata discovery; all aggregation levels; every
assessment analytics family; methodology; 10 supported paraphrases; 10 clearly
unrelated/prompt-injection requests; five unsupported energy requests; ambiguous,
missing-data, incomplete-period, malformed-argument, API-error, and multi-tool paths.
It also includes the exact periodless site-ranking, Beta Resort baseload,
typo-preserving Beta Resort baseload, `food crop` alias, full site/meter listing, and
standalone-query context-isolation regressions.

### Expanded-corpus failures retained and corrected

The first 99-turn run exposed three failures:

1. The all-meter answer had correct names but did not label the measurement-type field
   explicitly. The deterministic renderer now emits `type: electricity` (or the
   returned alternate type).
2. `Show monthly consumption for all organizations...` was misread as discovery
   because the discovery regex allowed arbitrary text between `show` and
   `organizations`. Discovery wording is now adjacency-constrained.
3. `What cached data coverage is available for that site?` unnecessarily planned
   `list_sites` before `get_data_availability`. An explicit availability intent now
   selects only the availability tool while resolving `that site` from history.

The affected cases and then the complete corpus were rerun. The final 99-turn report
has no failures.

## Controlled live GPT-5.6 Terra evaluation

Standard short-context rates were used. Answer values were not persisted.

### Run 1: original reliability workflow

- 15/15 answered
- 10/10 peak regression
- zero false refusals
- 15 deterministic fallbacks
- cost: `$0.519906`

This safe result identified that all model syntheses were being rejected by fact-field
timestamp validation.

### Diagnostic

One structured peak synthesis isolated the rewrapping bug described in
`docs/RELIABILITY_FIX.md`.

- cost: `$0.0081575`

### Run 2: timestamp-provenance fix

- 10/10 peak regression
- zero false refusals
- 14/15 answered
- four deterministic fallbacks
- one assessment question returned `data_unavailable`
- cost: `$0.27813075`

The failed assessment case was the period-less week-over-week comparison. The newest
cache slice did not contain two complete weeks.

### Affected assessment rerun

After deterministic complete-period routing:

- 5/5 assessment questions answered
- zero false refusals
- two deterministic fallbacks
- cost: `$0.1236875`

### In-scope query and presentation follow-up

After a larger cache refresh exposed fuzzy meter matching, the expanded mocked suite
initially selected the non-energy `HDD Food corp` metadata meter for questions naming
Food Corp. That failed run was retained. Fuzzy matching is now limited to organizations
and sites; meters require an exact name or stable ID.

- earlier expanded mocked suite after fuzzy-entity correction: 58/58;
- exact new live regressions: 4/4 answered, zero fallbacks/refusals, cost `$0.0603125`;
- full assessment live rerun: 5/5 answered, zero refusals, cost `$0.1141625`.

### Total live-evaluation cost

`$1.10435675`

This total includes both original full runs, the one-call diagnosis, both assessment
reruns, and the four new exact-query regressions. Failures were retained and diagnosed
rather than omitted. The July 30 metadata-listing work made no additional live-model
calls, so it added `$0.00` to this total; deterministic metadata rendering was verified
against the real cache and Streamlit test runtime.

## Targets

| Target | Status |
|---|---|
| Zero false refusals for clearly supported cases | Met |
| 100% numeric provenance | Met |
| 100% refusal for clearly unrelated cases | Met |
| 100% safe limitation handling | Met |
| Peak regression 10/10 | Met |
| No raw dataset sent to the model | Met |
| No credentials exposed | Met |
| No unhandled UI/orchestration exception | Met in automated and smoke checks |
