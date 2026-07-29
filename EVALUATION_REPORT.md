# Evaluation report

Generated for the July 29, 2026 assessment verification.

## Reproducible mocked evaluation

Command:

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluations.py
```

The runner uses the real cache, analytics, schemas, scope guard, orchestrator, result
validation, and fallback renderers with a scripted model. It persists no answer text.

| Metric | Result |
|---|---:|
| Cases | 54 |
| Peak regression | 10/10 |
| Tool-selection accuracy | 100% |
| Tool-argument accuracy | 100% |
| Answer success | 100% |
| Numeric-grounding/provenance pass | 100% |
| False-refusal rate | 0% |
| Clearly unrelated refusal precision | 100% |
| Unsupported-energy handling | 100% |
| Raw-dataset exclusion | 100% |
| Unhandled exceptions | 0 |
| Average latency | 1.006 s |
| Average mocked tokens/query | 702.963 |
| Total mocked estimated cost | $0.11315 |

The corpus includes the five assessment examples, 10 supported paraphrases, 10 clearly
unrelated/prompt-injection requests, five unsupported energy requests, ambiguous,
missing-data, malformed-argument, tool-empty, API-error, multi-tool, and five multi-turn
follow-up sequences.

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

### Total live-evaluation cost

`$0.92988175`

This total includes both full runs, the one-call diagnosis, and the affected-case rerun.
Failures were retained and diagnosed rather than omitted.

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
