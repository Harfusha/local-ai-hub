# T18 end-to-end current-root receipt — 2026-10-03

## Scope and ownership

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- T18 worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, detached HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.
- Hub tooling skipped per user. No source, route, root, test, or shared-owner files changed in this continuation. Root has 357 dirty status entries; T18 worktree has 44. Preserve mixed ownership and line endings.
- T13 owns operational-mode/auth production changes; T20 owns root integration and serial test slots. T01 reports T04 has the dedicated serial test slot. T04's latest completed turn was source-only; no explicit T18 slot release or GO is recorded.

## Integrated T18 changes

The following owner patches are already integrated in root. Each `git apply --reverse --check` completed with exit 0; no patch was applied in this continuation.

| Patch | SHA-256 | Scope |
|---|---|---|
| `T18-root-current-dashboard-degraded-polling-source-20261003-v3.patch` | `9786B8A195557C8728C35B522EA311EA50EE7277D97AF098391FFC660986FB73` | Dashboard degrades failed status response instead of reporting healthy connection |
| `T18-root-current-dashboard-response-fixtures-only-20261003-v2.patch` | `41FBC9574FE8BB1AF44FFA8AB1FE45DBDF7576595D11E721EB5758FE9524989F` | Three successful status fixtures include `ok:true,status:200` |
| `T18-root-telemetry-report-cursor-budget-20261002-v1.patch` | `5C68B2319A407836CF97AFD81B575EC2BB829EB304B458F548B6A2A065E2DF3E` | Recompute telemetry page cursor after response-budget truncation |
| `T18-root-telemetry-report-cursor-budget-test-only-20261002-v2.patch` | `DBF914CA219290CCDBE0A66BE18FEC5691CA7013F162BD7A7BC04A5E5D7AE52E` | Regression selector for retained-row cursor after truncation |

Current root pins:

- `src/local_ai_hub/dashboard.py` — `6212C9D58EF6E3315A048DFF501D1B33B425E554CD96893932C3EAEE18516FE7`
- `src/local_ai_hub/telemetry.py` — `07D8651FE93B42363873348088611E54D9376CB52B820C01BD81D703637BC48A`
- `src/local_ai_hub/app.py` — `92017513BADBC10D09580367E6FF8DC0A9873C709C75DA940D79DB45DD75D822`
- `tests/test_dashboard_polling_quality.py` — `A6D8EFC0900DF03455EC3DB2F8F029CB307B778F12A144614A79DD600506C014`
- `tests/test_telemetry_report_bounds_t18.py` — `028E5D68A2ECBE840D665A062F79057C4DF25D0DCD3A66A16A813854F1F71CFE`
- `tests/test_status_snapshot_quality.py` — `8EE8659768D9C307E34DC1532E9C11036425BC0CBEBF09AA12B16FC8BAB97129`

## Test receipts and remaining gate

- Historical candidate status/dashboard bounded suite: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_status_snapshot_quality.py tests/test_dashboard_polling_quality.py` — **24 passed in 2.29 s**, tied to candidate pins in `T18-root-current-dashboard-status-acceptance-20261003-v1.md`. Not current-root acceptance.
- Historical candidate admin/status/telemetry suite: **65 passed in 22.74 s**; root-pinned integration selection: **11 passed in 15.96 s**. Their root pins predate current HEAD/source drift; do not use as current-root receipts.
- No tests rerun in this continuation: no explicit T18/T20 GO. The focused current-root telemetry selector is `tests/test_telemetry_report_bounds_t18.py::test_report_budget_truncation_advances_cursor_after_retained_rows`. Dashboard/status selectors and mode/admin selectors are listed in `T18-root-current-dashboard-status-acceptance-20261003-v1.md`.
- Actual `/dashboard` with a running backend, degraded/recovery cycle, live admin action/auth, and deployed service remain **NOT VERIFIED**. Existing Playwright test uses stub loopback APIs. Admin/mode source is T13-owned.

T18 source patches and regression fixtures are integrated, but current-root test acceptance and live runtime acceptance remain open. No additional safe T18 patch is identified.
