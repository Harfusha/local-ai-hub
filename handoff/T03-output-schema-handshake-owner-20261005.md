# T03 MCP output-schema handshake owner packet

- Owner worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
- Base HEAD: `d68ee694c6d3f75db5c1ab2f63497226880e5010`
- Scope: T03 MCP output-schema registration and focused contract tests. Existing unrelated dirty hunks preserved.
- Root: frozen; no root files read or written in this turn. `/api/context/pack` untouched.
- RAG evidence: `local_ai_rag(action="search")` dispatches to `/api/rag/search`; accepted response delta declares `results` as an array of objects with integer `chunk_no`. `tools/list.outputSchema` now publishes this action delta under `x-action-output-contracts.search` and retains it in top-level properties.
- Test API drift: removed stale `operation_actions` test import; alias test now uses active canonical actions from `mcp_server._ADOPTION_ACTIONS` intersected with the live action enum.

| Changed path | HEAD blob | HEAD SHA-256 | Owner pre-hunk SHA-256 | Post SHA-256 |
|---|---|---|---|---|
| `src/local_ai_hub/operation_contracts.py` | `6f9f6e1cec106be77fc4febcca27f4fec3d62ff7` | `c77dc63759e34dac4dbe6febeee95246a1c166f5972d41123240228e6ec47ecb` | `22b92715233766c9c44c423d118bc9294afe41b83559542464d4778a99f138ec` | `583136a0d4fa1d1b78436a81dbbb991535f7afb6fa68d771963053671e78697d` |
| `tests/test_mcp_stdio_contract.py` | `fbefab2a23174415232719c94c9a2117f661683d` | `a44e12242f804668fc43b4e83dc8baa5271d5e9f83675e3bbe75e9750d3608d6` | `a44e12242f804668fc43b4e83dc8baa5271d5e9f83675e3bbe75e9750d3608d6` | `1baed48579ec7dfc50d1d93686975158c8ac642bb2926a10bd523813d43f93ba` |
| `tests/test_mcp_output_contracts.py` | `fc12d1fc0c9f906e2b715d40ef3251773c3b54e7` | `2ad56800a3952d8778a9e1af7570f595f6c2914cf7f212463ed7b590d1769bec` | `451a4cc9b3998221c81b88ca375a53441cbc3f8b02004e2b95053a7d70fd4fc9` | `13f8549b5f65bc1b75beb1667c4f88b235533b10eb2c0ac9d8e9e872012ceda0` |

## Exact owner patch

Patch file: `handoff/T03-output-schema-handshake-owner-20261005.patch`

Patch SHA-256: `31d41abef8487610a53363bb9a5f95326057f3a859bf4cad176f6e6f9b8145a0`

## Test receipts

1. Red reproduction:
   `PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_stdio_contract.py::test_stdio_handshake_publishes_all_registered_live_schemas`
   Result: `1 failed in 4.33s`; `local_ai_rag` had only shared-envelope properties, failing the old bare-generic expectation.
2. Final bounded validation:
   `PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_stdio_contract.py::test_stdio_handshake_publishes_all_registered_live_schemas tests/test_mcp_output_contracts.py::test_live_mcp_outputs_match_generated_http_facing_contracts tests/test_operation_contracts.py::test_status_output_schema_publishes_shared_error_envelope`
   Result: `3 passed in 4.15s`.
3. Intermediate collection failure corrected before final validation: `tests/test_mcp_output_contracts.py` imported absent `operation_actions`; test now uses the existing live action catalog.

Final handshake asserts wire `tools/list.outputSchema == registered.output_schema` for every enabled tool; RAG `search.results` array and `chunk_no` integer are asserted explicitly. No broader suite run.
