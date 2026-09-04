# Cloud-agent hot-path optimization implementation plan

> **For Codex:** Execute in this order, keeping model runtime settings unchanged.

**Goal:** Make cloud-agent use faster and more observable by default while
preserving explicit full-context quality and transient-backend recovery.

**Architecture:** The MCP boundary chooses deterministic-fast context; the
telemetry/dashboard boundary chooses a process or rolling-window cohort; the
preprocessor records permanent external-root failures as revision-scoped skips.
No local model setting is changed.

## Tasks

1. Add red tests for default/explicit MCP context mode and telemetry scope.
2. Add red tests for stale-root external-index skip behavior while retaining the
   existing degraded transient-failure behavior.
3. Implement consistent MCP forwarding in `src/local_ai_hub/mcp_server.py` and
   `mcp/local_ai_mcp.py`.
4. Thread telemetry scope through `TelemetryStore`, realtime status, HTTP live
   status, and dashboard selector/labels.
5. Classify only missing-root/permanent project-configuration errors as skipped.
6. Run focused tests, complete suite, compile/selftest, then live-process checks.
