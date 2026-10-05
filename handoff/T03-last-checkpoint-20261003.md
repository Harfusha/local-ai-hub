# T03 current owned-scope handoff — 2026-10-03

## Verified checkout state

- T03 candidate root: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
- Candidate HEAD: `d68ee694c6d3f75db5c1ab2f63497226880e5010`
- Integration root: `C:\Users\Adam\.local-ai-hub`
- Integration HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Root has not been written.
- Candidate is dirty across multiple owner scopes: `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `src/local_ai_hub/async_jobs.py`, `generator.py`, `http_server.py`, `mcp_server.py`, `operation_contracts.py`, `services.py`, `tests/test_features.py`, `test_mcp_agent_routing.py`, `test_mcp_compact_transport.py`, `test_mcp_output_contracts.py`, `test_operation_contracts.py`, `test_task_context_task_integration.py`; untracked paths include `.t03-root-overlay/`, a Hub auto-start plan, `handoff/`, `inprocess_transport.py`, async/operational mode tests, path-hint search tests and write-set dispatch tests. Do not stage or integrate this broad dirty state.

## T03 ownership boundary

T03 owns MCP/API contracts and only the search-hint route slice:

- Public `local_ai_repo(action="search").path_hints` schema, bounds and action scoping in `operation_contracts.py`.
- MCP search normalization, root confinement and forwarding in `mcp_server.py`.
- The `POST /api/search` route's optional `path_hints` forwarding and unsupported-service response in `http_server.py`.
- Alias-advertised input schema and canonical validation/output selector, while preserving the original alias for handler dispatch.

T03 does **not** own the shared `Handler.do_POST` dispatcher, service retrieval/project-config behavior (`services.py`, T21), client serialization/transport (`client.py`, T04), `/api/context/pack` (T14), or operational-mode gate (`mcp_server.py`, T13). T16's `worktree_id` cleanup caller chain shares `http_server.py` as a file only; its cleanup route/process helper hunks are disjoint from T03's `/api/search` hunk. Integrate only the patch hunks below; do not replace dirty files.

## Root-current overlays and exact preimages

Keep the overlays separate. A just-tested concatenation was rejected by `git apply --check` as `tests/test_mcp_contract_dispatch.py: wrong type`, because two independently formatted patches modify that same test file. The invalid concatenation was deleted. Use the three standalone patches listed below; alias+output hunk composition was already checked on disposable preimage copies.

1. Alias schema/dispatch: `handoff/T03-root-current-alias-dispatch-20261003.patch`, SHA-256 `3661535DFCBAC27C93C82829F0E28EEFF83E89CCB2F69246D2038D1FB13DDCE9`.
   - Files: `src/local_ai_hub/mcp_server.py`, `tests/test_mcp_contract_dispatch.py`.
   - Root preimages: `mcp_server.py` `C61467CF7B8E3DFF4E105EE39B22742D488BC78791FFD05DBDAE5AB53B27E0ED`; dispatch test `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`.
2. Typed repo-search output contract: `.t03-root-overlay/handoff/T03-repo-search-output-contract.patch`, SHA-256 `9AECAF2A7EF64B7422E1A5E50F7BF388AAF9AB9C8663DFC74A9F3BC939D91472`.
   - Files: `src/local_ai_hub/operation_contracts.py`, `tests/test_operation_contracts.py`, `tests/test_mcp_contract_dispatch.py`.
   - Root preimages: `operation_contracts.py` `1CB6942E888506897F4C994062654D08524D546CE93A12707EE1C08D99A783BB`; operation test `6F15CBF4E045B6D5D6A316CD27636090661270142376AA13C97A8A85B24DD3F1`; dispatch test `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`. The bounded `path_hints` input contract is already in this root preimage.
3. HTTP search-hint signature compatibility: `handoff/T03-root-search-route-compat-20261003.patch`, SHA-256 `745D212E9A625B4C1CAA5589708F50A4A3D96BD642D23A69B0E1631A2A45062C`.
   - File: `src/local_ai_hub/http_server.py` only; route hunk plus `inspect` import.
   - Root preimage SHA-256: `7CE0E3D38979220917443CBF1FC24FFACCA8254ACD9E878E456FBB97C7A936EE`.
   - Candidate hunk preserves omission of the keyword when absent; if hints are sent but the service signature does not support them, returns HTTP 501 with `unsupported: true` instead of leaking `TypeError`. Current root T21 service accepts `path_hints`; this overlay changes only the route's graceful unsupported-service behavior.
4. MCP client-factory contract regression: `handoff/T03-root-mcp-factory-test-20261003.patch`, SHA-256 `7E103CDEC07B5102824A5DE71F3EA02375C6BB95F518BA4F29F847EBCC09C326`.
   - File: `tests/test_mcp_compact_transport.py` only; adds the existing candidate test that verifies tenant, config path and `auto_start=True` forwarding.
   - Root preimage SHA-256: `C010F2F4E05BC8E6EDEA37B5923B1E28F2153647DA4212E5DFEACF2CDDF2C97F`.
   - Read-only apply-check passed at root HEAD above (exit 0); not applied.

Union of exact scoped patch paths: `src/local_ai_hub/mcp_server.py`, `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/http_server.py`, `tests/test_mcp_contract_dispatch.py`, `tests/test_operation_contracts.py`, `tests/test_mcp_compact_transport.py`.

Read-only root apply-check for overlay 3 passed at the root HEAD above (exit 0). The command broker rejected `git apply --check` because root is not a registered task-owned worktree (`terminal=true`, `retryable=false`); one native read-only fallback was used. The patch was not applied. Overlays 1 and 2 have prior root-current apply-check and sequential disposable-preimage composition receipts in `handoff/T03-root-current-contract-alias-20261003.receipt.md`.

## Exact acceptance selectors after T20 GO

Run as one serialized owner-approved acceptance set; no tests were run for this handoff:

- `tests/test_mcp_contract_dispatch.py::test_mcp_action_alias_schema_and_dispatch_use_canonical_contract`
- `tests/test_mcp_contract_dispatch.py::test_live_mcp_schemas_match_registry_for_every_public_tool`
- `tests/test_mcp_compact_transport.py::test_mcp_client_factory_forwards_tenant_and_config`
- `tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_context_scoped`
- `tests/test_operation_contracts.py::test_local_ai_repo_path_hints_normalize_and_reject_root_escape`
- `tests/test_mcp_repo_path_hints.py` (module; legacy path and typed hints dispatch)
- `tests/test_api_search_path_hints.py::test_api_search_forwards_path_hints_to_repo_search`

T04 additionally owns `tests/test_client_path_hints.py`, including its route gate assertions. Include that module only after T04's client/API candidate is integrated and its owner confirms the expected allowed route set. T21 owns service/retrieval acceptance; include T21's exact selectors after its integration receipt. Prior candidate `3/3` and T20 path-hint `30 passed` are historical external receipts, not evidence from this checkout or this root revision.

## Current gate

T20 remains **NO GO / UNKNOWN**: its latest attempted owner-scoped release failed with `worktree ownership identifier is required`. No tests were run here. Root acceptance remains pending the authoritative T20 slot grant and T04/T21 dependencies.
