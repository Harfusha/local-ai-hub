# T03 acceptance current evidence

Date: 2026-10-01 (Europe/Prague)

## Current checkout evidence

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Assigned T03 worktree HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`.
- Root dirty `src/local_ai_hub/mcp_server.py` currently has lazy `main()` calling `mcp.run()` directly; T03 live-wire regression is present.
- Root `mcp_server.py` current SHA-256: `5FF372AF25D78EDBB09B7F6D3AB6ECF5F8C9C593247F38A7B01C2CFF8E7929CE`.
- Root `tests/test_mcp_live_wire_schema.py` SHA-256: `772D47A36C65A076B42CF2C70C3834C8EB99CEB0FA6E2E7808AF84B523CDDD29`.
- Root source hash differs from prior candidate postimage because other root-owned dirty hunks changed after integration; these were preserved.

## Root focused acceptance

Exact command, from root:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_live_wire_schema.py::test_stdio_main_does_not_gate_handshake_on_hub_startup tests/test_mcp_live_wire_schema.py::test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up
```

Result: `2 passed in 18.01s`.

## T03 bounded acceptance set

Exact command, from assigned worktree:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py
```

Result: `96 passed in 28.89s`.

This covers contracts and pre-dispatch validation, output dispatch validation, RecoveryJournal compatibility, concurrent auto-start and timeout cleanup fakes, live stdio schema equality, optional FastMCP import fallback, and actual daemon-off MCP initialization/tool call with Hub process cleanup.

`git diff --check` on T03-owned worktree paths returned no whitespace errors; only expected LF-to-CRLF working-copy warnings appeared.

Root was not edited in this continuation. The known T04-owned pubsub transport case and Hub Agent OS verification receipt remain separate acceptance boundaries.

## Acceptance refresh — 2026-10-03

- Candidate `HEAD` remained `ad622f8a90a81e349e94d3402f297f2995e733b2`.
- Exact command, run through `local_ai_command` in the assigned worktree:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py
```

- Result: **108 passed in 23.62s**, exit code 0; execution `44eafbbf81c64b8282eca2f295e01d44`, broker revision `345065f0e66fdc0e096a37ed875406ef6a889f1bd7d7f8de151f7b36fdcfb82b`.
- Reconciled stale test expectations for closed action output schemas, nested result payloads, current HTTP `HubClient(auto_start=True)` selection, and accounting telemetry. Added `test_mcp_repo_search_forwards_path_hints_to_http_payload` for the public MCP wrapper-to-HTTP payload hop.
- Current SHA-256: `tests/test_operation_contracts.py` `2C5AD3398AF7630C06676C7C75745CC66FA8C9B500D6C917685F6F9F4939B320`; `tests/test_mcp_contract_dispatch.py` `CF06429D5C4B9A780B36026C3FD0FB133DF9F3A234518486B685E7C548467475`.
- Announced the public `local_ai_repo(action="search")` `path_hints` contract to T21. T04 confirmed its client-to-HTTP selector covers the next hop.
- Root remains unmodified. Combined MCP-to-real-route/service acceptance remains open for the serial T20 integration slot; current T20 thread reports `systemError`.

## Combined path-hints acceptance boundary — 2026-10-03

Exact T03 test-only delta in this continuation:

- `tests/test_mcp_contract_dispatch.py`: renamed transport selection coverage to assert HTTP `HubClient(auto_start=True)`; added `test_mcp_repo_search_forwards_path_hints_to_http_payload`; made the lightweight map assertion ignore unrelated accounting calls while still requiring one `/api/repo/map` call and no `/api/command` call.
- `tests/test_operation_contracts.py`: updated artifact output union count to three registered variants; kept arbitrary action payload nested under allowed `results`; changed malformed-output assertions to the validator's exact nested field errors.

