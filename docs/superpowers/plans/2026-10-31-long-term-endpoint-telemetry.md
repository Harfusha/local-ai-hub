# Long-Term Endpoint & MCP Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement persistent, unexpiring long-term telemetry for all HTTP endpoints and MCP tools in Local AI Hub with logarithmic latency histograms (p50/p95/p99), call counts, success rate, global and per-project drilldown, reset support, and a responsive bar chart section at the bottom of the Tasks dashboard page.

**Architecture Decisions:**
1. Dedicated SQLite store `state_dir / "endpoint_stats.sqlite3"` to prevent 30-day raw event pruning from invalidating long-term stats, avoiding alterations to strict canonical `telemetry.sqlite3` table contracts.
2. Logarithmic histogram buckets (`<5ms`, `10ms`, `25ms`, `50ms`, `100ms`, `250ms`, `500ms`, `1s`, `2.5s`, `5s`, `10s`, `30s`, `60s`, `>60s`) providing $O(1)$ constant storage size per endpoint/project combination while retaining accurate p50/p95/p99 latency calculations.
3. Registered surface inventory catalog allowing unused endpoints and MCP actions (0 calls) to be explicitly visible in the dashboard alongside active ones.
4. HTTP API routes: `GET /api/telemetry/endpoint-stats` and `POST /api/telemetry/endpoint-stats/reset`.
5. Visual bar chart rendered in a new section at the bottom of the Tasks (`agentos`) tab in `src/local_ai_hub/dashboard.py`.

---

## Tasks

### Task 1: Dedicated Long-Term Endpoint & MCP Statistics Store
- [ ] Create `src/local_ai_hub/endpoint_stats.py` implementing `EndpointStatsStore`:
  - Logarithmic bucket boundaries: `(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000)`.
  - SQLite table `endpoint_stats`: `(scope_root TEXT NOT NULL, item_type TEXT NOT NULL, item_name TEXT NOT NULL, calls INTEGER NOT NULL, success_calls INTEGER NOT NULL, fail_calls INTEGER NOT NULL, b0..b13 INTEGER NOT NULL, last_used REAL NOT NULL, PRIMARY KEY(scope_root, item_type, item_name))`.
  - Method `record_call(item_type: str, item_name: str, duration_ms: float, success: bool, root: str = "") -> None`: Thread-safe SQLite record or write queue.
  - Method `get_stats(root: str | None = None) -> dict[str, Any]`: Computes `p50`, `p95`, `p99`, `success_rate`, `calls` per item (aggregating global when `root` is None or `""`).
  - Method `reset(root: str | None = None) -> None`: Resets stats globally or for a specific project.
  - Function `get_registered_surface_catalog() -> list[dict[str, str]]`: Returns complete catalog of all known HTTP endpoints and MCP tools so uncalled items are included with 0 calls.
- [ ] Write unit tests in `tests/unit/test_endpoint_stats.py`:
  - Test recording calls and histogram bucket assignments.
  - Test percentile calculations (p50, p95, p99) against synthetic known distributions.
  - Test global vs project-specific aggregation.
  - Test uncalled catalog items reporting 0 calls.
  - Test reset functionality.

### Task 2: Instrumentation in HTTP Server & MCP Server
- [ ] Update `src/local_ai_hub/app.py`:
  - Instantiate `APP.endpoint_stats = EndpointStatsStore(state_dir)`.
- [ ] Update `src/local_ai_hub/http_server.py`:
  - Extract project `root` from incoming request query/payload if present.
  - Call `APP.endpoint_stats.record_call(item_type="endpoint", item_name=path, duration_ms=elapsed_ms, success=reliability_success, root=safe_root)` in response completion.
- [ ] Update `src/local_ai_hub/mcp_server.py`:
  - When recording tool accounting, extract tool action (e.g. `local_ai_repo:context` or tool name) and project `root` argument.
  - Post or record call to `endpoint_stats`.
- [ ] Write integration test in `tests/test_endpoint_stats_integration.py` verifying HTTP and MCP calls populate `endpoint_stats`.

### Task 3: HTTP API Routes for Long-Term Stats
- [ ] Register routes in `src/local_ai_hub/http_route_registry.py`:
  - GET `/api/telemetry/endpoint-stats`.
  - POST `/api/telemetry/endpoint-stats/reset`.
- [ ] Implement handlers in `src/local_ai_hub/http_server.py`:
  - GET `/api/telemetry/endpoint-stats`: Accepts `?root=...`, returns `{success: true, projects: [...], items: [...]}`.
  - POST `/api/telemetry/endpoint-stats/reset`: Accepts optional `{"root": "..."}` to reset specific project or all.
- [ ] Write tests in `tests/unit/test_endpoint_stats_api.py`.

### Task 4: Dashboard UI & Bar Chart on Tasks Page
- [ ] Edit `src/local_ai_hub/dashboard.py`:
  - At the bottom of `<div id="agentos" class="page">`, add `<section class="section" id="endpointStatsSection">`.
  - Add toolbar controls: Project filter dropdown, Type filter (All / Endpoints / MCP), Sort dropdown (Most calls, Unused/least used, Slowest p95, Most failing), Refresh button, Reset button.
  - Add Bar Chart container rendering visual horizontal/stacked bars for p50, p95, p99 latency alongside call count badge and success rate % indicator.
  - Add summary badges: Total endpoints, active count, unused count (0 calls), slow (>1s p95) count, failing (<95%) count.
  - Implement client-side fetch, render, sorting, project filtering, and reset confirmation handler.
- [ ] Write UI smoke test or verify dashboard HTML structure in `tests/test_dashboard_endpoint_stats.py`.

### Task 5: End-to-End Validation & Verification
- [ ] Run `python -m compileall -q src tools tests`.
- [ ] Run test suite `python -m pytest -q tests/unit/test_endpoint_stats.py tests/test_endpoint_stats_integration.py tests/unit/test_endpoint_stats_api.py tests/test_dashboard_endpoint_stats.py`.
- [ ] Run `python tools/release_check.py --allow-installed`.
- [ ] Verify completion with `local_ai_coord(action="verify_completion")`.
