# T03 path_hints test-only transfer packet — 2026-10-06

## Transfer boundary

- Target root: `C:\Users\Adam\.local-ai-hub`
- Target base HEAD: `744727887bb1027b1bc464534a1ab0280ddbc9fe`
- Candidate base HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`
- Candidate/root merge-base: `2b33602adef0d030fea66cdcc04ca742c60b2e32`; histories diverge. Neither HEAD is ancestor of the other.
- Packet: [T03-root-current-path-hints-wrapper-test-20261006.patch](T03-root-current-path-hints-wrapper-test-20261006.patch)
- Patch SHA-256: `022978323BAB2A69610E9EF16784A91A0AC8864C9BC7D3D40AB0768D397AAC7E`
- Payload: one added T03-owned function only, `test_mcp_repo_search_forwards_path_hints_to_http_payload`.
- Function SHA-256 (UTF-8, LF-normalized function body plus final LF): `6a8329626d0fe5dcc63a438427d038474efa60ce4d9f18a2a56356b01feb5638`

The function comes from the prior immutable owner patch (`T03-root-current-path-hints-wrapper-test.patch`, SHA-256 `7D83E7FF93B4013B1B8C3C1BEB7B9D4AA5AA98582999E6EA73CAB387CA09CD66`). Its assertion now filters the intentional `/api/telemetry/tool-accounting` request while still requiring exactly one `/api/search` request and the full payload. Separate T03 telemetry test owns telemetry assertions.

## Root base and postimage

| Target file | Git blob SHA-1 | SHA-256 |
| --- | --- | --- |
| Committed base at root HEAD | `64c8c11a93fec6bf487b7613342e17696f4a5ca4` | `e5c0b92ea2e79a9c5551dd4af9a5ecaf50565cbf1d2c59e2fbd2d2e2dd800dd6` |
| Current root worktree preimage | `fd8eec2d2af9b9409a6d5e0b8222d0b80f6bff93` | `0070fa81c1d83e4bf55614020d3b8b3db984ed48d85e22e4af1f89a7bd6fe1bc` |
| Expected postimage after add-only hunk | `804f2e6072a1fbf833453fb606ec52981decff72` | `b92d56abd612410a654be34373bdebace45aad9805a52d2324535665f590cd39` |

Current worktree differs from committed base by one inherited hunk at lines 193–195: `_ACCOUNTING_REPORTER.record` becomes `_ACCOUNTING_REPORTER._send`. Packet leaves it unchanged. Expected postimage hashes were computed in memory as current raw file bytes plus the patch's added LF-terminated lines; no root file was written.

## Root source contract check

At the exact target HEAD, tracked source already contains both MCP route and schema:

- `src/local_ai_hub/operation_contracts.py:236`: optional `path_hints`, maximum 64, required `path`, `purpose`, `scope`, and `additionalProperties: false`.
- `src/local_ai_hub/mcp_server.py:245-293`: bounded path-hint normalization; `:2146-2155` forwards normalized hints through the `/api/search` dispatch.

No production-source patch is included. Candidate dirty source hunks in `operation_contracts.py` and `mcp_server.py` are excluded: their origin is not established by prior owner receipt, and root already has the needed contract.

## Prior ownership evidence

- [T03-owner-only-mcp-contract-dispatch-20261004.md](T03-owner-only-mcp-contract-dispatch-20261004.md), SHA-256 `6F19771ACCB1DBCCC195DCC73E21487543AD74B3CB6F02096AAFA627522E6382`, lines 7–16: identifies the exact added T03 test function and explicitly says no production-code hunk was needed and no inherited dirty content was in the patch. This proves test ownership; it does not prove origin of candidate source hunks.
- `T03-path-hints-contract-manifest-20261004.md` records the T03/T21 boundary; it fingerprints whole dirty files, not ownership of each inherited hunk.
- The older patch targets stale root snapshot `7cb4bcdf…` with an untracked test file. This replacement is anchored to current tracked root file at line 539.

## Applicability and test receipts

Applicability check, run from root, no application:

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-root-current-path-hints-wrapper-test-20261006.patch
```

Result: exit 0. Root status remained unchanged; patch was not applied.

Actual T03 post-edit selector receipt (previous continuation):

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py::test_mcp_repo_search_forwards_path_hints_to_http_payload
1 passed in 1.88s
request_id=req_43909003c5d7
execution_id=5e41bdf19f784b50917535a8f9756a6d
```

No tests ran while preparing this packet. No root integration or source transfer occurred.
