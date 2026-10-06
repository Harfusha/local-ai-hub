# T18 dashboard/status current owner delta — 2026-10-02 v1

## Scope and pins

Read-only dashboard/status source review in original T18 worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. Root remains `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. No root files changed. This review did not run tests or benchmarks. Local AI Hub tools were not used.

| Path | T18 candidate SHA-256 | Current root SHA-256 |
|---|---|---|
| `src/local_ai_hub/dashboard.py` | `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705` | `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760` |
| `tests/test_dashboard_operational_surfaces.py` | `C2CAA92E8F401844FBC35CD950CC77313CEEF85EC74052BA3301A3A017F37F51` | `46F2816F1CE47665ED7B01F8C87B617C15B222F1AD1923BF736AE577492B31B6` |
| `tests/test_status_snapshot_quality.py` | `00EC4D2ABD65ABBF07EBF4981D41C2B0893F5FAB9A67CFF005F0CB39B1EF5DE7` | `1A08CC0F690FF70D4A3D78F9C2A122965CC4FBCD2063544090627B4A4C4CF0C8` |

Both root and candidate dashboard files are already dirty and have mixed-owner changes. Whole-file replacement is unsafe.

## Source review

T18-owned operator transition display hunk is `handoff/T18-root-current-operator-display.patch`, SHA-256 `C65C257D082B180B908F6DCAC49DB09CA0131BF05E290D353CD7D9F9DCB579CC`. Source-only reverse apply check exited 0 against both current root and candidate. This proves the exact T18 hunk is present in both; no dashboard production patch remains to apply.

Candidate dashboard/status coverage review found no additional source-level defect. Candidate behavior covers unknown versus offline Ollama probe, degraded live status with retry, partial VRAM unload, transition failure reporting, poller overlap, dependency deadline degradation, and bounded runtime probes. The candidate-only `dashboard_status_poller.py` extraction has no established ownership and duplicates root inline behavior; do not transfer it.

## Current root selector inventory

Static AST inventory confirms these focused node IDs exist in both root and candidate:

```text
tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause
tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures
tests/test_dashboard_operational_surfaces.py::test_live_pollers_skip_overlapping_requests
tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape
tests/test_status_snapshot_quality.py::test_slow_accelerator_probe_degrades_within_deadline_and_keeps_shape
tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes
tests/test_status_snapshot_quality.py::test_slow_agent_state_summary_uses_dependency_deadline
```

These three T18 supplemental node IDs exist in candidate and are absent from current root test files:

```text
tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline
tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff
tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe
```

The candidate supplemental receipts are historical: dashboard selector `5 passed in 0.61s`; status selector `6 passed in 0.69s` (five node IDs, one parametrized). Full commands and scope are in `handoff/T18-coverage-review-20261002-v1.md`, SHA-256 `4C0C646F43DAC36003F35720513B62A46941FFD9EA814597633D9D84E42D595E`. They prove candidate behavior at that run, not root acceptance or current dirty-file behavior. T20's prior 48-pass root receipt included whole root dashboard/status files under then-current pins; it is historical root evidence, not a receipt for newly added candidate-only cases.

Exact function-only root test patch: `handoff/T18-root-dashboard-status-tests-only-20261002-v1.patch`, SHA-256 `66D7083A45D9811C112C11C333C960DBF8FFBC2FCBBA86783E0E75230046919C`. It adds only these three test functions (26 lines total) to the two existing mixed-owner root test files:

```text
tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline
tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff
tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe
```

Root `git apply --check --whitespace=nowarn` exited 0. Patch remains unapplied; root files were not edited. Keep the mixed-owner files intact and route application through T20 root integration ownership.

## Blockers and next acceptance

Latest external snapshot: T02 is idle with review-only `-05` manifest `handoff/T02-paired-matrix-20261002-v1/manifest-T02-CPU-20261002-05-draft.json`, SHA-256 `0FE9D7D8D0BE90D7D4B93309F8D4BF6D50EA0F2CF36016EB375D00AC695D259C`. It says `review_only_not_runnable`, `measurement_allowed=false`, `slot=null`; `-04` remains preserved. No slot is assigned or released to T18. T20 reports T03 slot 13 ended before test due to transport hash drift. T21 slot 14 was closed from the existing log as `5 passed, 69 deselected`; receipt SHA-256 `69D46E50B5B86DC4F241A00FF034387518B387FA61E051F64FC02FCBB29872FC`. T20 did not repeat the test, released slot 14, and requested fresh manifest/pins from T02; benchmark has not run. T20 now asks for approval to extend work to T03 output-schema and T12 selector after slots 15–18; no T18 slot assignment exists. T19 runbook integration had halted before apply-check on a SHA mismatch; root unchanged. T13's latest state keeps mode gates untouched and releases only MCP/schema scope to T03. T20 remains active. These updates do not satisfy the T02 gate or assign a slot to T18.

No T18 source-level dashboard/status gap was found. Root lacks the three named supplemental test functions. Integrate only those exact test functions after owner review, or accept equivalent existing root coverage with named evidence; do not replace either mixed-owner test file.

Fresh thread reads on 2026-10-02: T02 is active on static-only work; latest states no test or benchmark repeat and no T02 slot assignment. T02's last stated queue was T11, T05, T03, T08, then T02; T20 has since reprioritized based on a new T21 root gate: T05 slot 12, T03 slot 13, T21 slot 14, T01 slot 15, and T08 no earlier than slot 16. T02's position after this reorder is not confirmed. T07 slot 06 ended `UNKNOWN`. T04 released slot 07 after 31 passed/5 failed; its broker result was `UNKNOWN`. T15 explicitly released slot 08 after `outcome_unknown=true` (`req_c346aa085510`); receipt SHA-256 `658F1EA53F0EEFCC549E38B0FAEFFFCD45CEA9688F31741ACDB0477EE20AB4FA`, manifest SHA-256 `7776CD49BEB5D43E69EAC6F5B879D92FC62336D64AB21D3598164BEC11FD07FB`. T13 slot 09 ended `UNKNOWN` and was explicitly released to T20; T13 records the receipt in its handoff. T20 reports slot 11 closed for T11: privacy `1 passed`, offline suite `179 passed, 3 skipped`; both native runs after new permission, not broker-validated. T20 later confirmed all 18 source pins still matched after those runs. T05 slot 12 ended without test execution: the pin guard found `agent_memory.py` SHA drift; T05 applied only its approved test-only hunk, did not revert, then released the slot. T03 slot 13 ended before test execution because of transport hash drift. T20 now verifies pins before its T21 root gate; this is not a T02 release for T18. Earlier T19 runbook integration also halted on patch SHA mismatch before apply-check, with root unchanged. This turn rehashed the five T18 source/test files in candidate and root; hashes match handoff pins. No T18 inputs changed. No benchmark ran. T20 retains root integration and serial slot assignment. T18 has no slot assignment. Do not run selectors until T02 explicitly releases the single slot and T20 assigns it to T18. After assignment and T20 acceptance of the supplemental patch, run the exact command below.

```powershell
Set-Location 'C:\Users\Adam\.local-ai-hub'
& 'C:\Python313\python.exe' -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause `
  tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures `
  tests/test_dashboard_operational_surfaces.py::test_live_pollers_skip_overlapping_requests `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff `
  tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape `
  tests/test_status_snapshot_quality.py::test_slow_accelerator_probe_degrades_within_deadline_and_keeps_shape `
  tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes `
  tests/test_status_snapshot_quality.py::test_slow_agent_state_summary_uses_dependency_deadline `
  tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe
