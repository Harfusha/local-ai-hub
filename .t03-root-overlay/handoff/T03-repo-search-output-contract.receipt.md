# T03 `repo.search` output contract handoff receipt

Date: 2026-10-01
Workspace: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub\.t03-root-overlay`
Root target: `C:\Users\Adam\.local-ai-hub` (not modified)

## Scope and ownership

Patch contains only the T03-owned operation contract and two contract/dispatch test files. It leaves shared result envelope open, preserves the eight MCP tools, and exposes compact `x-action-output-contracts` payload deltas. `repo.search` hit fields are type checked; `preprocessed_hit` and `progressive_disclosure` remain optional. Disabled action output schemas are omitted. Registered `local_ai_status` output catalog uses `brief`.

Optional `path_hints` for `local_ai_repo(action="search")` already exists in the root baseline and is covered in `test_repo_path_hints_schema_is_bounded_and_context_scoped`: bounded input schema, valid hint, and malformed/oversized hint rejection. It is not part of this output-contract patch.

## Exact file hashes

Root preimages, captured before edits:

- `src/local_ai_hub/operation_contracts.py`: `28DD0FF31AE5F4163BC439768F2C76B513ED3D2A1CF41AF432520D54A9AF7C83`
- `tests/test_operation_contracts.py`: `48BD4FBA25C7E4C0568D9762DCF067263349D5051E3BA6C9E13E690DB80BBB97`
- `tests/test_mcp_contract_dispatch.py`: `3A77B0D4690BCB2835EC8FCD88A129EDE4431E5D4B15400047399307557825CD`

Overlay postimages:

- `src/local_ai_hub/operation_contracts.py`: `780226137BEECA0F6CBB111EB2C478139659F59BFF01E0C3B0901AB28D3041CB`
- `tests/test_operation_contracts.py`: `0ACCD2729EF1CC46A7AF8FC31A76E106D5222596163D21B540A39C76DC3B51EE`
- `tests/test_mcp_contract_dispatch.py`: `370165C4B182B26450F7618836254C295F86E34D81DA1DE161B862A1B4CA6481`

Patch `T03-repo-search-output-contract.patch`: `9AECAF2A7EF64B7422E1A5E50F7BF388AAF9AB9C8663DFC74A9F3BC939D91472`

## Validation receipts

- Fail-first targeted contract tests: `3 failed, 55 deselected`; demonstrated malformed search-hit path accepted, missing output action catalog, and missing registered `brief` contract.
- Final contract/dispatch suite: `58 passed, 1 deselected in 2.63s`. Inventory test excluded for T20 ownership.
- Malformed repo-search dispatch regression: `1 passed, 7 deselected in 2.25s`.
- T14 MCP-to-HTTP joined harness: `2 passed in 9.82s`.
- `git apply --check` from root: passed; root target hashes remained equal to captured preimages.
- Root checkout has extensive pre-existing dirty paths. This task did not apply the patch or edit root files.

Exact final contract/dispatch command:

```powershell
python -B -c "import sys; sys.path.insert(0, r'.t03-root-overlay/src'); import local_ai_hub; import pytest; raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '-k', 'not surface_inventory_uses_generated_operation_contract_metadata', '.t03-root-overlay/tests/test_operation_contracts.py', '.t03-root-overlay/tests/test_mcp_contract_dispatch.py']))"
```

## Token measurement

Compact action deltas across all eight tools (upper bound with no feature filtering): baseline `3,283` O200k / `2,907` cl100k; updated `5,964` / `5,465`; delta `+2,681` / `+2,558`. `repo.search` delta alone: `186` / `169`. Full action schema map would cost `27,360` / `24,714`; full operation metadata `130,248` / `118,017`.
