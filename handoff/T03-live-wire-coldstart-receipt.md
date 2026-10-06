# T03 live-wire and cold-start receipt

Date: 2026-10-01 (Europe/Prague)
Assigned worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Change

Only `tests/test_mcp_live_wire_schema.py` changed in this continuation. Its handshake now uses an interactive subprocess: send `initialize`, receive its response, then send `notifications/initialized` and `tools/list`; close and reap the server in `finally`, drain and close both output pipes. This prevents feeding all requests followed immediately by EOF and retains diagnostics if a response times out.

## Exact validation

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_live_wire_schema.py
```

Result: `3 passed in 17.53s`.

Coverage includes live stdio initialize/tool listing, exact equality between all eight feature-enabled registered tool schemas and `operation_tool_input_schema`/`operation_tool_output_schema`, import-safe behavior when FastMCP SDK import is blocked, and a real daemon-off MCP `tools/call` that auto-starts an isolated Hub and cleans the captured Hub/supervisor processes.

The handshake alone after interactive transport change: `1 passed in 4.51s`.

Previous combined run before the change: `95 passed, 1 failed in 40.39s`; the handshake had no `tools/list` id-2 response when requests were batch-fed then stdin closed. No source runtime code changed. Following the interactive fix, the live-wire file passed as a bounded three-test suite. This is direct evidence for the affected tests; it is not a high-iteration flake stress claim.

Additional focused transport receipts from this continuation:

- HubClient concurrent start, timeout/reap, pre-existing server preservation, and listener-owner preservation: `4 passed in 2.29s`.
- Stream cancellation and coalescing timeout: `2 passed in 2.34s`.
- MCP action schema/dispatch/recovery/autostart/live-wire combined run before interactive fix: `95 passed, 1 failed`; only failure was the handshake issue described above.

Root-current artifact slice bounds were independently integrated by the root owner and verified there; do not apply the obsolete patch. No `/api/context/pack` edit.

## Remaining boundary

A known client transport pubsub selector failure is recorded in the pre-existing T03 plan evidence (`test_coord_pubsub_poll_uses_after_seq_in_json_body`) and is T04-owned; no client transport code was edited here. Local AI Hub command/review/Agent OS APIs were not exposed in this session, so no Hub verification receipt or task completion transition is claimed.