T21 candidate composition receipt (separate worktree, not T03 proof): HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; selector `tests/test_t21_candidate_path_hint_worktree_e2e.py::test_registered_search_path_hints_use_candidate_worktree_config`; **1 passed in 4.88s**. It covers registered MCP search through client `/api/search` to T21's candidate HTTP handler/service, including a valid hint and traversal rejection. It does not prove T03's checkout or a live daemon.

Ownership boundary from T21: `/api/search` route hunk in `http_server.py` is owned by T06; `services.repo_search` hunk in `services.py` is owned by T16. Neither owner-cleared hunk is available in T03; do not transplant T21 candidate files. T20 broader integration is NO-GO. No root writes and no `/api/context/pack` edits.

## Owned MCP/client selector detail — 2026-10-03

Candidate HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`.

Current T03 source contract (existing candidate hunks; no T06/T16 files):

- `src/local_ai_hub/operation_contracts.py`: `local_ai_repo.search` accepts optional `path_hints`; schema bounds the list to 64 and requires each record's `path`, `purpose`, and `scope`; nested records are validated before dispatch.
- `src/local_ai_hub/mcp_server.py`: `_local_ai_repo_impl` accepts `path_hints` and adds them to `/api/search`; public `local_ai_repo` accepts and forwards the same argument.

Exact T03 test delta is limited to these two T03-owned test files:

- `tests/test_mcp_contract_dispatch.py`: HTTP auto-start expectation; MCP `path_hints` payload selector; classification assertion filtered to one repo-map call and excludes command dispatch.
- `tests/test_operation_contracts.py`: three registered artifact output variants; nested payload on the allowed `results` field; precise nested type-error assertions for closed output schemas.

Current SHA-256:

| File | SHA-256 |
| --- | --- |
| `src/local_ai_hub/mcp_server.py` | `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D` |
| `src/local_ai_hub/operation_contracts.py` | `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF` |
| `tests/test_mcp_contract_dispatch.py` | `CF06429D5C4B9A780B36026C3FD0FB133DF9F3A234518486B685E7C548467475` |
| `tests/test_operation_contracts.py` | `2C5AD3398AF7630C06676C7C75745CC66FA8C9B500D6C917685F6F9F4939B320` |

T04's separate candidate receipt reports its path-hints HTTP selector at **7 passed in 2.31s** and an overall T04 batch at **133 passed in 27.74s**; these are not T03 revision proof. T21's separate candidate selector and exact revision are recorded above. Together these receipts map each owner seam without copying or duplicating T04/T21 code. T03's 108-pass batch includes the T03 public MCP-to-HTTP payload selector.

## Separate request-ID transport gap — 2026-10-03

T04 read-only review identified an API difference outside this `path_hints` selector scope. Current T03 `src/local_ai_hub/client.py` SHA-256 is `E43BA99F5846C4A6EE9A4B92BE15666D38F20AB12D0489B22208CB6792A19962`; `HubClient.request(path, payload, *, timeout, replay_safe)` generates a `req_<12 hex>` ID and sends `X-LocalAI-Request-ID`, but accepts no caller-supplied `request_id` argument and does no explicit-ID validation. The 108-pass T03 batch did not include `tests/test_client_transport.py`.

T03 client selectors identified by T04: `test_client_replays_explicitly_safe_post_with_stable_request_id`, `test_client_does_not_replay_ambiguous_default_post`, `test_post_malformed_response_returns_explicit_unknown_outcome`. T04 candidate selectors for supplied IDs: `test_post_uses_explicit_request_id_across_safe_retry`, `test_post_rejects_malformed_request_ids_before_network`, `test_safe_posts_with_distinct_explicit_request_ids_do_not_coalesce`. This difference needs a same-revision owner handoff and transport acceptance; no client source/test changes were made for it here, and it is not covered by the T03 `path_hints` selector receipt.

## Current root preimage audit — 2026-10-03

- Read-only root HEAD is now `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, different from T04 patch's pinned HEAD `360a58f90d0d6562641e62d15095410fc5dd044a`.
- Root `src/local_ai_hub/client.py` SHA-256 still matches the patch preimage: `393791DFC87F64247DB675B1E76C86DF6B4C666B937B70CAD2A55FC7BE44502C`.
- Root `tests/test_t04_inprocess_transport_acceptance.py` is absent. Root has a separate untracked `tests/test_t04_client_retry_acceptance.py`; T04 receipt says it is not touched.
- T04 patch artifact `artifacts/t04-root-current-inprocess-retry-20261003.patch` SHA-256 `3D68E854708CE604BEA0442EF8491D2F1022BBC78BA962410ECE6B51FA557DB9`. Historical `git apply --check` passed against the pinned older root HEAD only.
- A fresh `git apply --check` was submitted through `local_ai_command` against current root, but the broker returned no result before the bounded wait was stopped. Current applicability is therefore **unverified**. No patch was applied; no root file was written. Root selector remains unrun pending serial GO.

