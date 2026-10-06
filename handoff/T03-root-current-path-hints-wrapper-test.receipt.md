# T03 root-current path_hints wrapper test receipt

Date: 2026-10-03
Owner: T03 candidate worktree `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
Root integration: not performed; root stayed read-only.

## Contract state

- User approved optional `path_hints` for `local_ai_repo(action="search")` and notification to T21.
- T21 confirms root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; root-current `src/local_ai_hub/mcp_server.py` already contains path-hint normalization and `/api/search` forwarding (SHA-256 `C61467CF7B8E3DFF4E105EE39B22742D488BC78791FFD05DBDAE5AB53B27E0ED`).
- Root-current untracked `src/local_ai_hub/operation_contracts.py` already permits bounded `path_hints` for `search` and `context`, validates nested fields, SHA-256 `1CB6942E888506897F4C994062654D08524D546CE93A12707EE1C08D99A783BB`.
- Root-current untracked `tests/test_operation_contracts.py` already tests bounded/search schema, SHA-256 `6F15CBF4E045B6D5D6A316CD27636090661270142376AA13C97A8A85B24DD3F1`. The inherited `context` path_hints branch/test is T14-owned; patch leaves it unchanged.
- Root-current untracked `tests/test_mcp_contract_dispatch.py` has no wrapper-forwarding test, SHA-256 `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`; T21 reports CRLF and EOF newline. A bounded native line-count fallback returned 329 lines.

## Patch

`T03-root-current-path-hints-wrapper-test.patch` adds only the already-tested T03 selector at root test-file EOF. Hunk uses current working-tree line 329; target file is untracked, so there is no HEAD preimage. Patch was not applied and applicability was not checked. Root files remain untouched.

## Candidate proof

Existing T03 candidate focused receipt: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py` — 108 passed, 23.62s, exit 0; command execution `44eafbbf81c64b8282eca2f295e01d44`, revision `345065f0e66fdc0e096a37ed875406ef6a889f1bd7d7f8de151f7b36fdcfb82b`.

Candidate hashes: `mcp_server.py` `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`; `operation_contracts.py` `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF`; `test_mcp_contract_dispatch.py` `CF06429D5C4B9A780B36026C3FD0FB133DF9F3A234518486B685E7C548467475`; `test_operation_contracts.py` `2C5AD3398AF7630C06676C7C75745CC66FA8C9B500D6C917685F6F9F4939B320`.

## Coordination

T21 was notified with user approval that T03 owns the contract/adapter/test selector and that its existing `/api/search` hunk must not be duplicated. No tests were run after the candidate receipt; patch/receipt are handoff-only files.