# T18 status, dashboard, telemetry acceptance handoff

## Ownership and pins

- Candidate worktree only: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, detached HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`; 37 dirty paths were present before this handoff. No broad diffs copied, reset, staged, or committed.
- T18 telemetry scope: `TelemetryStore._safe_error_message` in `src/local_ai_hub/telemetry.py` and synthetic coverage in `tests/test_telemetry_error_diagnostics_t18.py` plus `tests/test_telemetry_sqlite_dashboard_t18.py`.
- Candidate source SHA-256: telemetry `607736CE42A16C348F3032FC514C5FDB19C35A15E2FFA77A260E3F88E99EA14D`; diagnostics test `B0303169B5AE7728B4A444B724F7F3BDA0A2EACCE1B681DDAE4884C82DE1BCC2`; SQLite dashboard test `73947FF8F0C09B9075F6C1A6AFDC7314F1BFB2D3124EF7416C6DD7A896586A4C`.
- Read-only root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root was already dirty under T20/other owners; T18 wrote nothing there.
- Exact root pins: `src/local_ai_hub/http_server.py` `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`; `dashboard.py` `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`; `app.py` `2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546`; `telemetry.py` `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`; `agent_events.py` `02A25102B888B23FE99B8C508F59AEDD846BA24FD38A268BCC6893B0877E0A38`; integrated `tests/test_telemetry_sqlite_dashboard_t18.py` `6F841BAE86741DE4D6A01A7A2BD227CBCF8524EF982E9A6AC2FDED430E0705AC`.

## Behavior

The allowlist retains useful safe classifications for timeout, invalid JSON, missing file, permission denial, connection, invalid value/type, and generic OS/runtime errors. It does not persist raw exception text. Safe diagnostic length stays capped at 96 characters.

The SQLite test records 15 synthetic failures, including private prompt/source/token/path sentinels. It flushes and reads actual SQLite, checks classifications through realtime/dashboard summaries, verifies 12-row recent-error bound and report total, and asserts sentinels never leak.

## Receipts

Candidate-only end-to-end selector, with all `T18_ROOT_*` variables cleared:

```text
python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_mode_playwright_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_status_diagnostics_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_telemetry_timeline_paging_t18.py tests/test_status_snapshot_quality.py::test_realtime_status_surfaces_stored_sqlite_error_summary tests/test_dashboard_operational_surfaces.py::test_dashboard_exposes_activity_mode_and_reports_http_failures tests/test_dashboard_operational_surfaces.py::test_dashboard_requires_server_confirmation_before_reporting_mode_update tests/test_dashboard_operational_surfaces.py::test_status_poller_respects_visibility_unchanged_state_and_jitter tests/test_dashboard_operational_surfaces.py::test_dashboard_api_fetch_has_bounded_request_timeout tests/test_dashboard_operational_surfaces.py::test_dashboard_wires_status_refreshes_through_backoff_poller
65 passed in 22.74s
```

Root-pinned mode/auth/DOM/realtime-status/SQLite integration ran from the candidate test harness after importing root modules first and checking current hashes. `T18_ROOT_SOURCE` pointed at `C:\Users\Adam\.local-ai-hub\src`; HTTP server, dashboard, and telemetry module paths and SHA-256 values matched the pins above. Command selector: `tests/test_root_current_mode_overlay_t18.py tests/test_dashboard_mode_playwright_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_status_snapshot_quality.py::test_realtime_status_surfaces_stored_sqlite_error_summary`.

```text
python -B -W error::ResourceWarning -c <root-module preload and pinned pytest selector>
11 passed in 15.96s
```

The earlier import-origin and mixed-source failures are superseded by the separated candidate-only and root-pinned receipts above. No root checkout test suite was run. No Hub/live service, GPU, or browser session was used; Playwright used preinstalled headless Chromium.

## Handoff

Current root pins show the classified-error branches and T20-added SQLite test file present. No further source change needed from T18 in this turn. T20 owns root integration and root-suite receipts. Keep root changes unmodified here.

