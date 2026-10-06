# T03 MCP HTTP daemon acceptance handoff

Date: 2026-10-03

## Checkout and ownership

Worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`

HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

The worktree had inherited dirty T03 changes before this task. I preserved them without reset, clean, rebase, or root checkout writes. This handoff covers the MCP transport changes and focused tests listed below. `client.py` retains its pre-existing dirty state and was not edited by this task.

## Behavior

- `_build_mcp_client()` constructs `HubClient(tenant=..., config_path=..., auto_start=True)` for the stdio adapter. It does not construct `InProcessTransport` or `LocalAIApp`.
- `main()` enters `mcp.run()` without eagerly starting the daemon. The first HTTP tool request uses the existing bounded `HubClient.ensure_server()` path after connection refusal.
- MCP HTTP requests preserve repository root, tenant, and request ID.
- `_ProtocolAccountingReporter.close()` drains its queue without closing a nonexistent private client; accounting uses the module-level client.
- The direct `InProcessTransport` import remains available for tests/development. The normal stdio builder does not instantiate it.

## Changes covered

- `src/local_ai_hub/mcp_server.py`
- `tests/test_mcp_daemon_proxy.py`
- `tests/test_mcp_autostart_contract.py`
- `tests/test_mcp_compact_transport.py`

The compact transport assertion selects `/api/context/pack` calls separately from metadata-only accounting calls. Endpoint behavior is unchanged.

## Validation

Command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_daemon_proxy.py tests/test_mcp_autostart_contract.py tests/test_mcp_compact_transport.py
```

Result: exit code `0`; `24 passed in 12.31s`. Output: `........................ [100%]`. No stderr or atexit error.

The test receipt proves the bounded startup contract with mocked connection/start behavior. It does not measure live daemon counts or exercise a real daemon process.

## File SHA-256

- `src/local_ai_hub/mcp_server.py`: `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`
- `tests/test_mcp_daemon_proxy.py`: `3C27E5E42323E2FCE0329E6F86E1EB3048D8AE29880318A44A0EE2DD10AFF3E1`
- `tests/test_mcp_autostart_contract.py`: `32DABC37A6809D5058139F74DC8CBE79B9AD7CBF93A11A5EFCFAC798D869C28E`
- `tests/test_mcp_compact_transport.py`: `E08BCE84B542CB3E6615CCB493747159EB8AB9C37536834DD7BF761335D89D54`

No commit was created.
