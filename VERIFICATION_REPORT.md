# Final verification report

Executed on July 29-30, 2026 from the assessment workspace. The commands below are the
actual final verification commands, not suggested commands.

## Code quality

| Check | Command | Result |
|---|---|---|
| Formatting | `python -m ruff format src tests scripts app.py list_wattics_orgs.py` | Pass; four newly edited files reformatted |
| Formatting check | `python -m ruff format --check src tests scripts app.py list_wattics_orgs.py` | Pass; 62 files formatted |
| Lint | `python -m ruff check src tests scripts app.py list_wattics_orgs.py` | Pass; all checks passed |
| Static typing | `python -m mypy src scripts` | Pass; no issues in 52 source files |
| Dependency consistency | `python -m pip check` | Pass; no broken requirements |
| Credential scan | `rg` high-confidence credential patterns, excluding `.env`, private data, virtual environment, PDF, and VCS metadata | Pass; zero matching source files |

All `python` commands used `.\.venv\Scripts\python.exe`.

## Automated tests

| Suite | Command | Result |
|---|---|---:|
| Unit/data/analytics/scalability | `python -m pytest tests\test_aggregation.py tests\test_analytics.py tests\test_cleaning.py tests\test_quality.py tests\test_extraction.py tests\test_scalability.py -q` | 27 passed |
| Integration/tool/analytics (latest focused run) | `python -m pytest tests\test_tools.py tests\test_analytics.py -q` | 12 passed |
| Orchestration/SDK (latest focused run) | `python -m pytest tests\test_orchestration.py tests\test_openai_sdk_contract.py -q` | 9 passed |
| Guardrails/routing (latest focused run) | `python -m pytest tests\test_scope.py -q` | 10 passed |
| Cost accounting/UI caption | `python -m pytest tests\test_usage_tracking.py -q` | 5 passed |
| Synchronization/data integrity | `python -m pytest tests\test_sync_manager.py tests\test_extraction.py tests\test_cleaning.py -q` | 17 passed |
| Full suite | `python -m pytest -q` | 85 passed |

The synchronization manager was rerun independently after its persisted-status and
dead-owner lock recovery fixes: 9/9 tests passed, and the full 85-test suite remained
green.

## Evaluation and smoke tests

- `python scripts\run_evaluations.py`: 99/99 executed turns met expectations; 100%
  tool selection, argument accuracy, answer success, required answer content, numeric
  provenance, out-of-scope precision, and unsupported-energy handling; zero false
  refusals and unhandled exceptions; peak regression 10/10.
- `python scripts\smoke_test.py --start 2026-03-01 --end 2026-04-01`: organization,
  availability, consumption, weekday/weekend, and site-ranking probes all returned
  `status: ok`.
- Streamlit was launched headlessly and probed over localhost: HTTP 200.
- Streamlit `AppTest` submitted `List sites` through the actual UI entry point and
  verified `Organic Farm`, `Alpha Hotel`, and `Beta Resort & Spa`; no scope-decision
  section was rendered and no application exception occurred.
- The rendered app was then inspected in a browser. Synchronization and freshness
  metrics, last-success/latest-observation metadata, the stale-cache warning, Refresh
  data, question input, and send-state behavior were present. The unique Refresh and
  question controls were visible and enabled, the empty-question send control was
  disabled, and the browser console contained zero warnings or errors.
- `python scripts\inspect_cache.py`: hierarchy present, 34 processed meter files, a
  persisted successful-sync timestamp, and zero failed meters. The final live startup
  refresh could not reach the Wattics API, so status was correctly persisted as
  `failed` while the previous cache remained readable and explicitly stale.
- The controlled browser tab and exact launched process were closed after verification.

The first Windows UI probe wrapper failed before application launch because
`Start-Process` encountered duplicate case-insensitive `Path`/`PATH` environment keys.
The final probe used `System.Diagnostics.Process` with no shell and succeeded. This was
a test-harness issue; no application exception occurred.

## Controlled live-model evidence

The live GPT-5.6 Terra runs are detailed in `EVALUATION_REPORT.md`.

- Initial safe run: 15/15 answered, peak 10/10, cost `$0.519906`.
- One-call field-provenance diagnosis: cost `$0.0081575`.
- Post-fix run: peak 10/10, zero false refusals, cost `$0.27813075`; one incomplete
  week-over-week case exposed period selection.
- Final affected assessment rerun after complete-period routing: 5/5 answered, cost
  `$0.1236875`.
- Exact periodless/typo in-scope live regressions: 4/4 answered with zero fallbacks or
  false refusals; cost `$0.0603125`.
- Final five-question assessment rerun: 5/5 answered with zero false refusals; cost
  `$0.1141625`.
- Total live-evaluation cost: `$1.10435675`.

## In-scope query presentation follow-up

- Scope decisions remain available internally for logging/evaluation but are not
  rendered in the UI.
- Per-answer pricing-source URLs and cache-freshness footers were removed. Token/cost
  captions appear only when usage exists.
- Periodless ranking and baseload questions deterministically use the latest closed
  cached month.
- Organization/site aliases tolerate safe wording errors such as `food crop`, while
  meter names require exact resolution to avoid selecting contextual numeric meters.
- Structured model answers and fallbacks normalize long decimal artifacts to the
  configured three-place display precision.
- Empty analytics results are labeled `empty` in the trace, not `success`.
- Multi-organization period fallback identifies the organization with the larger
  change rather than listing disconnected tool summaries.

The current Streamlit build returned HTTP 200. Static UI checks confirmed that `Scope
decision`, `source:`, `Answer used`, and `Token usage and cost unavailable` are absent
from the rendering code. A fresh browser-level inspection was blocked before navigation
by a local Codex browser-helper permission error; the earlier rendered-browser smoke
evidence remains recorded above, and the current rendered path passed Streamlit
`AppTest`.

## Metadata-listing and context-isolation follow-up

- `list_organizations`, `list_sites`, `list_meters`, and
  `get_data_availability` now have complete deterministic renderers.
- Obvious discovery questions use constrained direct plans and do not make a
  live-model call.
- The exact real-cache prompts `What organizations are available?`, `What sites and
  meters are available?`, `List sites`, `What sites does food crop have?`, and `What
  sites does Best Resorts Hotels include?` all returned the correct entity names and
  resolved tool arguments.
- Standalone commands such as `Rank sites` no longer inherit an organization from an
  unrelated preceding turn; explicit follow-ups such as `that site` and `same period`
  still use recent conversation context.
- The first expanded evaluation exposed three routing/content defects. Each was
  corrected and the complete 99-turn suite was rerun successfully; details are in
  `EVALUATION_REPORT.md`.

## Refresh follow-up

A reported manual-refresh failure was traced to two independent environmental states:

1. The Codex filesystem sandbox also restricted outbound Wattics traffic. A
   metadata-only access check failed inside that sandbox but succeeded immediately with
   approved network access, confirming the token, endpoint, and API were valid.
2. A force-terminated local UI process had left `sync.lock` owned by a dead PID. The
   lock previously depended only on its 15-minute timeout.

`FileSyncLock` now records PID and hostname and immediately reclaims a lock whose local
owner is no longer running. Live owners remain protected, and remote/unreadable locks
retain age-based recovery. The final actual incremental refresh completed successfully
at `2026-07-29T21:58:38.774804+00:00`, with zero failed meters, persisted
success/fresh status, common cache coverage through
`2026-07-29T21:45:00+00:00`, and no retained error. The refresh CLI now parses
standard `--help` before loading configuration or changing synchronization state.
