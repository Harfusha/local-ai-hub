# T03 operational-mode classifier handoff

Date: 2026-10-02
Worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`

## Scope

The candidate classifies `local_ai_command(action="run")` as heavy before dispatch. `local_ai_repo(action="map")` remains a lightweight read. No root file or `/api/context/pack` route was edited. T13's test file was not copied.

The T03 action registry does not contain `files` or `symbols`; `_local_ai_repo_impl` returns `_invalid_action` for `local_ai_repo(action="files")` with `success: false` and an error naming the supported actions. The candidate test therefore uses registered read action `map`.

## Root-current patch

Patch: `handoff/T03-operational-mode-classifier-root-current-20261002.patch`
Patch SHA-256: `2F0197AE42D0E0A1C6E54C601FAD3497564C48394395D3C9AA807FCE85560ECC`

Pinned root preimage SHA-256:

- `src/local_ai_hub/mcp_server.py`: `5FF372AF25D78EDBB09B7F6D3AB6ECF5F8C9C593247F38A7B01C2CFF8E7929CE`
- `tests/test_mcp_contract_dispatch.py`: `D8DEEBDE26C4D751769134992BD5F65A10ED9684EFAA7F44370DA9787266126F`

Patch changes only those two paths. Root source already classifies arbitrary command actions as heavy; patch aligns its lightweight action names with the supported T03 repo registry and adds root-compatible regression coverage.

## Candidate changes and validation

- `src/local_ai_hub/mcp_server.py`: candidate SHA-256 `B83ADBDFEF3C77070FD8611DCF9AD2F400419BE3E070A4EE298177E855EEA4D8`
- `tests/test_mcp_contract_dispatch.py`: candidate SHA-256 `1DC7B8F7677BC207E35189B28111140F7CF139CBB45428D7094B24D121291AF0`
- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py::test_instrumented_tools_classify_heavy_command_and_lightweight_repo_reads`
- Result: `1 passed in 2.52s`
- T13's reported RED: `tests/test_t13_mcp_command_mode_policy.py::test_mcp_command_run_classifies_test_execution_as_heavy` failed because the wrapper supplied `requires_heavy_work=False`; command broker and subprocess did not run.
- Prior candidate probe of `repo(files)` returned `success: false`; static source shows the action is absent from `_REPO_ACTIONS` and falls through to `_invalid_action`.

T20 owns root integration and any root-level validation.
