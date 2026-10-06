# T03 root-current MCP autostart test packet

Date: 2026-10-04 (Europe/Prague)
Owner: T03; test-only packet
Candidate root: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
Candidate HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`
Root HEAD at preparation: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`

## Packet

Patch: `handoff/T03-root-current-autostart-test.patch`
Target: root-current `tests/test_mcp_contract_dispatch.py` only.

Root target is untracked, so no Git `HEAD:path` preimage exists. The packet is pinned to the exact current working-file bytes:

- Root preimage SHA-256: `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`
- Expected postimage SHA-256 after applying patch: `D415E77C1D25D3DAAEC16B6F6D05479FB2D7B8EFD3E2531F294402D95FA24D9D`
- Patch SHA-256: `8A5E8792FAC72F27F0F18CAA7FE0E1C13B786AD0BFC242B549C071500EA5847E`

Patch replaces only the stale transport-selection test function. Fake now accepts `tenant`, `config_path`, and `auto_start`; assertions retain tenant/config and require `auto_start is True`, matching root `_build_mcp_client`. Current root builder does not create `InProcessTransport`; its old lazy-transport assertion cannot remain valid. No production source included.

## Candidate evidence

Candidate suite command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py
```

Recorded same-HEAD result: **110 passed in 22.02s**, exit 0. Candidate test SHA-256: `31ADBEF93145A1C57F049836795ADFAD3FF1424DD3049802F411259931DAF1EC`; candidate builder SHA-256: `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`. Candidate receipt is inherited from `handoff/T03-acceptance-current.md`; no tests rerun here.

## Boundaries

Patch is not applied. Root was not edited and root tests were not run. No `client.py`, `/api/search` route, `/api/context/pack`, or generic transport changes. `process_identity` lifecycle failures remain T16/T04-owned.
