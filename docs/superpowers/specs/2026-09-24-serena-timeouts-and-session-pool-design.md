# Serena Timeouts, Soft Fallback to CodeIndex, and 1-Hour Project Session Pool

## Goal

1. Eliminate Serena timeout cascades and process thrashing by raising hard timeouts.
2. Introduce a non-destructive soft timeout (4s) that falls back immediately to built-in `CodeIndex` without killing the underlying Serena LSP process.
3. Keep dedicated Serena instances alive and warmed for every project active in the last hour (3600s TTL, increased capacity).

## Current Problem

- `code_intelligence.query_timeout_seconds` is 20s. Heavy symbol searches or AST queries on non-trivial codebases exceed 20s.
- When `MCPStdioClient` times out, it forcefully kills the process (`_stop_process()`), triggering an expensive cold restart (`startup_timeout_seconds = 45`) for the next request.
- All requests behind the project lock queue up and cascade into subsequent timeouts (visible as 2m+ stuck requests).
- `session_idle_ttl_seconds` is 900s (15 minutes) and `max_sessions_per_backend` is 8, terminating sessions prematurely even when projects are actively worked on over an hour.

## Design

### 1. Configuration & Defaults

In `defaults.toml` and `config.py`:
- `query_timeout_seconds = 60`: Hard timeout before killing a stuck process.
- `startup_timeout_seconds = 60`: Bounded startup for heavy language servers.
- `soft_timeout_seconds = 4.0`: Fast threshold. If Serena does not return or lock is contested, caller falls back to `CodeIndex`.
- `session_idle_ttl_seconds = 3600`: 1 hour retention for active project sessions.
- `max_sessions_per_backend = 16`: Accommodates up to 16 concurrent projects within the hour.

### 2. Non-Destructive Soft Timeout & CodeIndex Fallback

In `ExternalCodeIntelligence` (`external_tools.py`):
- `query_serena` accepts `soft_timeout: float | None = None` (defaulting to configured `soft_timeout_seconds`).
- When acquiring the project lock or waiting on `MCPStdioClient`:
  - If the operation exceeds `soft_timeout`, return a soft degradation indicator without terminating the process.
  - The caller immediately delegates to built-in `CodeIndex` (e.g. `find_symbol`, `search`, `related_paths`).
  - Response metadata includes `backend: "code_index"`, `fallback_used: true`, `degraded_reason: "serena_soft_timeout"`.
- If Serena genuinely hangs past `query_timeout_seconds` (60s hard timeout), `MCPStdioClient` invokes `_stop_process()` to reclaim system resources.

### 3. Dedicated Project Session Pool (1-Hour TTL)

- `_serena_sessions: dict[str, MCPStdioClient]` maintains 1 instance per canonical repository root.
- `_session_access["serena"][root]` tracks monotonic access timestamps.
- Pruning (`_prune_sessions_locked`) purges sessions only when inactive for >3600s, or when capacity exceeds 16 active projects.
- Projects touched within the last hour remain alive, warm, and ready for queries.

## Compatibility & Safety

- Existing APIs (`/api/external/query`, `/api/context/pack`, `/api/search`) preserve JSON schemas.
- `fallback_used` and `degraded_reason` are standard telemetry and response fields.
- Subprocess creation retains Windows `CREATE_NO_WINDOW` and clean child process tree teardown on shutdown.

## Verification

- Unit tests in `tests/test_external_tools.py` and `tests/test_reliability_core.py`:
  - Verify `soft_timeout_seconds` fallback to `CodeIndex` leaves client process running.
  - Verify hard timeout terminates process after `query_timeout_seconds`.
  - Verify session pool retains active project sessions up to 3600s and respects `max_sessions=16`.
- Run pytest test suite: `python -m pytest tests/test_external_tools.py`.