```

T13 owns operational-mode production. This dashboard/status review does not claim mode-route auth acceptance. T20 owns overall release acceptance. No full release claim follows from static source equality or prior focused receipts.

## Bounded inspector source review (2026-10-02)

Root-current bounded-inspection patch: `handoff/T18-root-bounded-inspection-20261002-v1.patch`, SHA-256 `BF88560D74DEBA70B3B18745C95961F2D25DA0A84464FA301DAA7D416C1C5BBE`. This is a prepared patch artifact only. `git apply --check --whitespace=nowarn` passed against `C:\Users\Adam\.local-ai-hub`; `git apply --stat` reports five paths, 454 insertions and 54 deletions. The degraded-state test-only patch also passed `git apply --check`. Neither patch was applied. Root source/test file hashes were captured after the checks; no root files changed.

Findings: the root trace-detail route ignored `limit` and `max_bytes`, and the store returned every retained event after `since_seq`. The patch adds bounded trace pages, an 8 MiB HTTP response ceiling, oversize-to-413 handling, cursor/reset metadata, and response-size rebuilding after session reconciliation. The root trajectory API already accepts bounded cursor pages; its dashboard inspector issued one unbounded request and rendered the full stream. The patch switches it to 100-event pages with a snapshot cursor, retry/load-more UI, gap and cursor-reset handling. `/api/context/pack` was not touched.

Prepared focused root selectors (not run; require explicit T02 slot release and T20 assignment/integration):

- `tests/test_debug_traces.py::test_trace_detail_http_clamps_page_parameters_and_maps_oversize`
- `tests/test_debug_traces.py::test_trace_detail_http_rebuilds_page_after_reconciliation`
- `tests/test_dashboard_operational_surfaces.py::test_trace_inspector_consumes_pages_with_hard_response_budget`
- `tests/test_dashboard_operational_surfaces.py::test_trajectory_inspector_uses_bounded_cursor_pages`
- Existing bounded regressions: `tests/test_debug_traces.py::test_trace_detail_since_seq_and_list_filters_are_bounded` and `tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes`

Root integration and test-slot ownership remain with T20. No T18 tests or benchmarks ran. Do not apply the patch or execute selectors until T20 accepts the patch and assigns the serial slot after T02 explicitly releases it.

Sensitive-data review: `Handler.do_GET` calls `_require_authorized()` for `/api/debug-traces` routes before dispatch. That gate checks host/origin, authorization, admin audit, tenant binding, and rate limiting (`http_server.py` lines 2078-2086 and 1499-1526). Trace detail currently returns stored request, effective payload, response, output, thinking, and event payloads without blanket redaction; `_request_summary` redacts a limited set of secret-like command-line assignments only. The bounded patch preserves the existing authorization boundary and caps returned bytes, but does not claim to redact trace contents. Treat returned trace data as sensitive operator data.

Exact root command after T20 integrates both supplemental patches, confirms current pins, and assigns the slot after T02 release (not run):

```powershell
Set-Location 'C:\Users\Adam\.local-ai-hub'
& 'C:\Python313\python.exe' -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_debug_traces.py::test_trace_detail_http_clamps_page_parameters_and_maps_oversize `
  tests/test_debug_traces.py::test_trace_detail_http_rebuilds_page_after_reconciliation `
  tests/test_debug_traces.py::test_trace_detail_since_seq_and_list_filters_are_bounded `
  tests/test_dashboard_operational_surfaces.py::test_trace_inspector_consumes_pages_with_hard_response_budget `
  tests/test_dashboard_operational_surfaces.py::test_trajectory_inspector_uses_bounded_cursor_pages `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause `
  tests/test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures `
  tests/test_dashboard_operational_surfaces.py::test_live_pollers_skip_overlapping_requests `
  tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape `
  tests/test_status_snapshot_quality.py::test_slow_accelerator_probe_degrades_within_deadline_and_keeps_shape `
  tests/test_status_snapshot_quality.py::test_realtime_status_bounds_runtime_health_probes `
  tests/test_status_snapshot_quality.py::test_slow_agent_state_summary_uses_dependency_deadline `
  tests/test_status_snapshot_quality.py::test_status_distinguishes_offline_from_successful_runtime_probe
