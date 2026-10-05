# T03 root-current contract overlay receipt

Patch: `T03-root-current-contract.patch`
SHA-256: `CD7D46FF2C18C02DE41F2690D8861F1E182BA0D6727A86A2400C450B7256D64B`

## Preimages

- `src/local_ai_hub/operation_contracts.py`: `F51F8E395A2072B2534E4CE9F7D1A8285303B44FDF5737F49AD295A744D9B572`
- `tests/test_operation_contracts.py`: `D873FBD91CA805DE67EC62215BAC9A70834092644D2BE45853A92CE36D4B08E6`
- `tests/test_mcp_contract_dispatch.py`: `0CFE358C21C9121813461EB499EBED38D982D80130519AA1A7F2941B1D1159AF`

## Postimages

- `src/local_ai_hub/operation_contracts.py`: `28DD0FF31AE5F4163BC439768F2C76B513ED3D2A1CF41AF432520D54A9AF7C83`
- `tests/test_operation_contracts.py`: `48BD4FBA25C7E4C0568D9762DCF067263349D5051E3BA6C9E13E690DB80BBB97`
- `tests/test_mcp_contract_dispatch.py`: `3A77B0D4690BCB2835EC8FCD88A129EDE4431E5D4B15400047399307557825CD`

## Validation

Working directory: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`

Command:
`python -c "import sys; sys.path.insert(0, r'.t03-root-overlay/src'); import local_ai_hub; import pytest; raise SystemExit(pytest.main(['-q', '-k', 'not surface_inventory_uses_generated_operation_contract_metadata', '.t03-root-overlay/tests/test_operation_contracts.py', '.t03-root-overlay/tests/test_mcp_contract_dispatch.py']))"`

Result: `54 passed, 1 deselected in 3.79s`. The deselected inventory test requires an entire source tree absent from this bounded overlay.

Joined T14 MCP-to-HTTP test used the immutable T14 source overlay and the patched T03 operation contract:
`python -c "import sys; sys.path.insert(0, r'C:\Users\Adam\.codex\worktrees\0c2e\.local-ai-hub\handoff\root-current-overlay-v2\src'); sys.path.insert(0, r'.t03-root-overlay/src'); import local_ai_hub; import pytest; raise SystemExit(pytest.main(['-q', '.t03-root-overlay/tests/test_t03_context_http_join.py']))"`

Result: `2 passed in 10.48s`.

Patch applicability check, from `C:\Users\Adam\.local-ai-hub`:
`git apply --check 'C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub\.t03-root-overlay\handoff\T03-root-current-contract.patch'`

Result: `PASS`. This was a check only; the root checkout was not modified.

## Bugbot review

Review found no remaining schema/runtime bypass or adaptive-default mismatch. It reported a P1 because the patch does not apply to the active e809 checkout, whose test layout differs. The artifact targets the pinned root preimages listed above, not e809's source tree; the explicit `git apply --check` against `C:\Users\Adam\.local-ai-hub` passed. No code change needed for that target mismatch.
