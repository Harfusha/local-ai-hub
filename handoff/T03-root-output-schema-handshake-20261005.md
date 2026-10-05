# T03 root-current MCP output-schema packet — 2026-10-05

- Root: `C:\Users\Adam\.local-ai-hub`
- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Owner checkout: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
- Root remains unmodified. Patch generated from verified live root preimages; no e809 source patch copied.
- Scope: preserve common MCP output envelope; expose available action-specific output deltas via `x-action-output-contracts`; add RAG search fields grounded in `RAGStore._search_uncached` (`workspace`, `results`, path/chunk/text/content_hash/score, fallback diagnostics). Extend existing root `tests/test_operation_contracts.py` to assert registered and live `tools/list.outputSchema`.
- T21-owned adapter and T14 `/api/context/pack` untouched.

| Root path | Preimage SHA-256 | Proposed postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/operation_contracts.py` | `1cb6942e888506897f4c994062654d08524d546ce93a12707ee1c08d99a783bb` | `79abad111dddbca541d0e8e7a439742f54ba431fac51918a704fccb7fbe06930` |
| `tests/test_operation_contracts.py` | `6f15cbf4e045b6d5d6a316cd27636090661270142376aa13c97a8a85b24dd3f1` | `7a22137b1d17c52163f938ae206264d0a788f1481b460b4cab9ef073c8477c88` |

Patch: `handoff/T03-root-output-schema-handshake-20261005.patch`

Patch SHA-256: `d2dd9e9277b7b6a697a169edd92b80d7af2fcb6847cb9e855d9be11b43437703`

`git apply --check`: exit `0`.

## Test evidence

Candidate-only (e809) exact selectors, against e809 code, not root:
`tests/test_mcp_stdio_contract.py::test_stdio_handshake_publishes_all_registered_live_schemas`
`tests/test_mcp_output_contracts.py::test_live_mcp_outputs_match_generated_http_facing_contracts`
`tests/test_operation_contracts.py::test_status_output_schema_publishes_shared_error_envelope`
Result: `3 passed in 4.15s`.

Root tests for this packet: **not run**. Root was kept read-only; patch was not applied. Candidate receipts do not establish root test results.
