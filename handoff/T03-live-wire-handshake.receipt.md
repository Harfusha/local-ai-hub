# T03 live-wire schema handshake receipt

Date: 2026-10-01 (Europe/Prague)
Worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Result

The isolated stdio handshake test passed. It launches `python -B -m local_ai_hub.mcp_server`, sends MCP `initialize`, `notifications/initialized`, and `tools/list`, then compares all registered names plus every input and output schema against the operation registry and FastMCP registration.

Exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_live_wire_schema.py::test_stdio_handshake_publishes_all_registry_input_and_output_schemas
```

Result: `1 passed in 5.14s`.

## Combined-run flake

The targeted combined acceptance command (`test_operation_contracts.py`, `test_mcp_contract_dispatch.py`, `test_mcp_autostart_contract.py`, `test_recovery_journal_contract.py`, `test_mcp_live_wire_schema.py`) returned `95 passed, 1 failed in 40.39s`. Failure was `StopIteration` because the handshake subprocess emitted no response with id 2 (`tools/list`). The same exact handshake test passed alone immediately afterward. No code fix is justified by the isolated evidence; retain this as an intermittent stdio batching/startup flake pending a focused reproduction. The cold-start actual `tools/call` test in the same combined run passed.

Root-cause investigation reproduced a distinct diagnostic-probe mistake: a PowerShell-quoted ad hoc command supplied literal backslash-n separators, so MCP correctly rejected trailing JSON characters. This was not the test's input construction and does not explain the combined-run flake.

No source patch was made for this observation.
