# T18 / T31 route and symbol ownership — 2026-10-03

## Evidence pins

Read-only map against root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`:

- `src/local_ai_hub/http_server.py` — `7CE0E3D38979220917443CBF1FC24FFACCA8254ACD9E878E456FBB97C7A936EE`
- `src/local_ai_hub/dashboard.py` — `6212C9D58EF6E3315A048DFF501D1B33B425E554CD96893932C3EAEE18516FE7`
- `src/local_ai_hub/app.py` — `92017513BADBC10D09580367E6FF8DC0A9873C709C75DA940D79DB45DD75D822`
- `src/local_ai_hub/telemetry.py` — `07D8651FE93B42363873348088611E54D9376CB52B820C01BD81D703637BC48A`

No tests run. No root/source edits. T31 `/api/context/pack` and T03/T07 endpoint handlers excluded. No T20 lease acquired.

## T18 ownership map

| Route/symbol | T18 ownership | Current implementation boundary |
|---|---|---|
| `GET /dashboard`; `DASHBOARD_HTML` | Dashboard shell/UI. Client status/mode display and refresh behavior. | Route is a branch inside shared `HubRequestHandler.do_GET` (line 2094). Keep shared dispatcher in place. Shell is public, contains no runtime data. |
| Dashboard health: `dashboardHealthBadge`, `dashboardHealth` | Status presentation and unknown/degraded health display. | Inline JS in `dashboard.py`; dashboard reads `GET /api/live/status`. |
| Dashboard status poll: `pollStatus` | Status payload consumption, timeout/backoff, visibility and stale-response behavior. | Inline JS at `dashboard.py:5202`; it calls `/api/live/status?light=1&scope=...`. Candidate-only `dashboard_status_poller.py` is not root ownership evidence; root implementation remains inline. |
| Dashboard activity mode UI: `renderActivityMode`, `refreshActivityMode`, `applyActivityMode` | Client display and server-confirmed transition/failure rendering. | UI only. `/api/mode` and `/api/admin/mode` route handlers and auth/mode policy remain T13-owned. |
| `GET /api/live/status` | T18 status view contract and coverage. | Shared `do_GET` branch at 2109 calls `LocalAIApp.realtime_status(light, scope)`; may attach HTTP concurrency snapshot. |
| `GET /api/status` | T18 full status view contract and coverage. | Shared `do_GET` branch at 2116 calls `LocalAIApp.status(scope)`; `detail=agent_state` is a separate detail branch outside T18 status snapshot. |
| `LocalAIApp.realtime_status`, `LocalAIApp.status` | T18 status snapshot/degradation behavior and coverage. | `app.py:687`, `app.py:850`; no HTTP route movement implied. |
| `GET /api/live` | T18 dashboard event-poll consumption/overlap behavior. | Shared `do_GET` branch calls `TelemetryStore.live`; no POST extraction. |
| `GET /api/metrics`, `/api/telemetry/report`, `/api/telemetry/timeline` | T18 telemetry report/page/bounds and persisted-safe-error coverage. | Shared `do_GET` branches call `summary`, `report`, `get_timeline_page`; no route extraction. |
| `POST /api/telemetry/timeline` | T18 regression-tested legacy read-page parity only. | Shared `do_POST` branch at 4989. T31 may extract only with explicit T20 lease; preserve verb-specific auth/mode/payload behavior below. |

## Exclusions and shared ownership

- `HubRequestHandler.do_GET` and `do_POST` remain central shared dispatchers. T18 owns behavior/consumer contracts above, not whole methods.
- Shared auth/mode symbols (`_require_authorized`, `_http_admin_action`, `_http_mode_policy`, `_http_mode_gate_error`) are parity constraints, not T18 edit targets. T13 may enforce shared gates; retain existing action/scope decisions.
- `/api/mode` and `POST /api/admin/mode` are T13 route implementations. T18 owns only dashboard UI consumption.
- `POST /api/telemetry/tool-accounting` is a telemetry writer, not T18 read surface. Keep with its current owner; do not fold it into T18 read descriptors.
- Do not transfer T03/T07 handlers or `/api/context/pack` under T18 ownership.

## Parity contract for any later route extraction

| Surface | Auth parity | Mode parity | Status/result and payload parity |
|---|---|---|---|
| Dashboard shell | Public shell; data/control APIs still authenticate. | Operator route, mode-independent. | `200 text/html`; `404` when disabled; no body or tenant. |
| `/api/live/status` | `status.read`; global token or matching action token; loopback only when token policy is empty. No tenant binding/filter. | Operator GET, allowed in active/gaming/maintenance. | GET query only: `light` default false, `scope` default `process`. HTTP `200` snapshot may report degraded status; preserve `http_concurrency` when server provides it. |
| `/api/status` | `status.read`; same token/loopback rule; no tenant filter. | Operator GET, allowed in all modes. | `scope` default `process`; `detail=agent_state` selects its special envelope. Current root has no `detail=summary|light` branch; do not import that candidate-only behavior silently. HTTP `200` full snapshot may be degraded. |
| `/api/live` | `telemetry.read`; no tenant filter; events can contain record tenant labels. | Active mode only: path is not in operator or gaming-read GET sets. | Query `after` default `0`, `limit` default `200`, capped by configured `monitoring.live_max_batch` and store max `1000`; no body. Returns `{success,cursor,oldest,events}`. |
| `/api/metrics` | `telemetry.read`; no tenant filter. | Operator GET, any mode. | Query `days=30`, `scope=window`; no body. `summary()` may flush pending events for up to `0.5s` on cache miss. `{success,metrics}`. |
| `/api/telemetry/report` | `telemetry.read`; no tenant filter. | Operator GET, any mode. | Root query names: `days=30`, `scope=window`, `recent_errors=25`, `error_offset=0`, optional `error_cursor`. Store bounds: days `1..retention`, recent errors `1..100`, offset `0..100000`; flush up to `1s`; response cap `256KiB-64`. Returns `{success,report}`. Invalid `recent_errors`/`error_offset`, malformed cursor, or cursor+offset is `400`, terminal, non-retryable. `days` conversion is outside this 400 handler. Candidate `error_limit` name is stale. |
| `/api/telemetry/timeline` GET | `telemetry.read`; no tenant filter. | Operator GET, any mode. | Query `limit=100`, optional `before_id`; store clamps limit `1..500` and cursor `0..2^63-1`; flush up to `0.2s`; no body. Returns `{success,timeline,next_cursor,has_more}`. |
| `/api/telemetry/timeline` POST | No POST `telemetry.read` action mapping: configured global token required; no scoped telemetry token. | Active mode only (POST path is not operator/gaming-read allowlisted). | JSON `limit=100`, optional `before_id`; generic body cap `server.max_request_body_bytes` (default 16 MiB). Same page envelope and bounded flush as GET. Keep separate row; do not normalize to GET auth/mode during extraction. |

Read-route auth envelope: unauthorized `401`; admin-audit unavailable `503`; rate limit `429`. Blocked non-operator modes use retryable `503` operational-mode envelope. Tenant source is absent for status and telemetry reads; reads are global, not tenant-filtered.

## Exact existing tests and gaps

- Dashboard shell/mode/degraded display: `tests/test_dashboard_operational_surfaces.py::test_dashboard_route_serves_live_http_document`, `::test_dashboard_exposes_activity_mode_and_reports_http_failures`, `::test_dashboard_requires_server_confirmation_before_reporting_mode_update`, `::test_status_poller_respects_visibility_unchanged_state_and_jitter`; `tests/test_dashboard_mode_playwright_t18.py::test_dashboard_mode_dom_auth_and_error_projection`.
- Status: `tests/test_status_snapshot_quality.py::test_status_route_surfaces_structured_probe_failure`, `::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape`, `::test_status_uses_one_deadline_across_slow_dependencies`, `::test_realtime_status_bounds_runtime_health_probes`, `::test_realtime_status_surfaces_stored_sqlite_error_summary`.
- Telemetry: `tests/test_telemetry_report_bounds_t18.py::test_telemetry_report_http_route_forwards_error_cursor`, `::test_report_budget_truncation_advances_cursor_after_retained_rows`; `tests/test_telemetry_timeline_paging_t18.py::test_http_timeline_get_and_post_page_before_cursor`; `tests/test_telemetry_error_diagnostics_t18.py::test_error_diagnostics_are_actionable_bounded_and_private`, `::test_public_error_report_and_dashboard_expose_only_safe_diagnostic`; `tests/test_telemetry_sqlite_dashboard_t18.py::test_dashboard_summary_uses_bounded_safe_diagnostics_from_sqlite`.
- Auth gap: `tests/test_http_admin_action_auth_t18.py::test_action_tokens_are_scoped_and_authorization_is_audited` proves `trace.read`/`config.write`, not `status.read`/`telemetry.read`. Add an explicit read-scope selector before claiming those scopes are test-locked.
- Root parity gaps: root `GET /api/status` lacks candidate `detail=summary|light`; report accepts `recent_errors`, not candidate `error_limit`. No tests run in this handoff.
