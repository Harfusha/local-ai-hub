# T01 MCP coord gap handoff — 2026-10-02

## Exact manifest gaps

| Priority | Operation | Owner | Candidate selector |
| --- | --- | --- | --- |
| 1 | `op-28d63e90525c` — MCP action `local_ai_coord::task_rollback` | T08 | `tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint` |
| 2 | `op-a9ceb516370a` — MCP tool `local_ai_coord` | T03 | `tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch` |

Both selectors are listed in the T01 operation selector evidence and absent from the current root test file. Rollback selector covers checkpoint restoration, persisted checkpoint, and `task.rolled_back`; feature-gate selector verifies a valid action fails before any backend method dispatch.

## Candidate receipt

- Worktree: `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub`
- HEAD: `689165fbe18101feacf5f489847a4890fc27ed1f`
- Both selectors are included in the completed unique candidate run: **63 passed in 25.96s**, exit 0; see `T01-current-operation-selector-run-20261002.md`.
- Candidate source file SHA-256 for the 63-selector run: `2EA4B59D11DB9519C3FC1D2A98C22AAC78E68D67B8C31C802602F16D4FFC11B6`.
- After T20 released the root slot, exact candidate-only command ran in T01:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch
  ```

- Result: **2 passed in 2.56s**, exit 0. The command broker request failed before write (`request_not_sent=true`); this exact command then ran once natively in the authorized T01 worktree.
- Added 32 named action-forwarding tests, 21 MCP protocol tests for canonical actions and aliases, and 7 schema-gap diagnostics. The 60 selectors after `_prepare_coord_api` are still unrun pending T20 slot release; the two earlier selectors have separate passing receipts above.
- Current T01 test SHA-256: `0DB2EB213FF4F8B121F8B82EA12340C5F01558EED03D1B780DC60BD0467CABB5`; T01 `mcp_server.py` SHA-256 remains `8104895506A3FB0B063C41D42362A9B47367AEAA355E8AEE32DF564FF968E56A`.
- Pending selector file: `handoff/T01-mcp-coord-pending-selectors-20261002.txt`, SHA-256 `12145D5EFFB52AF133B64101BB72EA70B882EF31A050369CC0EDE89F83634FEA`; it contains 60 selectors.
- Reserved-slot command:

  ```powershell
  $selectors = Get-Content handoff/T01-mcp-coord-pending-selectors-20261002.txt
  python -B -m pytest -q -p no:cacheprovider --tb=short $selectors
  ```

- Rebuilt handoff map only: 59/446 historical gap rows linked; 58 have targeted selectors; 387 remain unlinked; 127 unique candidate selectors; root-green 0. Selector-map JSON SHA-256 `BFF32CD60D5236779173009498B8259CA8D416F547A70637CA14FCF2ADC82238`; gap-map JSON SHA-256 `D10D49FCE365260595CA94AACD70D5381A3E4E2C012BC2D65B8B27DF688DAD77`.
- The 7 T03-owned `MCP action schema gap local_ai_coord` rows now each have a candidate selector in that map; tests and map are candidate evidence only until execution and T03 contract resolution. Seven protocol selectors for `blackboard_update`, `context_compile`, `incident_decision`, `memory_get`, `memory_record`, `task_create`, and `verify_receipt` are outside the historical gap-map row set.

## Remaining MCP coord schema rows

Seven unlinked rows remain, all surface `MCP action schema gap local_ai_coord`, owner T03: `op-db688a5eedb4` `claim_batch`; `op-dad19ce3e476` `curate_training_dataset`; `op-b0d3c8bd69ad` `delete`; `op-9205ce46f2ca` `get`; `op-ce44f3483a73` `lease_renew`; `op-b1cb625a2e0c` `list`; `op-4ae1b9fe51e3` `merge`. Inventory distinguishes these from supported MCP action rows; schema ownership remains T03. Do not count them as supported operation coverage without T03 contract resolution.

## Root-current patch receipt

- Consolidated test-only patch: `handoff/T01-root-mcp-coord-current.patch`
- Patch SHA-256: `D7EA302829B2D71542131E4C205AE5DE1C0D3690559D8EA7C948B50A69A66B8D`
- Root test preimage SHA-256: `303BB30536AD6BBF223C21738CBC482AF22539BEC09726CEF390D4CDF7F8FCFF`
- Exact target: `tests/test_mcp_coord_operation_acceptance.py`; patch adds 62 tests (two already-run selectors plus the 60-selector pending batch) and test imports only.
- Scratch preimage hash matched root preimage. `git -c core.whitespace=cr-at-eol apply --check --whitespace=error` passed, exit 0. Patch was not applied. Root test file SHA remains `303BB30536AD6BBF223C21738CBC482AF22539BEC09726CEF390D4CDF7F8FCFF`.
- Root tests remain pending; T20 owns root integration and the active test slot.

## Scope and evidence limits

- No root files changed; root test preimage remains `303BB30536AD6BBF223C21738CBC482AF22539BEC09726CEF390D4CDF7F8FCFF`. No root tests, builds, Hub service calls, or generated inventory checks were run.
- Candidate selectors establish candidate-worktree behavior only; no root-green receipt for MCP coord rows yet.
- Keep `/api/context/pack` excluded. Do not rerun inventory `--check` because its generator may rewrite `docs/API_COVERAGE.md`.
