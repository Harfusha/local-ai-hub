# T03 root-current contract patch receipt — 2026-10-03

Root: `C:\Users\Adam\.local-ai-hub`  
Candidate: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`  
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`

Root was read-only throughout. Both patches below are T03-owned overlays; neither was applied to the root checkout.

## Exact patches and preimages

### Alias schema and dispatch

Patch: `handoff/T03-root-current-alias-dispatch-20261003.patch`  
SHA-256: `3661535DFCBAC27C93C82829F0E28EEFF83E89CCB2F69246D2038D1FB13DDCE9`

Files/hunks:

- `src/local_ai_hub/mcp_server.py`: alias-aware FastMCP Literal/input schema, canonical validator copy, original alias dispatch, canonical output validation.
- `tests/test_mcp_contract_dispatch.py`: alias schema/dispatch and canonical validation regression.

Root preimage SHA-256:

- `src/local_ai_hub/mcp_server.py`: `C61467CF7B8E3DFF4E105EE39B22742D488BC78791FFD05DBDAE5AB53B27E0ED`
- `tests/test_mcp_contract_dispatch.py`: `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`

### Search/output contracts

Patch: `.t03-root-overlay/handoff/T03-repo-search-output-contract.patch`  
SHA-256: `9AECAF2A7EF64B7422E1A5E50F7BF388AAF9AB9C8663DFC74A9F3BC939D91472`

Files/hunks:

- `src/local_ai_hub/operation_contracts.py`: compact action-output catalog and typed `repo.search` hit contract; preserves the common output envelope as open. The `path_hints` input contract is already in the captured root preimage.
- `tests/test_operation_contracts.py`: schema and validator regressions.
- `tests/test_mcp_contract_dispatch.py`: malformed search output/dispatch regression.

Root preimage SHA-256:

- `src/local_ai_hub/operation_contracts.py`: `1CB6942E888506897F4C994062654D08524D546CE93A12707EE1C08D99A783BB`
- `tests/test_operation_contracts.py`: `6F15CBF4E045B6D5D6A316CD27636090661270142376AA13C97A8A85B24DD3F1`
- `tests/test_mcp_contract_dispatch.py`: `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`

## Apply/diff checks

Read-only checks against the root at the HEAD above:

- Alias patch: `git apply --check --ignore-space-change --ignore-whitespace --whitespace=nowarn ...` → exit 0. Strict whitespace mode reports CRLF context in the dispatch-test hunk.
- Search/output patch: `git apply --check --whitespace=error ...` → exit 0.
- The two patches were applied in sequence to disposable copies of the four root preimages in `.t03-root-overlay/combined-v2`; composition passed. This did not write to root.
- Root status remained limited to pre-existing T03/T13 files: `mcp_server.py` modified; `operation_contracts.py`, `test_mcp_contract_dispatch.py`, and `test_operation_contracts.py` untracked. No status change was made by the checks.
- Orchestrator reports candidate scoped HTTP/MCP payload tests **3/3 passed**. No root integration test ran in this continuation; current root acceptance is still pending.

## T08/T13 dependency map

| Owner | Contract dependency | Integration boundary |
|---|---|---|
| T08 Agent OS | Keep `session_id` distinct from tenant scope; preserve the canonical context-element identity fields and stable ETag behavior. Keep T08-owned result payloads general until every action has a source-backed output contract. | T08 owns `agent_context.py`, its tests and benchmark. No T03 patch hunk overlaps those files. T03 does not assign a stricter FastMCP output schema to the incomplete Agent OS actions. |
| T13 operational gate | Gate identity is `(tool_name, selector_field, canonical_action)`; aliases normalize to the same canonical authorization contract. | T13 gate wrapper in `mcp_server.py` near `_registered_tool` (about line 1168) is separate from T03 schema/dispatch hunks. Preserve it. T03 validates canonical input/output while sending the original alias to dispatch; do not add alias-specific gate policy. |

T13 previously confirmed it had no planned changes to the schema-registration or compact-dispatch hunks. T08's current continuation reports no root edit. Recheck exact root preimages before applying if either owner changes those files.

## Status

**PATCH READY FOR INTEGRATION REVIEW; ROOT NOT MODIFIED.** Candidate test result is reported above; root receipt-gated acceptance is incomplete. Keep `/api/context/pack` and `client.py` outside these patches.
