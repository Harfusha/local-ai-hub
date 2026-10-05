# T03 root-current action contract handoff

Date: 2026-10-03
Root: `C:\Users\Adam\.local-ai-hub`
Candidate: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Root files were not edited.

## Scope and ownership

- T04 confirmed it owns `client.py` transport and does not own `operation_contracts.py` or MCP registration.
- T13 confirmed its operational-mode gate hunk is in a separate region and has no planned changes to schema registration or compact dispatch. Preserve the dirty gate code.
- T03 owns the MCP alias schema/dispatch hunk, typed action output contract, and these tests. `/api/context/pack`, `client.py`, and `async_jobs.py` core remain outside scope.
- The public MCP output schema remains the shared open envelope pending complete action contracts.

## Root-current patches

`handoff/T03-root-current-alias-dispatch-20261003.patch`

- SHA-256: `3661535DFCBAC27C93C82829F0E28EEFF83E89CCB2F69246D2038D1FB13DDCE9`
- Files: `src/local_ai_hub/mcp_server.py`, `tests/test_mcp_contract_dispatch.py`
- Full root preimage SHA-256:
  - `mcp_server.py`: `C61467CF7B8E3DFF4E105EE39B22742D488BC78791FFD05DBDAE5AB53B27E0ED`
  - `test_mcp_contract_dispatch.py`: `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`
- Adds aliases to FastMCP Literal and JSON input schemas, mirrors canonical conditional requirements, validates a canonicalized copy while dispatching the original alias, and validates output against the canonical action. Regression covers advertised/runtime `task_new`, matched `task_create` constraints, and canonical input/output validation.
- `git apply --check --whitespace=error` fails on CRLF context in `test_mcp_contract_dispatch.py`. `git apply --check --ignore-space-change --ignore-whitespace --whitespace=nowarn` passes against current root. No patch was applied.

`handoff/T03-repo-search-output-contract.patch`

- SHA-256: `9AECAF2A7EF64B7422E1A5E50F7BF388AAF9AB9C8663DFC74A9F3BC939D91472`
- Files: `src/local_ai_hub/operation_contracts.py`, `tests/test_operation_contracts.py`, `tests/test_mcp_contract_dispatch.py`
- Current root full-file SHA-256 at recheck:
  - `operation_contracts.py`: `1CB6942E888506897F4C994062654D08524D546CE93A12707EE1C08D99A783BB`
  - `test_operation_contracts.py`: `6F15CBF4E045B6D5D6A316CD27636090661270142376AA13C97A8A85B24DD3F1`
  - `test_mcp_contract_dispatch.py`: `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`
- Strict `git apply --check --whitespace=error` passes against current root. No patch was applied.
- Prior isolated overlay receipt reports `58 passed, 1 deselected in 2.63s`, malformed `repo.search` dispatch `1 passed`, and T14 joined harness `2 passed`. These validate only the output-contract patch, not the alias-dispatch patch. See `T03-repo-search-output-contract.receipt.md`.

## Combined apply check

Copied the four root preimages into `.t03-root-overlay/combined-v2`, then applied the output-contract patch followed by the alias-dispatch patch there. Sequential overlay application passed. This proves the hunks compose against the captured root snapshot; it did not modify the root checkout.

Alias-dispatch tests are **UNVERIFIED**. No tests or builds were run in this continuation; the exclusive root validation slot remains with the orchestrator.
