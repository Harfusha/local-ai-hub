# T04 root reconciliation — 2026-10-03

## Startup lock and singleflight state

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Current root working-tree preimages: `src/local_ai_hub/client.py` SHA-256 `7D0EF3BE7A95152318FAE1B7E7B8376BFAAE065EEAD4C5CC4F2A37C1DF06DEA2`; `tests/test_client_transport.py` SHA-256 `D1B02094AF21A2B2C4A1577F10B4211FC6C9F2CBED32E60C32CDAB9FD27F2EDC`; `tests/test_t04_root_start_lock_acceptance.py` SHA-256 `ACD6F1995B13896FD715C8ED11929A5C033B1FE024F96F47B247E04C502717E1`.
- Current root source already contains both T04 changes: `_singleflight(..., request_id=...)` caller-ID handling and startup marker process-creation identity with PID-reuse rejection. Root tests include marker identity, reused PID, same live identity, and 30-client mock selectors.
- Earlier source patch `artifacts/t04-root-current-startup-lock-20261003.patch` SHA-256 `AF77C4024C08C667799010E90F9979404C5A50DF981E7193CEB39121DA73FB0E` targeted old `client.py` preimage `C2CDC6EF131D9134D39251B7597DE84200DCD093118C9A2EC1CE863CB440D50D`. It must not be forward-applied to current root.
- Read-only `git apply --check --reverse` of that old patch against current root passed, exit 0. This confirms startup-lock change is already present. No new forward patch was generated because there is no remaining source delta; no root file was written. No root acceptance test was run.

## Process and tenant evidence

- `tests/test_client_startup_resilience.py::test_30_concurrent_offline_clients_share_one_startup` uses 30 threads and mocked `subprocess.run`; it verifies one mock service start, not multi-process runtime.
- `::test_cross_process_offline_clients_share_one_unmanaged_autostart` uses two real spawned Python workers and a shared startup lock; each worker replaces `subprocess.run` with a mock and writes a simulated ready file. This proves process-level lock coordination, not a real Hub daemon.
- Current candidate real-child tests failed in the latest bounded run: `/api/search` did not become ready; both MCP stdio tests recorded zero Hub children. Their isolated state directories contained `service.managed` and operational metadata, no `hub.pid`; targeted process search found no matching test child afterward.
- Root/task/tenant contracts have source and thread/mock tests in `tests/test_client_tenant_override.py`, including two roots sharing task ID (`:210`), tenant-hint binding (`:265`), rootless principal binding (`:387`), and invalid override preflight (`:592`). No fresh current-candidate real multi-process tenant-isolation run exists.
- Path hints flow through candidate public `local_ai_repo` in `src/local_ai_hub/mcp_server.py:1745,1810` and `HubClient.post` in `src/local_ai_hub/client.py:1332-1358`. Candidate HTTP search/service path has no `path_hints` handling; current chain test still returns excluded `secret/blocked.py`. HTTP/MCP route ownership belongs to T03; T04 did not edit it.
- Existing runtime receipt reports 54 MCP and 2 HTTP processes at about 3.65 GB RSS, but labels acceptance failed because of supervisor recycling, schema-preflight races, and SQLite locks. It is not current post-fix RSS acceptance evidence.

## Validation bounds

- Candidate focused mock lifecycle/mode/lock/request-ID selectors: 15 passed in 3.43s, exit 0.
- Current root tests were not run; serial slot released to next owner.
- No claim of full T04 end-to-end acceptance, real daemon singleton, or post-fix RSS measurement.
