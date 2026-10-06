# T18 acceptance review — 2026-10-02

## Ownership and baseline

Original worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`; HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. At review start, 20 tracked paths and 22 untracked paths/groups were dirty. No cleanup or checkout reset. Candidate pins from the prior acceptance receipts still match exactly:

- `src/local_ai_hub/telemetry.py` — `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`
- `src/local_ai_hub/http_server.py` — `771D62EA4C5809255E985F40CF46E59A8093AF2F5381813E49A1C74BDFAA93F0`
- `src/local_ai_hub/dashboard.py` — `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705`
- `tests/test_telemetry_privacy.py` — `A33405560C715B20A621A243CBA6B26451FC38DB0CB1EDA43957ED978DAB3917`
- `tests/test_telemetry_flush_retry_t18.py` — `5D584579BF3927A4D93EAE2EB8EC97DEF3C16720A84EFA48C2276DAB317C83EC`

Root is a separate shared checkout with dirty overlap. Current root `http_server.py` SHA `A8DF17496129DDA67BB74711A7D83568385FC301AB670AF3FB8F1659C7E3221D`; current diff is +1,346/-114. T20 must refresh root pins before integration.

## Patch boundary audit

| Patch | SHA-256 | Files and current-root dry-run |
|---|---|---|
| `T18-root-bounded-inspection-20261002-v1.patch` | `BF88560D74DEBA70B3B18745C95961F2D25DA0A84464FA301DAA7D416C1C5BBE` | `debug_traces.py`, `http_server.py`, `dashboard.py`, `test_debug_traces.py`, `test_dashboard_operational_surfaces.py`; 454 insertions/54 deletions; `git apply --check --whitespace=nowarn` exit 0 |
| `T18-root-dashboard-status-tests-only-20261002-v1.patch` | `66D7083A45D9811C112C11C333C960DBF8FFBC2FCBBA86783E0E75230046919C` | `test_dashboard_operational_surfaces.py`, `test_status_snapshot_quality.py`; 26 insertions; dry-run exit 0 |
| `T18-root-telemetry-paging.patch` | `65A4B8A64AA072AA28BB7063BD11AF968C92C17D38791238C794CAEF7B813382` | `http_server.py`, `telemetry.py`, `test_telemetry_timeline_paging_t18.py`; dry-run fails at current root preimages for both source files; test target already exists in root as untracked |
| `T18-root-status-diagnostics.patch` | `91DC34B723655E5AD83E16D82D63E56D2D7001D297477A0CC51B65F86FA32266` | `http_server.py`, `test_http_status_diagnostics_t18.py`; source preimage fails; test target already exists in root as untracked |
| `T18-root-telemetry-sqlite-dashboard-test-only-20261001-v1.patch` | `D61E1AF4F9F501E7734EACD3E1C2C0A7925A48B56F9A32ECA252EC767F874855` | `test_telemetry_sqlite_dashboard_t18.py`; target already exists in root as untracked |
| `T18-root-safe-test-delta.patch` | `2B79118F0C3CA1A750E8163EDA85470FC4D1141B92595F49371D3EC9F70A875F` | `test_dashboard_operational_surfaces.py`, `test_db_query_bounds_t18.py`; existing dashboard hunk fails; test target exists in root as untracked |
| `T18-root-trace-cursor.patch` | `4AB87EC6E9BE3088812783F17242E4654CD3A5B373345EA9A0043524DF5A980C` | `debug_traces.py`, `test_debug_traces.py`; current root/source test preimages fail |

Only the first two dry-run cleanly against this current root snapshot. Do not apply the stale patches or overwrite mixed-owner files. Root integration belongs to T20. The review created no source changes in candidate or root; handoff files only.

## Source review and privacy

Telemetry error persistence classifies exception types into fixed bounded reason strings; it does not store exception text. Error metadata/fingerprints redact credentials, paths, and long tokens. The report has a byte budget and cursor bounds. Earlier telemetry privacy and SQLite dashboard receipts are recorded below.

Debug trace detail is different: it returns stored request, effective payload, response, output, thinking, and event payloads. The HTTP path calls authorization/audit/tenant checks before dispatch. Trace contents remain sensitive to authorized operators; the bounded patch limits page bytes and event count but is not redaction. `/api/context/pack` was not touched.

## Actual test receipts (historical; not rerun in this review)

- Candidate: `42 passed in 18.85s`, checkpoint v7 SHA `BF95C7B96F353054B17B3485AD9A6F46A3A5542C1C7D6EC5A2426C4D52C42214`. The exact command and selector list are in that checkpoint. Current telemetry/HTTP/dashboard and two telemetry test hashes above match its recorded pins.
- Candidate telemetry/dashboard acceptance: `65 passed in 22.74s`, exact selector command in `T18-status-dashboard-telemetry-acceptance-20261001-v4.md` SHA `7CF35F3CE8230885B0899579B37B6645D609FA4CF70AFEB7EC19553717CB4893`.
- Root-pinned selection: `11 passed in 15.96s`, same acceptance handoff; this is not a whole-root suite.
- The new bounded trace/trajectory selectors and supplemental degraded-state root selectors are not covered by those receipts. No test or benchmark ran in this review because T02 has not explicitly released the slot and T20 has not assigned it to T18. Exact next command is in `T18-dashboard-status-current-owner-delta-20261002-v1.md`.

## Current blockers

Latest T02 snapshot is idle; its last turn cannot verify its original checkout because `4b5d` is not a Git worktree. Latest T20 monitor says T20 remains active, its worktree is archived, and it is reconstructing acceptance evidence. No T18 slot assignment/release reported. T13 still owns operational-mode production. No full release acceptance claim.
## Scoped diff whitespace validation (2026-10-02)

Executed, exit 0, against the T18 status/dashboard/telemetry tracked source and test paths only (no tests/build):

```powershell
git diff --check -- src/local_ai_hub/dashboard.py src/local_ai_hub/debug_traces.py src/local_ai_hub/http_server.py src/local_ai_hub/telemetry.py tests/test_dashboard_operational_surfaces.py tests/test_status_snapshot_quality.py tests/test_debug_traces.py tests/test_telemetry_privacy.py tests/test_telemetry_error_metadata_privacy_t18.py
```

Git emitted only LF-to-CRLF working-copy warnings for `http_server.py`, `telemetry.py`, `test_telemetry_error_metadata_privacy_t18.py`, and `test_telemetry_privacy.py`; no whitespace errors. This check does not cover untracked files. Exact deferred pytest command is in the dashboard/status delta handoff; no test receipt for new bounded selectors.

## Root-current telemetry cursor truncation delta (2026-10-02)

Static comparison found root already has the T18 telemetry report/paging/privacy surfaces, but `_bound_telemetry_report` differs from the candidate when the response byte budget truncates `error_fingerprints`: root updates `next_offset` even for cursor mode and does not recompute `next_cursor` from the final retained row. The stale `next_cursor` can skip rows removed by response truncation. Other inspected telemetry error helpers and `report` were AST-equivalent; root's extra `OSError.errno` classifications in `_safe_error_message` were retained.

Candidate-only regression node added: `tests/test_telemetry_report_bounds_t18.py::test_report_budget_truncation_advances_cursor_after_retained_rows`. Candidate test SHA-256: `69C915E4A668F45C6C19353C35134E6F937F850A74A819489DA74F9394A543D0`. New test AST parse succeeded; it was not executed.

Root-current source patch: `handoff/T18-root-telemetry-report-cursor-budget-20261002-v1.patch`, SHA-256 `5C68B2319A407836CF97AFD81B575EC2BB829EB304B458F548B6A2A065E2DF3E`; modifies only `src/local_ai_hub/telemetry.py` (15 insertions, 1 deletion). Test-only root patch: `handoff/T18-root-telemetry-report-cursor-budget-test-only-20261002-v1.patch`, SHA-256 `026139F0D498F5EEC8CA282A95419DAF90D18071629B5F70842D2F5F6A403129`; modifies only `tests/test_telemetry_report_bounds_t18.py` (51 additions). Combined current-root `git apply --check --whitespace=nowarn` exited 0; root files remain unchanged.

Exact deferred selector after T20 integrates both patches and G is no longer UNKNOWN:

```powershell
Set-Location 'C:\Users\Adam\.local-ai-hub'
& 'C:\Python313\python.exe' -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_report_bounds_t18.py::test_report_budget_truncation_advances_cursor_after_retained_rows
```

No test or benchmark ran. T20 owns root integration and the test slot. The root production fix patch preserves unrelated OSError classification improvements.

## Root-current dashboard degraded-state delta (2026-10-02)

A null/unknown Ollama probe was incorrectly treated as healthy in root `dashboardHealth`; candidate reports `unknown` as attention and distinguishes it from offline. Patch `T18-root-dashboard-ollama-unknown-20261002-v1.patch`, SHA-256 `2376EFD6448E7F32ED2A8E7F7BDBBC23DD08C5269058FF6485E0050AC25CFEB4`, changes only `src/local_ai_hub/dashboard.py` (+3/-2). Combined dry-run with the degraded-state test-only patch passed; root remains unmodified. Candidate v7 42-pass receipt includes both target tests; no root receipt. Exact deferred root selector is in the dashboard delta handoff. No test/benchmark run in this continuation.

## Current root-current patch bundle dry-run (2026-10-02)

One `git apply --check --whitespace=nowarn` invocation with these five artifacts exited 0 against the current root; no patch was applied:

- `T18-root-bounded-inspection-20261002-v1.patch` — `BF88560D74DEBA70B3B18745C95961F2D25DA0A84464FA301DAA7D416C1C5BBE`
- `T18-root-dashboard-status-tests-only-20261002-v1.patch` — `66D7083A45D9811C112C11C333C960DBF8FFBC2FCBBA86783E0E75230046919C`
- `T18-root-dashboard-ollama-unknown-20261002-v1.patch` — `2376EFD6448E7F32ED2A8E7F7BDBBC23DD08C5269058FF6485E0050AC25CFEB4`
- `T18-root-telemetry-report-cursor-budget-20261002-v1.patch` — `5C68B2319A407836CF97AFD81B575EC2BB829EB304B458F548B6A2A065E2DF3E`
- `T18-root-telemetry-report-cursor-budget-test-only-20261002-v1.patch` — `026139F0D498F5EEC8CA282A95419DAF90D18071629B5F70842D2F5F6A403129`

This is patch applicability evidence only. It is not source integration or test acceptance. Root files remain dirty under T20 ownership. The new cursor-budget regression test is prepared but unexecuted; run only after G is no longer UNKNOWN and T20 serial GO.

Exact reproducible current-root patch preflight (executed earlier with the listed same five patch arguments; result exit 0):

```powershell
git -C 'C:\Users\Adam\.local-ai-hub' apply --check --whitespace=nowarn `
  'C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-bounded-inspection-20261002-v1.patch' `
  'C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-dashboard-status-tests-only-20261002-v1.patch' `
  'C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-dashboard-ollama-unknown-20261002-v1.patch' `
  'C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-telemetry-report-cursor-budget-20261002-v1.patch' `
  'C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-telemetry-report-cursor-budget-test-only-20261002-v1.patch'
```
