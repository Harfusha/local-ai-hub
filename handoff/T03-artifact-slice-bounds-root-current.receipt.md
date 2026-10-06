# T03 artifact slice bounds — root-current handoff

Date: 2026-10-01 (Europe/Prague)
Assigned worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
Assigned HEAD at entry: `ad622f8a90a81e349e94d3402f297f2995e733b2`; 30 dirty paths were present before this continuation.
Root target: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Scope

Patch changes only `operation_contracts.py` and its contract/dispatch tests. `local_ai_artifact.get` and `.slice` now publish and enforce `offset >= 0` and `512 <= max_chars <= 12000`, matching MCP dispatch bounds. Dispatch tests assert invalid values return status 400 before calling the registered tool. `mcp_server.py`, `/api/context/pack`, and other T03 work are excluded. Root was not edited.

## Root-current preimages and overlay postimages

| Path | Root-current preimage SHA-256 | Isolated overlay postimage SHA-256 |
| --- | --- | --- |
| `src/local_ai_hub/operation_contracts.py` | `28DD0FF31AE5F4163BC439768F2C76B513ED3D2A1CF41AF432520D54A9AF7C83` | `EA9250A37DC21286B6D194CB3AC3B96BC62356ECDE5C8094D3A4EEE7F1B4F330` |
| `tests/test_operation_contracts.py` | `48BD4FBA25C7E4C0568D9762DCF067263349D5051E3BA6C9E13E690DB80BBB97` | `B0D2CCE62F5F3FB0BABB145A8933E8254236D3D61DB31ABE57008FBFCEA28AAF` |
| `tests/test_mcp_contract_dispatch.py` | `3A77B0D4690BCB2835EC8FCD88A129EDE4431E5D4B15400047399307557825CD` | `D8DEEBDE26C4D751769134992BD5F65A10ED9684EFAA7F44370DA9787266126F` |

Patch: `T03-artifact-slice-bounds-root-current.patch`  
Patch SHA-256: `D863C42786034A75EB4FBB0C2B7740F79931DF2FB87098E69E2669537DCB7CAB`  
Patch stat: 3 files, 57 insertions, 2 deletions. No MCP entrypoint hunk.

## Validation

Fail-first on root-current preimage overlay with the two selectors below: **5 failed in 2.54s** (missing numeric schema bounds; dispatch did not reject the invalid calls as 400 before side effect).

```text
 tests/test_operation_contracts.py::test_artifact_slice_numeric_bounds_are_published_and_enforced
 tests/test_mcp_contract_dispatch.py::test_mcp_dispatch_rejects_out_of_range_artifact_slice_before_tool_call
```

Green on patched root-current overlay: **5 passed in 2.37s**.

```text
python -B -c "import pytest; raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--confcutdir=C:/Users/Adam/.codex/worktrees/t03-contracts-resume/.local-ai-hub/.t03-root-current-overlay/candidate',r'C:/Users/Adam/.codex/worktrees/t03-contracts-resume/.local-ai-hub/.t03-root-current-overlay/candidate/tests/test_operation_contracts.py::test_artifact_slice_numeric_bounds_are_published_and_enforced',r'C:/Users/Adam/.codex/worktrees/t03-contracts-resume/.local-ai-hub/.t03-root-current-overlay/candidate/tests/test_mcp_contract_dispatch.py::test_mcp_dispatch_rejects_out_of_range_artifact_slice_before_tool_call']))"
```

Root applicability:

```text
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-artifact-slice-bounds-root-current.patch
PASS
```

Root target hashes remained equal to the preimages after `git apply --check`. The root already had its own dirty MCP entrypoint and untracked contract files; these were preserved.

## Remaining T03 work

Cold-start stdio runtime proof, concurrent start/timeout/cancellation cleanup audit, FastMCP-absent fallback, exhaustive action parity, and broader end-to-end acceptance remain pending. A separate live-wire test edit in the assigned worktree is not included in this bounded root patch.
