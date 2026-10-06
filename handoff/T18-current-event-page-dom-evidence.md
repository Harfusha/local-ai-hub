# T18 current event-page + dashboard DOM evidence

**Scope:** isolated T18 candidate only. T18 made no root writes and ran no root tests. T20 owns live root integration and final root selectors. Mode authority remains with T13; no mode/HTTP production code changed in this work.

## Candidate DOM acceptance

Added `tests/test_dashboard_mode_playwright_t18.py` and `tests/fixtures/dashboard_mode_playwright_t18.cjs`. The fixture serves the actual `DASHBOARD_HTML` over an ephemeral loopback HTTP server, blocks non-local requests, and launches bundled Node + Playwright with an already-installed Playwright headless Chromium. It opens the real Controls menu and enters tokens through the actual input and button.

The browser assertions cover unauthenticated loopback `GET /api/mode`, degraded status projection, successful scoped-token POST to `/api/admin/mode`, partial gaming transition projection (pending VRAM unload plus accelerator/job failures), pressed-mode state, enabled controls after completion, wrong-token 401 with prior mode preserved, and valid-token 503 with prior mode preserved.

RED/GREEN: first run confirmed missing runner; diagnostic run identified the actual `/api/live/status` endpoint and closed `<details>` controls. After correcting the fixture to the real degraded-status envelope and interacting through visible DOM controls, focused browser/event/DB selector passed **16/16 in 6.43s**. Full T18 candidate selector with the browser test passed **138/138 in 30.78s**, exit 0.

```powershell
python -m pytest -q --tb=short tests/test_dashboard_operational_surfaces.py tests/test_status_snapshot_quality.py tests/test_http_status_diagnostics_t18.py tests/test_telemetry_report_bounds_t18.py tests/test_debug_traces.py tests/test_telemetry_timeline_paging_t18.py tests/test_db_query_bounds_t18.py tests/test_agent_event_page_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_telemetry_privacy.py tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_http_phase_telemetry.py tests/test_http_tool_accounting_rejections.py tests/test_dashboard_mode_playwright_t18.py
```

Runtime receipt: Node `v24.19.0` at `C:\Users\Adam\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`; Playwright package under `...\dependencies\node\node_modules\playwright`; preinstalled headless Chromium `147.0.7727.15`. No package install or browser download.

Candidate artifact SHA-256:
- `tests/test_dashboard_mode_playwright_t18.py`: `FEB633BF2AEB86E4F8CF3299E7BA846DC468D269ED7D3F3A82D04AF65C97D14C`
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`: `CC63D998923BCE8A736551AC4D9786F32F51048E530394AB9FE7855F90AA2736`
- `tests/test_agent_event_page_t18.py`: `95ADEFBA99FAE852A78AC8B1C9AC18F6FF579C2CDC96404FB6E4BA9A19A0F8C6`

## Current root event-page source (read-only)

Live root SHA-256:
- `src/local_ai_hub/agent_events.py`: `02A25102B888B23FE99B8C508F59AEDD846BA24FD38A268BCC6893B0877E0A38`
- `src/local_ai_hub/http_server.py`: `CD2998708AFBEE64A22D8027AA86969E9C17A05967CBED8431BEE7A4F8D55FD5`
- `tests/test_agent_event_page_t18.py`: `39BE401F6709F46F52FFAE904CF87D7DB5B9D329DF381206E98EB633C2CA0B68`

Read-only source inspection confirms `AgentEventStore.event_page` serializes result rows with `event.to_dict()` (`agent_events.py:627`). The GET route now calls `event_page`, carries `after_seq` / `through_seq`, maps error status, and applies `_bound_agent_event_page` (`http_server.py:2176-2204`). The route is bounded to 100 rows; serialized response budget is 1 MiB. Root integration is present in source; T20 must supply the dynamic root receipt.

T20-reported earlier root receipts: event/auth/trace/timeline selector **17 failed, 24 passed in 8.06s**; later auth + operational-mode selector **21 passed, 2 failed in 8.63s**, with failures due to tests expecting absent `_operational_mode_api` and `_redact_config_secrets` seams. T18 did not rerun these root selectors or add shims.

Historical pre-integration patch: `handoff/T18-pre-T20-agent-event-page-route.patch`, SHA-256 `C1D2914106A2593D9598CD20C50DA97390994161C71FE7130B16D132C0DA5A0C`, matched prior root preimages `7BBA75A0A335A1BEF0370F636D65F36477BF0638261723A1778E4DC06BB8B949` and `15F497AEFDE4E2EDFF4D8B6BA158C87FF70731C7F40762F10BE64445646F927`. Original apply-check passed; after T20 changed the root files, rechecked apply-check failed. **Do not apply this historical patch.**
