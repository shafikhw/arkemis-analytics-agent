# Intermittent false-refusal diagnosis and fix

## Reproduced failure

The previous `validate_numeric_grounding` implementation serialized tool results,
extracted every number with a regular expression, and compared the answer's independent
numeric tokens with the serialized tokens.

Using the validated June peak result:

```text
tool timestamp: 2026-06-12T16:25:00+00:00
answer timestamp: June 12, 2026 at 4:25 PM UTC
```

The readable answer failed because `4` did not literally match ISO hour `16`. The same
answer using `2026-06-12T16:25:00Z` passed. This explains the intermittency: model
timestamp formatting varied between attempts while the analytics output did not.

After a first validation failure, the old orchestration requested one prose revision.
If the retry used another readable timestamp or otherwise failed literal token matching,
the code discarded the usable final answer and returned:

```text
I could not produce a numerically grounded answer...
```

The tool had succeeded and its result remained valid; synthesis validation was
incorrectly treated as a terminal factual failure.

## Implemented correction

`src/llm/response_validation.py` now validates semantic field provenance:

- timestamps are parsed and normalized across ISO/readable and 12/24-hour forms;
- `Z`, `+00:00`, and `UTC` are equivalent;
- numeric values support commas, units, trailing zeros, configured rounding, relative
  and absolute tolerance;
- ratios may be displayed as percentages, with a separate percentage tolerance;
- each matched value records source tool, source field, and allowed transformation;
- unreturned arithmetic remains unsupported.

`src/llm/orchestrator.py` now implements an explicit result-preserving state machine:

1. structured deterministic-first scope decision;
2. deterministic/constrained tool planning;
3. allow-listed execution;
4. structured tool-result validation;
5. structured answer synthesis;
6. fact-field and semantic numeric validation;
7. one synthesis retry with the same validated outputs and `tools=[]`;
8. deterministic renderer for every primary analytics tool;
9. failure status only when no factual result exists.

No analytics tool is repeated because synthesis failed. The original trace is retained.
A synthesis error cannot mutate scope to unrelated or unsupported.

## Secondary live-evaluation finding

The first post-fix live assessment run exposed a separate period-selection problem for
the period-less week-over-week example. The model chose the newest calendar weeks, but
the newest cache slice contained only partial recent days. The deterministic planner now
searches backward per organization for the latest two contiguous complete cached weeks.
Cross-organization weekend comparison and per-site baseload use the latest common
complete cached month.

## Evidence

- semantic validator regression: readable `4:25 PM UTC` maps to ISO `16:25+00:00`;
- deterministic fallback regression: two invalid syntheses still return the one
  successful tool result and keep one tool trace;
- exact peak question: 10/10 consecutive live successes;
- mocked behavioral suite: 99/99 executed turns with zero false refusals and full numeric
  provenance;
- final live rerun: 5/5 assessment questions answered after complete-period routing.

See `EVALUATION_REPORT.md` and `ASSESSMENT_COMPLIANCE.md`.
