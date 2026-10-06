# T18 dashboard, admin, and status acceptance handoff

Date: 2026-10-01. Candidate HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`; root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. T18 made no root edits. Root remains dirty under T20/other owners. HUB was skipped.

## Completed receipts (no retest in this continuation)

1. Candidate status/dashboard/admin/mode/telemetry acceptance, root variables cleared:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_mode_playwright_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_status_diagnostics_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_telemetry_timeline_paging_t18.py tests/test_status_snapshot_quality.py::test_realtime_status_surfaces_stored_sqlite_error_summary tests/test_dashboard_operational_surfaces.py::test_dashboard_exposes_activity_mode_and_reports_http_failures tests/test_dashboard_operational_surfaces.py::test_dashboard_requires_server_confirmation_before_reporting_mode_update tests/test_dashboard_operational_surfaces.py::test_status_poller_respects_visibility_unchanged_state_and_jitter tests/test_dashboard_operational_surfaces.py::test_dashboard_api_fetch_has_bounded_request_timeout tests/test_dashboard_operational_surfaces.py::test_dashboard_wires_status_refreshes_through_backoff_poller
65 passed in 22.74s
```

2. Current-root pinned mode/auth/DOM/status/SQLite selector was run from candidate harness after preloading current root modules and validating root paths/hashes. It covers actual read-only loopback mode GET, unauthorized and scoped-token mode POST with authorization audit and persisted state, dashboard degraded/partial/401/503 UI, and `realtime_status(light=True)` SQLite error summary.

Environment set before run:

```powershell
$root='C:\Users\Adam\.local-ai-hub\src'
$env:T18_ROOT_SOURCE=$root
$env:T18_ROOT_HTTP_SERVER_SHA256='6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3'
$env:T18_ROOT_DASHBOARD_SHA256='9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760'
$env:T18_ROOT_TELEMETRY_SHA256='79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE'
```

Command:

```powershell
$code="import sys,hashlib; from pathlib import Path; sys.path.insert(0,r'$root'); import local_ai_hub.http_server,local_ai_hub.dashboard,local_ai_hub.telemetry,local_ai_hub.app; assert Path(local_ai_hub.http_server.__file__).resolve()==Path(r'$root/local_ai_hub/http_server.py').resolve(); assert hashlib.sha256(Path(local_ai_hub.telemetry.__file__).read_bytes()).hexdigest().upper()==__import__('os').environ['T18_ROOT_TELEMETRY_SHA256']; import pytest; raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--tb=short','tests/test_root_current_mode_overlay_t18.py','tests/test_dashboard_mode_playwright_t18.py','tests/test_telemetry_error_diagnostics_t18.py','tests/test_telemetry_sqlite_dashboard_t18.py','tests/test_status_snapshot_quality.py::test_realtime_status_surfaces_stored_sqlite_error_summary']))"
python -B -W error::ResourceWarning -c $code
```

Result: **11 passed in 15.96s**. Root-pinned fixture asserted HTTP/dashboard module paths and hashes; telemetry import resolved from the pinned root package. This receipt is from prior run; intentionally not repeated in this continuation.

3. Root errno diagnostic test is already integrated. Root owner receipt: `tests/test_telemetry_error_errno_diagnostics_t18.py`, SHA-256 `B6C59287C900E2E4C8B6023DBF6C049720D754CACEE2E3F14F322945D801620F`, **1 passed in 0.72s**, scoped diff-check clean. Not repeated.

## Current root pins

- `src/local_ai_hub/http_server.py`: `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`
- `src/local_ai_hub/app.py`: `2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546`
- `src/local_ai_hub/telemetry.py`: `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`
- `tests/test_telemetry_error_errno_diagnostics_t18.py`: `B6C59287C900E2E4C8B6023DBF6C049720D754CACEE2E3F14F322945D801620F`
- `tests/test_telemetry_sqlite_dashboard_t18.py`: `6F841BAE86741DE4D6A01A7A2BD227CBCF8524EF982E9A6AC2FDED430E0705AC`

## Blockers and limits

No open T18-specific dashboard/admin/status test gap remains in these receipts. No full root suite, live Hub/service, user browser, or GPU was run. T20 owns remaining integrated release acceptance and any broader root selector. Do not apply old errno patch; its target exists and owner verified it.
