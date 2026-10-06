# T03 owner-only MCP contract/dispatch packet — 2026-10-04

Status: prepared and hash-pinned. Root was not modified.

## Packet

- Patch: `handoff/T03-root-current-path-hints-wrapper-test.patch`
- Patch SHA-256: `7D83E7FF93B4013B1B8C3C1BEB7B9D4AA5AA98582999E6EA73CAB387CA09CD66`
- Payload: one added test, `test_mcp_repo_search_forwards_path_hints_to_http_payload`, in `tests/test_mcp_contract_dispatch.py`. The exact function SHA-256 is `54712785CBB9DE9C10D59CFF9CAEB1D44815A0814636BFA043D58E9F00417DAC`; it matches the candidate function and packet hunk.
- No production-code hunk is needed: root `mcp_server.py` already normalizes and forwards MCP `path_hints`; root `operation_contracts.py` already validates bounded search hints. Root `test_operation_contracts.py` already covers those schemas. The T14-owned `context` hint contract stays intact.

## Ownership exclusions

- Excluded: HTTP `Handler.do_POST` route for `/api/search` (T06-owned), `services.repo_search` (T16-owned), T04 `client.py` transport, and T14 `/api/context/pack`.
- The test asserts the MCP client's existing `/api/search` request target. It does not modify or claim the HTTP route.
- No inherited dirty content, broad candidate file replacement, or other owner hunk is in the patch.

## Candidate and root snapshots

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`; HEAD `ad622f8a90a81e349e94d3402f297f2995e733b2`.

| File | Candidate HEAD preimage SHA-256 | Candidate worktree SHA-256 | Root current preimage SHA-256 | Packet expected root postimage SHA-256 |
| --- | --- | --- | --- | --- |
| `src/local_ai_hub/mcp_server.py` | `229B62A68305F3236BE4C4782FE17BE1EFE36F557E48B0FDFe1875A31F838848` | `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D` | `FDFDD51B35054A1C80A8B5DF0DD751D6745E0CF0C888AE6CF18A47D7B386EA73` | unchanged |
| `src/local_ai_hub/operation_contracts.py` | `D2120B614852DE7AB7006F65B8AE30D5B6EEE474EBCAD69CB2605D37EC119329` | `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF` | `1CB6942E888506897F4C994062654D08524D546CE93A12707EE1C08D99A783BB` | unchanged |
| `tests/test_mcp_contract_dispatch.py` | `1BBA650F154E835F961A7FA72494C0DB3C6A806D72F7DD8465F3E86D41606B81` | `CF06429D5C4B9A780B36026C3FD0FB133DF9F3A234518486B685E7C548467475` | `1608DCFB5A57B0A4F5AE8CDBB80B2576D0A54A7D2FFE84035989041A344343D0` | `84C67BD1791F201E692DD61F7C225A941B2EE886CFBAEA87A27770A5C342A285` |
| `tests/test_operation_contracts.py` | `6C388CED440D8EDA35DEE2C39762A1289412892C447EBF91BA08D3C0E8BC2BF5` | `2C5AD3398AF7630C06676C7C75745CC66FA8C9B500D6C917685F6F9F4939B320` | `6F15CBF4E045B6D5D6A316CD27636090661270142376AA13C97A8A85B24DD3F1` | unchanged |

Candidate whole-file hashes are provenance only; they include pre-existing shared hunks. The patch payload is only the single added dispatch test. Root `tests/test_mcp_contract_dispatch.py` is untracked, so its current working-tree hash is the preimage; no HEAD preimage exists for that root file.

## Applicability and acceptance

- Root HEAD at audit: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- `git apply --check --ignore-space-change <candidate patch>` from root: exit 0.
- Temporary-copy apply simulation: exit 0; dispatch-test preimage `1608DCFB5A57B0A4F5AE8CDBB80B2576D0A54A7D2FFE84035989041A344343D0`, postimage `84C67BD1791F201E692DD61F7C225A941B2EE886CFBAEA87A27770A5C342A285`. Temporary copy removed; root untouched.
- Candidate acceptance: 108 contract/dispatch/autostart/recovery/live-wire tests passed in 26.83s; 3 targeted client transport selectors passed in 1.35s. Full commands and receipts are in `handoff/T03-acceptance-current.md`.
- No root patch application or root test run. Live leases were not queried; ownership follows the assigned worktree and recorded owner matrix.
