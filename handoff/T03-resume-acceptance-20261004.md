# T03 resumed API/client/contracts acceptance — 2026-10-04

## Scope guard

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`, HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Root untouched.
- Candidate already dirty before this continuation. Existing modified/untracked source and tests remain preserved. This continuation edited only the new untracked `tests/test_t03_alias_contract.py` test assertion and added two handoff artifacts.
- User reassigned all search-specific `path_hints` MCP/client/HTTP/service symbols to T21. No such symbol edited by T03. T21 received the exact interface handoff and separately reports **120 passed in 17.46s** across its search-specific candidate suite; this is T21 evidence, not T03 acceptance.
- T14 `/api/context/pack`, T21 project-config/service adapter, and root files remain out of scope.

## T03 test packet

- Alias test patch: `handoff/T03-root-current-alias-contract-test-20261004.patch`, latest SHA-256 `DE4BDBE9D867025FB291C9F914CEF27A2206D95A3972D304AEAB2BDA3A0EBD74`.
- Target: new `tests/test_t03_alias_contract.py`; root preimage absent. Current candidate test SHA-256: `762001F41B6777D63EB4A35DC6DB532F9A546086F1BB9A9915DA048D42B75537`.
- Root `git apply --check` passed; patch not applied.
- Test correction: schema has a multi-action enum rule containing canonical `task_create`; it does not have a dedicated `const=task_create` rule. The test now verifies that alias `task_new` is included in that canonical enum, then verifies canonical validation and original-alias handler dispatch.

## Candidate validation receipt

T20 one-shot candidate run used `local_ai_command`, execution `3dd0926ea03a427fb5aee7d88480c6db`, repository revision `2cfe361897f53b93aa2f3ff002e32244d92fac9ba60ee4d2fd44e8237f2ac884`, candidate HEAD unchanged. Exact result: **28 passed, 2 failed in 9.03s**, exit 1. No retry.

Included selectors/modules:

- `tests/test_t03_http_json_contract.py`
- `tests/test_t03_alias_contract.py`
- Mutation route/journal registry, T07 recovery adapter and identity-bound journal selectors in `tests/test_operation_contracts.py`
- Typed `verify_receipt` schema selector
- Five duplicate/safe/unsafe POST replay selectors in `tests/test_client_transport.py`
- `tests/test_mcp_wire_contract.py`, `tests/test_mcp_stdio_contract.py`

Failures:

1. `tests/test_t03_alias_contract.py::test_mcp_action_alias_schema_and_dispatch_use_canonical_contract` — two one-shot attempts exposed test-only assumptions: first looked for a dedicated `const` schema branch instead of the canonical multi-action enum; second monkeypatched nonexistent `mcp_server.validate_operation_call`. Test now hooks the actual `validate_schema_object` boundary. Fresh T20 one-shot result: **1 passed in 2.18s**, execution `8c87569977ce4fae887d0f6c1de2720d`, exit 0, candidate HEAD unchanged. Post-test source hashes unchanged: `mcp_server.py` `24CB51FC19931D5E27508E48A3AAE59CDFA06914E7B8FD11A717C3A7EF8244E`; `operation_contracts.py` `20863DFEDE5AD7E5ABF25D356E2751650568E984E03DCD8A49EB8642122501F0`.
2. `tests/test_mcp_stdio_contract.py::test_stdio_handshake_publishes_all_registered_live_schemas` — expects generic output schema but candidate registration publishes a non-generic `local_ai_rag` output schema. Per user decision, defer per-action output schemas until complete contracts exist; exclude this selector from T03 acceptance and do not change its schema implementation here.

All pinned source/test file hashes were identical immediately before and after the test run. Production source was not edited. The selected JSON, recovery, typed receipt, client replay, and MCP wire selectors passed within the 28-pass result.

## Next authorized validation

Candidate focused API/client/contracts acceptance is complete for the included non-search selectors: the broad one-shot run had **28 passing tests**, and the corrected alias selector then passed separately (**1 passed**). Search-specific path-hints acceptance belongs to T21 and is separately reported there. Root acceptance remains open: root was not edited or tested; T20 must integrate owner-scoped patches and authorize root checks. The `local_ai_rag` generic-versus-action-output schema mismatch remains deferred and excluded.

Do not repeat the candidate selectors. Only run new root checks under a fresh exact T20 GO after integration.