## Candidate contract/transport refresh — 2026-10-04

- Assigned candidate: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`; HEAD `ad622f8a90a81e349e94d3402f297f2995e733b2`.
- Targeted command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py`.
- Result: **108 passed in 26.83s**, exit 0. Ran in the assigned candidate worktree; no root tests or integration run.
- Scoped `git diff --check -- src/local_ai_hub/mcp_server.py src/local_ai_hub/operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_operation_contracts.py`: exit 0; only expected LF-to-CRLF working-copy warnings.
- Current T03 file hashes match the 2026-10-03 candidate receipt: `mcp_server.py` `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`; `operation_contracts.py` `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF`; `test_mcp_contract_dispatch.py` `CF06429D5C4B9A780B36026C3FD0FB133DF9F3A234518486B685E7C548467475`; `test_operation_contracts.py` `2C5AD3398AF7630C06676C7C75745CC66FA8C9B500D6C917685F6F9F4939B320`.
- T03-owned scope remains MCP search input contract/wrapper and its contract/dispatch tests. HTTP `/api/search` route is T06-owned; T04 `client.py` timeout cleanup/request-ID acceptance remains a separate boundary. No inherited hunks were edited.
- Root/master unchanged. Current live lease list was not refreshed because Hub calls are disabled for this continuation; worktree assignment and prior owner-boundary receipt remain the ownership evidence.

## Candidate HubClient transport supplement — 2026-10-04

- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_replays_explicitly_safe_post_with_stable_request_id tests/test_client_transport.py::test_client_does_not_replay_ambiguous_default_post tests/test_client_transport.py::test_post_malformed_response_returns_explicit_unknown_outcome`.
- Result: **3 passed in 1.35s**, exit 0.
- This supplements T03 candidate transport acceptance only. Explicit caller-supplied request-ID validation remains a separate T04 contract/selector; these tests do not prove it.

## MCP isolation continuation — 2026-10-04

- Added two focused regression selectors in `tests/test_mcp_contract_dispatch.py`: shared-daemon `HubClient` requests keep tenant header, root and task ID paired; concurrent instrumented `local_ai_coord` calls keep task metadata paired.
- Exact selector command: `python -B -m pytest -vv -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py::test_shared_daemon_mcp_clients_keep_tenant_root_task_isolated tests/test_mcp_contract_dispatch.py::test_concurrent_instrumented_mcp_actions_keep_task_metadata_isolated`.
- Result: **2 passed in 1.90s**, exit 0.
- Updated owned suite command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py`.
- Result: **110 passed in 22.02s**, exit 0.
- `git diff --check -- tests/test_mcp_contract_dispatch.py`: exit 0; only expected LF-to-CRLF warning. Test SHA-256 `31ADBEF93145A1C57F049836795ADFAD3FF1424DD3049802F411259931DAF1EC`; `mcp_server.py` unchanged by this continuation, SHA-256 `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`.
- T06 confirms route contract: forward `path_hints` only for keyword-capable parameter kinds; `VAR_POSITIONAL` returns 501. T06 route patch remains blocked by unavailable checkout and lease. T04 transport contract request is pending; no `client.py` edits.
