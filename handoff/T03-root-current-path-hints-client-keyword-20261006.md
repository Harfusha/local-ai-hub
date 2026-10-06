# T03 path_hints client-keyword test packet — 2026-10-06

## Payload and target

- Target root: `C:\Users\Adam\.local-ai-hub`
- Root base HEAD: `744727887bb1027b1bc464534a1ab0280ddbc9fe`
- Candidate T03 HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`
- Patch: [T03-root-current-path-hints-client-keyword-20261006.patch](T03-root-current-path-hints-client-keyword-20261006.patch)
- Patch SHA-256: `4E6EDE9B5B710305FD928ACFA9C9DB7525CE58F4AD7A568D4A389F5145182392`
- Only payload: one added T03-owned test function, `test_mcp_repo_search_passes_path_hints_to_client_keyword`.
- Function SHA-256 (UTF-8, LF-normalized function body plus final LF): `86092c6b7c60ac96271d20715a9d9dc75faf2b2bbbb96072b01e0301892b577e`
- Mock accepts `path_hints` as a keyword and asserts that exact argument at `CLIENT.post`; it asserts ordinary root/query/top_k/enrich payload separately. It does not claim HTTP serialization is tested.

## Root file fingerprints

| `tests/test_mcp_contract_dispatch.py` | Git blob SHA-1 | SHA-256 |
| --- | --- | --- |
| Committed base at root HEAD | `64c8c11a93fec6bf487b7613342e17696f4a5ca4` | `e5c0b92ea2e79a9c5551dd4af9a5ecaf50565cbf1d2c59e2fbd2d2e2dd800dd6` |
| Current root worktree preimage | `e53cf0f9c1a8810338b21fbe58b720849b7d2dea` | `1fc41dd2d2a947ac61e1786e1503c7354c293655ebc0b31bfa73a8dd849508b2` |
| Expected postimage, patch added in memory | `1baa6ec251099dde4eba422dfcafdba665bdeb95` | `8fa10f6e4f9ab4e97954dc804e42c7b122803648fd964c60e900e083e52b9941` |

Current root preimage preserves its existing dirty accounting hunk (`record` → `_send`) and trailing blank line. Expected postimage is current raw bytes plus only the patch's 33 LF-terminated added lines; no root file was written.

## Source contract and owner boundary

At root HEAD, `operation_contracts.py` already declares bounded search `path_hints` (maximum 64, required `path`/`purpose`/`scope`, closed item schema). Root `mcp_server.py` passes normalized hints as `path_hints=...` keyword to `CLIENT.post("/api/search", ...)`. Root `client.py` accepts that keyword and moves it into `clean_payload`.

No T04-owned HTTP serialization code is included or claimed. No T04 receipt exists in this T03 worktree, so the client-to-HTTP serialization hop remains unverified here. No production file is included.

The prior [T03 owner receipt](T03-owner-only-mcp-contract-dispatch-20261004.md) (SHA-256 `6F19771ACCB1DBCCC195DCC73E21487543AD74B3CB6F02096AAFA627522E6382`, lines 7–16) proves the T03-owned test-only boundary. It explicitly excludes production-code hunks.

## Applicability and validation

Applicability check against current root worktree, no application:

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-root-current-path-hints-client-keyword-20261006.patch
```

Result: exit 0. Root test target remains unchanged.

Exact selector run in T03 candidate after test edit:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py::test_mcp_repo_search_passes_path_hints_to_client_keyword
1 failed in 1.81s; exit 1
request_id=req_d159ae7cec30
```

Failure: candidate T03 `mcp_server.py` puts `path_hints` inside payload; captured keyword is `None`. Root HEAD uses the keyword seam. This candidate/root source mismatch is recorded, not repaired. The old payload-asserting packet targets a stale root snapshot and is superseded by this packet. No root patch application, root test run, or source edit occurred.
