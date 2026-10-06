# T04 current-root acceptance receipt

Date: 2026-10-01 (Europe/Prague)

Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

T04 patch: `artifacts/t04-current-root-api-acceptance.patch`, SHA-256 `1E8740300FDACFC3B407788E2DD5D20321407A005EB6F802B84F85FDAF4171A1`. The patch adds two HTTP contract corrections and focused tests for POST/GET `resolve_imports`, unsupported chat-completions payload behavior, and `HubClient.list_tasks(query)` serialization. `git apply --check --recount --verbose` passed before integration. T20 integrated the patch; T04 made no root writes.

Exact root command executed by T20:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_current_root_acceptance.py tests/test_agent_task_query.py tests/test_client_transport.py::test_continue_conversation_sends_task_over_real_http_and_keeps_transcript tests/test_conversation_continue_route_contract.py tests/test_client_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_operation_contracts.py::test_repo_search_path_hints_schema_is_bounded_and_search_only tests/test_operation_contracts.py::test_local_ai_repo_path_hints_normalize_and_reject_root_escape tests/test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields
```

Actual output: `.............................. [100%]` then `30 passed in 84.98s (0:01:24)`. Exit code `0`. This batch covers T04 API fixes, task query client/MCP/HTTP contracts, real HTTP conversation continuation, route continuation, path-hint client/MCP/HTTP slices, and the non-context action guard. No test result here is candidate-only.

Root SHA-256 at receipt time: `src/local_ai_hub/http_server.py` `6B6E79EF059941592B532FF0F7C617A97770D3C31F923C00EB254D28169553A2`; `tests/test_t04_current_root_acceptance.py` `F2356F8E15D915966BF76CDD9CDFE04CC9A78E6FA59D62D37AF63AF74A137A17`; `src/local_ai_hub/client.py` `DDB55EDA5F1949B19A876106E056A0C92992AA4D00BF711D85EFB67D3809A562`; `src/local_ai_hub/mcp_server.py` `CA57DCD703F6C7E85897A7E805556EAFD46A351C51CF4BE8833962FEEE64D45B`.

`git diff --check` passed for the integrated HTTP source and new test file. T04 patch does not mention or edit `/api/context/pack`; Agent 2 ownership preserved.
