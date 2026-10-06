# T03 MCP stdio preflight root-current receipt

Date: 2026-10-01 (Europe/Prague)
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Assigned T03 worktree HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Root cause

Both committed HEAD versions end in `if __name__ == "__main__": mcp.run()`; neither has a preflight. Root's current dirty `mcp_server.py` adds `main()` with `CLIENT.ensure_server(timeout=startup_timeout)` before `mcp.run()`. The T03 worktree's current dirty file still runs `mcp.run()` directly. If `ensure_server` returns false, root raises `SystemExit` before FastMCP can answer MCP `initialize`; its broad `except Exception` also discards any underlying exception and returns only the generic startup-timeout text. This makes MCP negotiation depend on HTTP Hub readiness before the first tool call, contrary to `HubClient(auto_start=True)` lazy transport behavior.

Observed provided failure (`Local AI Hub did not become ready ...`) is explained by that control flow. In an isolated baseline reproduction with temp state/config, the actual cold-start tool-call test passed in 16.06s, so the underlying readiness failure is environment/intermittent; the pre-initialize gate is deterministic and covered by fail-first regression below. Do not infer a stable underlying daemon failure from one run.

## Candidate change

Remove only the eager `ensure_server` block. `main()` enters FastMCP stdio immediately; `HubClient` starts HTTP on the first call that needs it. No timeout value changed. Test now asserts initialize response before the successful daemon-off status call and adds a focused unit regression that makes `ensure_server` return false while requiring `mcp.run()` to be entered.

## Hash pins

| Path | Root-current preimage SHA-256 | Candidate postimage SHA-256 |
| --- | --- | --- |
| `src/local_ai_hub/mcp_server.py` | `44205472ECA30794493082930E2D1775BFD4D7F37D189F2289E61CB3783BAEBF` | `FE508F44849E0EBC13C6A26CE71BCBB31E3F813A714C554A7A7A6D2AC3CAEE4A` |
| `tests/test_mcp_live_wire_schema.py` | `959B2E4ADE37E01A079CEABAE06E0E5225A0053FEFA86ACF425A01182B5FAE31` | `772D47A36C65A076B42CF2C70C3834C8EB99CEB0FA6E2E7808AF84B523CDDD29` |

Patch: `T03-main-preflight-root-current.patch`  
SHA-256: `B2F4A17AE555586C9E0D864DC1A05126BE6FDF0FE7FB87E609DD6D83C23FB92E`  
Patch stat: 2 files, 22 insertions, 9 deletions.

## Test receipts

Fail-first against root-current baseline overlay:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short --confcutdir=. tests/test_mcp_live_wire_schema.py::test_stdio_main_does_not_gate_handshake_on_hub_startup
```

Result: `1 failed in 2.86s`, exact cause `SystemExit: Local AI Hub did not become ready within the configured startup timeout` at `main()` before `mcp.run()`.

Patched candidate, focused handshake + real cold-start call:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short --confcutdir=. tests/test_mcp_live_wire_schema.py::test_stdio_main_does_not_gate_handshake_on_hub_startup tests/test_mcp_live_wire_schema.py::test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up
```

Result: `2 passed in 18.62s`. Cold-start test checks MCP initialize protocol version, status tool result, captured Hub/supervisor process cleanup, and asserts no orphan remains.

Patch applicability:

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-main-preflight-root-current.patch
```

Result: `PASS`, only the two paths above. Root hashes remained equal to preimages; root was not modified.