```

## Baseline refresh and gate state (2026-10-02 continuation)

Original T18 worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. `git status --short` shows 20 modified tracked paths and 22 untracked paths/groups, including the overlapping dashboard, trace, HTTP, telemetry, event, and test work. This dirty tree is shared/owner-mixed; no cleanup, reset, source overwrite, or root apply occurred. Root also has local edits in the five affected paths. Current root `http_server.py` SHA is `A8DF17496129DDA67BB74711A7D83568385FC301AB670AF3FB8F1659C7E3221D` and its current diff is 1,346 additions/114 deletions, so T20 must refresh integration pins before applying. Despite that drift, current root `git apply --check --whitespace=nowarn` exited 0 for both the bounded-inspection patch (`BF88560D74DEBA70B3B18745C95961F2D25DA0A84464FA301DAA7D416C1C5BBE`) and the degraded-state test-only patch (`66D7083A45D9811C112C11C333C960DBF8FFBC2FCBBA86783E0E75230046919C`). Both remain unapplied.

Latest read-only thread snapshot: T02 is idle but its latest turn says its `4b5d` checkout is not a Git worktree and it cannot verify its baseline; no explicit slot release to T18 is present. T20 is active and is still checking slot assignment. No T18 test ran in this continuation. Existing candidate evidence remains the previously recorded v7 receipt (42 passed, 18.85s); the separate older acceptance handoff records 65 candidate passes and an 11-pass root-pinned receipt. These historical receipts do not cover the new bounded-inspection selectors or current root drift.

The exact combined selector command and sensitive-data/auth boundary are recorded above. T20 owns root integration and slot assignment; T13 owns operational-mode production. No full release acceptance is claimed. `/api/context/pack` was not touched.

## Latest T20 monitor delta (2026-10-02)

A bounded `wait_threads` snapshot (30 seconds; timed out, T20 still active) reported T20's worktree is archived and T20 is reconstructing acceptance evidence. No slot assignment or T02 release for T18 was reported. This newer state supersedes the earlier note that T20 was checking a slot. No test or benchmark was run here.

## Independent acceptance and patch boundary review (2026-10-02)

Recorded in `handoff/T18-acceptance-review-20261002-v1.md` with per-patch SHA-256, exact file scope, current-root dry-run outcomes, candidate source pins, telemetry privacy review, and prior test receipts. The bounded-inspection and degraded-state patches are the only reviewed patches that apply cleanly by dry-run to the current root. Older telemetry paging, status diagnostics, SQLite-dashboard test, safe-test delta, and trace-cursor patches have current-root preimage collisions or target files that already exist. None was applied. Current root `http_server.py` has other-owner drift (`A8DF17496129DDA67BB74711A7D83568385FC301AB670AF3FB8F1659C7E3221D`; +1,346/-114); T20 owns re-pinning and integration.

Historical receipts are precise but do not cover the new bounded selectors: candidate 42/42 (18.85s), candidate acceptance 65/65 (22.74s), root-pinned focused selection 11/11 (15.96s). Their command/source-pin evidence is linked in the review. No tests or benchmarks ran in this review.

Scoped source-diff whitespace check passed (exit 0), path-bounded, no tests/build. Updated review handoff SHA-256: `8B6814D88879E9A28DE6EA97AB0373161C4128B361D54E524A0F01CB3C61A41B`.

T18 root-current telemetry truncation regression is now isolated to one production hunk and one test-only patch; details, patch SHA, current-root combined apply-check, and exact deferred selector are in the review handoff (SHA-256 `83545762CE6DF1707F326D9F1161FAFD2568CA96C9B437D58956A4DD3BD825F9`). Candidate adds only `test_report_budget_truncation_advances_cursor_after_retained_rows`; it was not run.

## Root-current dashboard unknown/offline delta (2026-10-02)

Root `dashboardHealth` treated only `ollamaOnline === false` as offline; a missing/null probe fell through to Healthy. Candidate uses explicit `ollama_status`, falls back from online boolean, and reports unknown separately from offline. Prepared source patch `handoff/T18-root-dashboard-ollama-unknown-20261002-v1.patch`, SHA-256 `2376EFD6448E7F32ED2A8E7F7BDBBC23DD08C5269058FF6485E0050AC25CFEB4`; only `src/local_ai_hub/dashboard.py` (3 insertions, 2 deletions). Combined current-root dry-run with degraded-state test patch exited 0. Root dashboard SHA stayed `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`; no apply.

Existing candidate receipt v7 (`42 passed / 18.85s`) includes `test_dashboard_distinguishes_unknown_ollama_probe_from_offline` and `test_dashboard_marks_degraded_live_status_and_retries_with_backoff`; root has no receipt. Deferred exact root selector after T20 integration/serial GO and G is no longer UNKNOWN:

```powershell
Set-Location 'C:\Users\Adam\.local-ai-hub'
& 'C:\Python313\python.exe' -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_distinguishes_unknown_ollama_probe_from_offline `
  tests/test_dashboard_operational_surfaces.py::test_dashboard_marks_degraded_live_status_and_retries_with_backoff
```

No tests or benchmarks ran in this continuation.

Current five-patch root-current bundle passed one dry `git apply --check --whitespace=nowarn` invocation (exit 0); no root patch applied. Exact patch names/SHA and scope are in the review handoff SHA `83545762CE6DF1707F326D9F1161FAFD2568CA96C9B437D58956A4DD3BD825F9`. Applicability is not integration or test acceptance.

Exact reproducible five-patch current-root preflight command and exit-0 receipt are in review SHA `83545762CE6DF1707F326D9F1161FAFD2568CA96C9B437D58956A4DD3BD825F9`.
