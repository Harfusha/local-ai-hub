# T18 root-current dashboard/status handoff

As of 2026-10-03. Hub tooling ignored. Root was not edited and no tests were run in root.

## Root state

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` (`fix(dashboard): surface degraded dependency health`).
- Existing committed dashboard regression receipt: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_polling_quality.py` → 7 passed in 0.54 s. This predates the root-current dirty polling/status hunks below; it is not a receipt for the present dirty tree.
- Root already contains dirty `/api/status` `duration_ms` hunks in `src/local_ai_hub/app.py` and `tests/test_status_snapshot_quality.py`. At final recheck, root SHAs were app `92017513BADBC10D09580367E6FF8DC0A9873C709C75DA940D79DB45DD75D822`; test `8EE8659768D9C307E34DC1532E9C11036425BC0CBEBF09AA12B16FC8BAB97129`. These differ from earlier supplied SHAs; current hunks retain duration instrumentation.
- Root degraded-polling source delta is now integrated as a dirty source-only change in `src/local_ai_hub/dashboard.py`; reverse-check of the source patch passed. Current dashboard SHA-256: `6212C9D58EF6E3315A048DFF501D1B33B425E554CD96893932C3EAEE18516FE7`.
- T04 reported its serial slot released to T01; T18 has no root test slot. Do not infer permission for another owner’s slot.

## Candidate receipts

Owned worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb`.

- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_status_snapshot_quality.py tests/test_dashboard_polling_quality.py` → 24 passed in 2.29 s, exit 0.
- Candidate SHA-256 at the 24-test run: `app.py` `6746BC014A2B9EB9B298D67FFEB40EF465C07D960FD828DE4E18DBD75287C3B8`; `test_status_snapshot_quality.py` `A52903B3BD50B8A73871977C4C8E81D1F0A63D43FC2F88FD66C13918AC6D3172`; `dashboard.py` `88C50B4E2DD4B9EA6F1B526773C750DF37707C1FC288D00C958DCA36AA808A2B`; `test_dashboard_polling_quality.py` `57E87561F9D04E0153027EE10FEC886B2FB46CB7CC14171B96EC85D417D85835`.
- Scoped candidate `git diff --check` passed.

## Root-current polling delta

Root `pollStatus()` still marks the connection green after `/api/live/status` returns `success=false`, and does not reject a non-OK status response. Candidate implements the warning/stop behavior. Prepared source-only patch:

- `handoff/T18-root-current-dashboard-degraded-polling-source-20261003-v3.patch`
- SHA-256 `9786B8A195557C8728C35B522EA311EA50EE7277D97AF098391FFC660986FB73`
- Root `git apply --check --whitespace=nowarn -- <patch>` passed before integration; root reverse-check passed after integration. Patch adds two lines to `src/local_ai_hub/dashboard.py` only. No root write by T18.
- T13 also changes the `hasLiveStatus` connection-render line in its dashboard candidate. The patch inserts its warning after that line and before hardware polling, so hunks are disjoint; recheck against root-current T13 integration before applying.
- Root fixture file was reversed by integration owner; current physical preimage SHA is `037E318D93AB18836EFD5F3B5C3AFE78437B964EE6DFFEB951F831891E24C943`. Normalized diff confirms line-ending-only dirtiness. Fixture-only patch: `handoff/T18-root-current-dashboard-response-fixtures-only-20261003-v2.patch`, SHA-256 `41FBC9574FE8BB1AF44FFA8AB1FE45DBDF7576595D11E721EB5758FE9524989F`. It touches one file and replaces only three API success fakes with `ok:true,status:200`; root `apply --check` passed with whitespace-change tolerance. No operational test file included, no root write by T18.
- The three `git diff --check -c core.whitespace=cr-at-eol` blank-line reports match whitespace already present in root HEAD around Serena config/status lines. Root diff’s single large embedded-dashboard hunk misclassifies these unchanged blank lines as additions. No safe T18-owned whitespace cleanup patch prepared.

## Runtime / admin acceptance gaps

- Actual `/dashboard` browser-to-server-to-`/api/live/status?light=1` run: **NOT RUN**; Hub is unavailable and no live receipt exists.
- The candidate route test uses a stub APP and loopback test server; it proves route document serving only, not a live backend, degraded dependency count, recovery, or browser behavior.
- Admin authorization/action and mode-transition checks: **NOT VERIFIED in root-current integration**. T13 auth work is separately owned; do not claim its acceptance from T18 candidate receipts.
- `/api/status` duration field measures time spent waiting/resolving from the caller’s view; a timed-out worker may continue, so this is not the worker’s eventual completion duration.
- Release acceptance remains open; no release GO implied.
