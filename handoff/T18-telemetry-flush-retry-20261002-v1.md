# T18 telemetry flush retry diagnosis — 2026-10-02 v1

## Scope and safety

Candidate-only worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. This task changed only the targeted telemetry writer retry hunk, added one regression test, and added one handoff reproducer. Existing dirty changes remain. T18 did not read, edit, or test root in this task. HUB ignored.

Original test `tests/test_telemetry_privacy.py::test_error_telemetry_persists_classification_without_exception_text` remains unchanged; candidate SHA-256 `A33405560C715B20A621A243CBA6B26451FC38DB0CB1EDA43957ED978DAB3917`. Its `flush(1)` assertion and all privacy expectations remain intact.

## Diagnosis

The previous root batch receipt records the failure at `assert store.flush(1)` before privacy assertions. It did not capture writer counters or the writer exception, so it cannot prove which event triggered the original incident.

A controlled candidate regression reproduces the same failure point with one transient `sqlite3.OperationalError("database is locked")`:

1. `_writer_loop` keeps failed rows in `batch` and schedules a one-second first retry (`flush_interval_seconds` default `0.5`, multiplied by `2`).
2. A flush already waiting with a one-second deadline can time out before that retry commits.
3. Before the fix, the next loop also blocked on an empty `queue.get(timeout=0.5)` despite holding the failed batch, adding another half-second before retry.

The injected busy error gives deterministic evidence for this failure mechanism. The original root run lacked writer diagnostics, so attribution to that exact transient remains unconfirmed.

## Change

`src/local_ai_hub/telemetry.py` now retries a held batch without waiting for another queue item. Busy retry delay starts at the configured flush interval and grows linearly to the existing one-second cap. With default interval `0.5`, delays are `0.5s`, then `1.0s`; stopping behavior remains `0.05s`.

New `tests/test_telemetry_flush_retry_t18.py` injects one busy failure, preserves `flush(1)` success expectation, asserts retry occurs without an idle blocking queue read, and confirms error row persistence. Original privacy test was not modified.

## Patch and pins

Patch: `handoff/T18-telemetry-flush-retry-20261002-v1.patch`

SHA-256: `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`

The patch includes only the two writer-loop hunks and new regression test (2 paths, 56 insertions, 6 deletions). It is generated against candidate HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`, source HEAD blob `457ae7e184b4b5dfa72eb8fde7fa7c63970e9932` (raw SHA-256 `511BF72684B557A8842EAE77ADFDFAE1EE93B82D98C27C87FD02260ECDD037C0`). T20 must apply-check against current root before integration; this task ran no root command.

Current candidate hashes:

- `src/local_ai_hub/telemetry.py`: `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`.
- `tests/test_telemetry_flush_retry_t18.py`: `5D584579BF3927A4D93EAE2EB8EC97DEF3C16720A84EFA48C2276DAB317C83EC`.
- `tests/test_telemetry_privacy.py` (unchanged): `A33405560C715B20A621A243CBA6B26451FC38DB0CB1EDA43957ED978DAB3917`.
- `handoff/repro_telemetry_flush_false_t18.py`: `6CD9B0E5B4A24BA7A98AAE61FCF2787CB536C72417FB1DAF3FF49930E53C881B`.

`git apply --reverse --check` passed against candidate current tree. `git diff --check -- src/local_ai_hub/telemetry.py` exited 0. Neither check changes files.

## Validation receipts

Before source fix, controlled regression failed at `assert store.flush(1)` (1 failed, 1.31s after the idle-wait change; earlier red also failed at the same assertion, 1 failed, 1.80s). This established the retry-delay part independently.

After fix, strict targeted selector:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_flush_retry_t18.py tests/test_telemetry_privacy.py::test_error_telemetry_persists_classification_without_exception_text tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py
10 passed in 6.33s
```

Full T18 candidate selector plus regression test, `T18_ROOT_*` variables cleared:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_flush_retry_t18.py tests/test_dashboard_mode_playwright_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_status_diagnostics_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_telemetry_timeline_paging_t18.py tests/test_status_snapshot_quality.py::test_realtime_status_surfaces_stored_sqlite_error_summary tests/test_dashboard_operational_surfaces.py::test_dashboard_exposes_activity_mode_and_reports_http_failures tests/test_dashboard_operational_surfaces.py::test_dashboard_requires_server_confirmation_before_reporting_mode_update tests/test_dashboard_operational_surfaces.py::test_status_poller_respects_visibility_unchanged_state_and_jitter tests/test_dashboard_operational_surfaces.py::test_dashboard_api_fetch_has_bounded_request_timeout tests/test_dashboard_operational_surfaces.py::test_dashboard_wires_status_refreshes_through_backoff_poller
66 passed in 19.83s
```

Stress reproducer command `python -B handoff/repro_telemetry_flush_false_t18.py`: 50 iterations, 0 flush failures. This is separate from the deterministic injected-busy regression.

## Remaining gate

T20 must apply-check, integrate, and run the new regression plus original privacy test against current root source. Root acceptance remains T20-owned. T18 goal remains blocked until that root receipt and overall acceptance review arrive.
