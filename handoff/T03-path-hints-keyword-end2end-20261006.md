# T03 path_hints keyword-seam packet — 2026-10-06

## Scope and ancestry

- T03 worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
- T03 base HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2` (parent `a07c41fba00e35d13a8e9d8de26720b4b6f0b45b`)
- Root HEAD: `744727887bb1027b1bc464534a1ab0280ddbc9fe`
- Merge-base: `2b33602adef0d030fea66cdcc04ca742c60b2e32`; histories diverge, neither HEAD is ancestor of the other.
- T03 task-preimage source/test patch: [T03-path-hints-keyword-source-test-20261006.patch](T03-path-hints-keyword-source-test-20261006.patch), SHA-256 `afe3b258fab2660e4bf016bd5df7ecf3c48c5a3b12ae81d71983b17ca2d8c28e`. Reconstructed preimages match recorded task-start Git blobs.
- Root test-only add patch: [T03-root-current-path-hints-client-keyword-postfix-20261006.patch](T03-root-current-path-hints-client-keyword-postfix-20261006.patch), SHA-256 `65D734A9830E1FD5AF1ACE5A10A62594797161037E071ACC2244FCDD09ADABF4`.
- Added test function SHA-256: `816f67a1f8b3d5f68b70b3829bfcbc2154736db914edd8230667e16cc2c0a06a`

## T03 source/test delta

Only T03-owned `src/local_ai_hub/mcp_server.py` and `tests/test_mcp_contract_dispatch.py` changed in this continuation. Whole-file hashes include prior dirty candidate hunks; transfer must stay hunk-scoped.

| T03 file | Base HEAD blob | Task preimage blob | Post blob |
| --- | --- | --- | --- |
| `src/local_ai_hub/mcp_server.py` | `6b4317b3457bfcf5995da1758a3ae229d4a00ba8` | `6b521650683424f3a918219d9c8b3e88d017c3ca` | `f3d11bee4d7ae8bd63f46bc7ea23f8d5b1043645` |
| `tests/test_mcp_contract_dispatch.py` | `6367c3d59f95f5f846a893dd86d816b216f530b1` | `0f9b39fce74283ea2e4ec8f779ff380fb676da74` | `5e4dd18c615203d7dbd63f5f6e6f6f977d9f9926` |

`operation_contracts.py` was not changed in this continuation; its existing candidate schema permits optional `path_hints` for search with a 64-item limit. Its HEAD/worktree blobs are `2ef2b0a3e574e3f88d040cb332059e4deccfa933` / `bbee5bf01ffb17a4a5506574237c7e3ad75935f9`.

Source change: MCP previously inserted `path_hints` inside the `/api/search` payload. It now builds normalized hints from `path` (`repository_search` / `repo_search`), appends at most 64 supplied hints, removes them from payload, and passes `path_hints=search_path_hints or None` to `CLIENT.post`. The test captures that keyword and the ordinary payload separately; it does not assert HTTP serialization.

The current root source already uses this keyword seam and root `HubClient.post` accepts the keyword. Root integration patch therefore adds only the test function. Root test-file fingerprints:

| State | Git blob SHA-1 | SHA-256 |
| --- | --- | --- |
| Root committed base | `64c8c11a93fec6bf487b7613342e17696f4a5ca4` | `e5c0b92ea2e79a9c5551dd4af9a5ecaf50565cbf1d2c59e2fbd2d2e2dd800dd6` |
| Root current preimage | `e53cf0f9c1a8810338b21fbe58b720849b7d2dea` | `1fc41dd2d2a947ac61e1786e1503c7354c293655ebc0b31bfa73a8dd849508b2` |
| Expected root postimage | `06662c9340d7d1c19582369b37b1bf27b328401d` | `ff84e19726dc633db0aeebaf696d155884139cd2d9bb15833487b433dcaddbbf` |

Expected postimage preserves root's inherited `_ACCOUNTING_REPORTER.record` → `_send` hunk and trailing blank line. Hash computed in memory; no root write.

## T04 boundary

No `client.py` edits. T03 candidate `client.py` is still the pre-keyword contract, while current root source has the T04 keyword API. T04 replied that its assigned checkout has no source and no retained selector/log proving `HubClient.post(..., path_hints=...)` → HTTP payload. Its reported transport receipts do not map to a path_hints selector. Therefore the verified hop ends at MCP `CLIENT.post` keyword; keyword-to-HTTP serialization remains unverified. T03 is not marked done.

## Validation

T03 exact selector, after source/test edit:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py::test_mcp_repo_search_passes_path_hints_to_client_keyword
1 passed in 5.75s; exit 0
request_id=req_8cc9623262d8
execution_id=bdd4446579bd4a54bafabc8441a4ffd9
```

Root applicability check, no application:

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-root-current-path-hints-client-keyword-postfix-20261006.patch
```

Result: exit 0. Root status unchanged. No broad tests ran. Indexed `review_diff` did not complete: it included inherited files despite `changed_paths` and declined the 69-segment diff; no review result claimed.
