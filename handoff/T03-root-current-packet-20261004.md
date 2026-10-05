# T03 root-current patch packet — 2026-10-04

## Scope and ownership

- Candidate: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`, HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`.
- Integration root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root remained read-only. Candidate and root contain extensive unrelated dirty changes; no broad file replacement, staging, or commit.
- T03-owned patch hunks: MCP alias schema/dispatch, focused alias contract coverage, and HTTP JSON parser contract tests.
- `path_hints` input contract and MCP normalization/root confinement are already present in root (`operation_contracts.py` and `mcp_server.py`). User approved the public `local_ai_repo(action="search").path_hints` contract and T21 notification; prior handoff records that T21 was notified. No new implementation patch is needed for this contract in the current root.
- Excluded: `/api/search` HTTP handler (T06-owned), T18 matcher, `/api/context/pack`, output schema expansion (user deferred pending complete action contracts), client transport (T04), service adapter (T21), and all inherited hunks.

## Included standalone root-current patches

Hashes below are SHA-256. Root preimages were hashed from the live integration root. Postimages were produced by applying the patches in order to an isolated temporary Git repository seeded with the relevant root preimage files. Root `git apply --ignore-space-change --check` passed individually for each patch; no root patch was applied.

| Patch | SHA-256 | Target | Root preimage SHA-256 | Simulated postimage SHA-256 |
|---|---|---|---|---|
| `handoff/T03-root-current-alias-source-20261004.patch` | `0380A4F6C8E472EF1FD8ADFC93F78595C734EE383CEAE2616D386EB94FEF2284` | `src/local_ai_hub/mcp_server.py` | `FDFDD51B35054A1C80A8B5DF0DD751D6745E0CF0C888AE6CF18A47D7B386EA73` | `60389E604E6BE351EB36221B8520AFB575F9C63FF8F7CE90C41C119FCE0E5A40` |
| `handoff/T03-root-current-alias-tests-20261004.patch` | `78A26890AB0FA68133A1C8B85AFCCAB73E791A9B47BA2182709508A56C35504D` | `tests/test_mcp_contract_dispatch.py` | `1608DCFB5A57B0A4F5AE8CDBB80B2576D0A54A7D2FFE84035989041A344343D0` | `14F76CD1C34E51A0F119AF1B0DE3C4981B58D2321EA3611B9631DB1185EAE26F` |
| `handoff/T03-root-current-json-parser-test-20261004.patch` | `8D12937147951EB6C77578D76E88CF0A1C39BB3561E932C0C077A9BED35D4D96` | `tests/test_t03_http_json_contract.py` (new) | absent | `F5A42222F9597376723456C4CC86B78162D601C536E578F9AD0BA4DEA7E82D27` |
| `handoff/test_t03_alias_contract-root-current-20261004.patch` | `6E6F204718468B20A9ABC2DC35217FD90FF18D164B9E33BFA88CA115D8168172` | `tests/test_t03_alias_contract.py` (new) | absent | `5197DBB787AB2E511833681FFFAD91DAFC4FC540F34ABF933B536ECB3E3919A3` |

Candidate working-tree hashes for the two new test files are respectively `87599DECDD061C4482BC97323F809EB50C9E80212C48B2625B5AF04EC36AF02B` and `01969762D0155351957A0C38FF4DAF2F978F38CE7CE568E8D323C2553592D31D`. Root postimage hashes are intentionally reported separately because the patch bytes and candidate working copy may use different line endings.

## Receipts and acceptance blockers

- Candidate contract/dispatch/journal/wire selection: **108 passed in 26.83s** (historical candidate receipt; not a root result).
- Candidate explicit safe-POST transport selection: **3 passed in 1.35s** (historical candidate receipt; not a root result).
- A later T20-gated run reported **22 passed, 1 failed in 2.58s**; the failure was the earlier alias selector calling nonexistent `_mcp_input_schema`. The selector was corrected to `_mcp_contract_schema`; corrected selector is **not run**.
- Candidate focused JSON/alias contract tests were not rerun after their latest edits. No root tests were run.
- T20's overall release GO remains closed/unknown; its latest T07 acceptance attempt reported exit 1 (41 passed, 14 failed). This blocks a fresh serialized T03 test slot and root acceptance.
- T04 client/API path-hints acceptance and T21 service/retrieval acceptance remain external dependencies. T21 notification is recorded above; no T21 service code is in this packet.
- The existing `.t03-root-overlay/handoff/T03-repo-search-output-contract.patch` (SHA-256 `9AECAF2A7EF64B7422E1A5E50F7BF388AAF9AB9C8663DFC74A9F3BC939D91472`) is deliberately excluded under the user's decision to defer output schemas until complete action contracts exist.
- No `/api/search` handler, T18 matcher, `/api/context/pack`, T04 client, or T21 adapter hunk is included.
