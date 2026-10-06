# T03 `path_hints` public contract manifest

Date: 2026-10-04 (Europe/Prague)
Candidate root: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
Candidate HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Released boundary

`local_ai_repo(action="search")` exposes optional `path_hints`. The public schema limits the list to 64 objects; each object requires `path`, `purpose`, and `scope`, and rejects undeclared fields. The MCP adapter forwards the list to `/api/search`. Search service semantics and the `/api/search` implementation remain with their existing owners, T21/T16/T06.

T21 notification sent in Codex thread `01a0d7b9-04b9-7da1-906e-393693d07f65` on 2026-10-04. T03 owns only the public contract and MCP forwarding seam.

## Source and test fingerprints

Preimage SHA-256 is the blob at candidate `HEAD`; postimage SHA-256 is the current worktree file. These hashes fingerprint whole files, which also contain unrelated previously existing dirty hunks. No such hunks were changed for this manifest.

| Path | Preimage SHA-256 | Postimage SHA-256 |
| --- | --- | --- |
| `src/local_ai_hub/operation_contracts.py` | `d2120b614852de7ab7006f65b8ae30d5b6eee474ebcad69cb2605d37ec119329` | `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF` |
| `src/local_ai_hub/mcp_server.py` | `229b62a68305f3236be4c4782fe17be1efe36f557e48b0fdfe1875a31f838848` | `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D` |
| `tests/test_operation_contracts.py` | `6c388ced440d8eda35dee2c39762a1289412892c447ebf91ba08d3c0e8bc2bf5` | `2C5AD3398AF7630C06676C7C75745CC66FA8C9B500D6C917685F6F9F4939B320` |
| `tests/test_mcp_contract_dispatch.py` | `1bba650f154e835f961a7fa72494c0db3c6a806d72f7dd8465f3e86d41606b81` | `31ADBEF93145A1C57F049836795ADFAD3FF1424DD3049802F411259931DAF1EC` |

## Candidate validation receipts

Exact core command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py
```

Recorded candidate result: **110 passed in 22.02s**, exit 0. The suite includes `test_mcp_repo_search_forwards_path_hints_to_http_payload` and ran at the candidate HEAD above. Receipt is inherited from `handoff/T03-acceptance-current.md`; tests were not rerun for this manifest. T20 was inactive on 2026-10-04 after its usage limit, so this continuation did not start a competing test run.

Supplemental recorded candidate command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_replays_explicitly_safe_post_with_stable_request_id tests/test_client_transport.py::test_client_does_not_replay_ambiguous_default_post tests/test_client_transport.py::test_post_malformed_response_returns_explicit_unknown_outcome
```

Recorded result: **3 passed in 1.35s**, exit 0. Caller-supplied request-ID support remains T04-owned and is not covered by this receipt.

## Ownership and exclusions

No root checkout edits. No T21 search/service implementation edits. No T04 client edits. No `/api/context/pack` edits. Inherited worktree changes remain untouched.
