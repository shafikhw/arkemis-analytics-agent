# Final verification report

Executed on July 29, 2026 from the assessment workspace. The commands below are the
actual final verification commands, not suggested commands.

## Code quality

| Check | Command | Result |
|---|---|---|
| Formatting | `python -m ruff format src tests scripts app.py list_wattics_orgs.py` | Pass; 62 files unchanged |
| Formatting check | `python -m ruff format --check src tests scripts app.py list_wattics_orgs.py` | Pass; 62 files formatted |
| Lint | `python -m ruff check src tests scripts app.py list_wattics_orgs.py` | Pass; all checks passed |
| Static typing | `python -m mypy src scripts` | Pass; no issues in 51 source files |
| Dependency consistency | `python -m pip check` | Pass; no broken requirements |
| Credential scan | `rg` high-confidence credential patterns, excluding `.env`, private data, virtual environment, PDF, and VCS metadata | Pass; zero matching source files |

All `python` commands used `.\.venv\Scripts\python.exe`.

## Automated tests

| Suite | Command | Result |
|---|---|---:|
| Unit/data/analytics/scalability | `python -m pytest tests\test_aggregation.py tests\test_analytics.py tests\test_cleaning.py tests\test_quality.py tests\test_extraction.py tests\test_scalability.py -q` | 27 passed |
| Integration/tool/SDK | `python -m pytest tests\test_discovery.py tests\test_wattics_client.py tests\test_tools.py tests\test_openai_sdk_contract.py -q` | 14 passed |
| Orchestration/fallback | `python -m pytest tests\test_orchestration.py tests\test_fallback_renderers.py -q` | 7 passed |
| Guardrail/provenance | `python -m pytest tests\test_scope.py tests\test_response_validation.py -q` | 14 passed |
| Cost accounting | `python -m pytest tests\test_usage_tracking.py -q` | 4 passed |
| Synchronization/data integrity | `python -m pytest tests\test_sync_manager.py tests\test_extraction.py tests\test_cleaning.py -q` | 17 passed |
| Full suite | `python -m pytest -q` | 75 passed |

The synchronization manager was rerun independently after its persisted-status and
dead-owner lock recovery fixes: 9/9 tests passed, and the full 75-test suite remained
green.

## Evaluation and smoke tests

- `python scripts\run_evaluations.py`: 54/54 behavioral cases met expectations;
  100% tool selection, argument accuracy, answer success, numeric provenance,
  out-of-scope precision, and unsupported-energy handling; zero false refusals and
  unhandled exceptions; peak regression 10/10.
- `python scripts\smoke_test.py --start 2026-03-01 --end 2026-04-01`: organization,
  availability, consumption, weekday/weekend, and site-ranking probes all returned
  `status: ok`.
- Streamlit was launched headlessly and probed over localhost: HTTP 200 with a
  10,626-byte response.
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
- Total live-evaluation cost: `$0.92988175`.

No additional billable calls were made for the final documentation/status-only fix.

## Refresh follow-up

A reported manual-refresh failure was traced to two independent environmental states:

1. The Codex filesystem sandbox also restricted outbound Wattics traffic. A
   metadata-only access check failed inside that sandbox but succeeded immediately with
   approved network access, confirming the token, endpoint, and API were valid.
2. A force-terminated local UI process had left `sync.lock` owned by a dead PID. The
   lock previously depended only on its 15-minute timeout.

`FileSyncLock` now records PID and hostname and immediately reclaims a lock whose local
owner is no longer running. Live owners remain protected, and remote/unreadable locks
retain age-based recovery. An actual locked incremental refresh then completed with
zero failed meters, persisted success/fresh status, advanced common cache coverage
through `2026-07-29T18:15:00Z`, and removed its lock.
