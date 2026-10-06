# T04 root-compatible singleflight packet

## Scope and diagnosis

No root source was edited and no tests were run. HUB was not used.

T04 baseline HEAD is `3658d5056354849ddf17883ed04f807f16cc44c1`; baseline client blob `3efbfc395bf512f3cc7b9d713ee3d1a665288eb5` defines `_singleflight(self, key, timeout, execute)` without `request_id`. Current T04 candidate client SHA-256 is `A1D5DBCCEEDF7432EB420B2A16A97C874693B8D5FF566C75FFAD12B993B07186`; its keyword-only signature accepts `request_id` and `cancel_event`, GET passes both, and the waiter retains owner request ID. GET timeout result also propagates the owner ID from the exception. Root preimage client SHA-256 was `7D0EF3BE7A95152318FAE1B7E7B8376BFAAE065EEAD4C5CC4F2A37C1DF06DEA2`; root working source accepted both keywords. These facts show a baseline/runtime version boundary, but do not prove which module the live process imported.

## Prepared patches

- `handoff/t04-root-singleflight-owner-id.patch`, SHA-256 `AF146488306D8BEC05C5DD745D119B665B3ECD11A639AD4BBB445A5AE50F7FC7`. Against root current client worktree SHA above, it stores the owner request ID on the flight, uses that ID for waiter timeout, and preserves the server-visible owner ID in waiter results (`setdefault`, no waiter overwrite). Flight removal still precedes event signaling. It does not change `request_id`/`cancel_event` signatures or cancellation behavior.
- `handoff/t04-root-singleflight-owner-id-test.patch`, corrected SHA-256 `EB3BDC3BF6C1DDEEF5C79FE06C473F9B6A02812373F50507CE49BA3FB34D8687`. Adds two selectors: `test_coalesced_get_returns_server_visible_owner_request_id` synchronizes owner/waiter calls and checks one HTTP ID survives; `test_get_reuses_request_id_after_autostart_retry` injects one connection refusal, verifies autostart, and checks the retry uses the same ID. Only `HubClient.get` and transport tests are involved; no worktree-ID forwarding hunk. The owner-ID production delta is only `_singleflight` bookkeeping plus GET timeout ID propagation.

Both patches passed read-only `git apply --check` against root preimages. Orchestrator integrated these two hunks into root; T04 did not reapply them. Recorded root preimage SHA-256: client `7D0EF3BE7A95152318FAE1B7E7B8376BFAAE065EEAD4C5CC4F2A37C1DF06DEA2`, test `D1B02094AF21A2B2C4A1577F10B4211FC6C9F2CBED32E60C32CDAB9FD27F2EDC`; HEAD preimage blobs: client `32610a921ccd1c7718e0378406bedca7b21c995b`, test `67c4b50af2ff8a82e3f9e2d1ac81d09f01d235ee`. Observed root post-integration SHA-256: client `7E326D5B21F460B9CE81299920935237A6A474F144AD64C459E3BA0C9367F2DA`, test `2A130EE93E30E3C7C13DF98B51C4AFAC8078F006FEE81801AE0F3CDBDD6CAFE6`.

T04 candidate transport test SHA-256: `F881EA45E1DF0FFF82B8D06F0C376330B46DFD9A0646F63E781B896825805EAE`. The real-child startup test file `tests/test_client_startup_resilience.py` now has SHA-256 `F9E7A1E487980BCD87BC5C553AC837F42B33E3FFADB862BB1CCAA56268FF1BD0`; its owned test captures each actual `_open` request ID and asserts the autostart retry reuses `t04-real-child-search`. Owner-ID implementation is in T04 candidate; all new regressions remain unrun. T16 confirmed no overlap with its `HubClient.coord` worktree-ID forwarding branch. No RED/GREEN claim is made.

## Validation after T20 GO only

From `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`:

```powershell
$env:PYTHONPATH = "C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src"
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_get_passes_request_id_through_singleflight tests/test_client_transport.py::test_coalesced_get_returns_server_visible_owner_request_id tests/test_client_transport.py::test_get_reuses_request_id_after_autostart_retry tests/test_client_transport.py::test_coalesced_replay_safe_post_timeout_returns_owner_request_id tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result
```

Do not run until T20 issues an explicit test-slot GO. Runtime provenance still requires the live MCP process's `local_ai_hub.client.__file__` and loaded method signature; the current source comparison alone does not prove a stale installation.

## 2026-10-04 continuation checkpoint

The assigned T04 worktree still exists at HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`; candidate hashes remain client `A1D5DBCCEEDF7432EB420B2A16A97C874693B8D5FF566C75FFAD12B993B07186` and transport tests `F881EA45E1DF0FFF82B8D06F0C376330B46DFD9A0646F63E781B896825805EAE`. T16 confirms its worktree-ID forwarding is in separate `HubClient.coord`; T04 GET/singleflight scope does not overlap.

T20 GO remains unconfirmed. T20's assigned `ec50` snapshot recovery failed with `The archived worktree snapshot is missing`; no fresh lease/GO receipt is available. This continuation changed only T04 client transport source/test paths. `client.py` SHA-256 now `0DDA3813ABF650127DE614ED6EA8F9646FC44805CC05CF4A7603D5FE9DFDC9ED`; `tests/test_client_transport.py` SHA-256 now `B988C13FF289A491CAB3C35F263AB724626B37867B6BADBDD4588AA551391406`. The existing T04 startup regression now captures actual `GET`/POST transport request IDs around real autostart; its file remains SHA-256 `F9E7A1E487980BCD87BC5C553AC837F42B33E3FFADB862BB1CCAA56268FF1BD0`. POST replay-safe `_singleflight` now receives generated `request_id`; timeout response preserves the owner ID. Retry classifier, `HubClient.coord`, root, and `/api/context/pack` untouched. No tests/builds run. Use the five-selector command above only after explicit T20 GO.

## 2026-10-04 T20 review packet

T20 reported slot unassigned/idle and no T04 GO. Hold all selectors until explicit GO. Candidate hashes remain `client.py` `0DDA3813ABF650127DE614ED6EA8F9646FC44805CC05CF4A7603D5FE9DFDC9ED`, `tests/test_client_transport.py` `B988C13FF289A491CAB3C35F263AB724626B37867B6BADBDD4588AA551391406`, `tests/test_client_startup_resilience.py` `F9E7A1E487980BCD87BC5C553AC837F42B33E3FFADB862BB1CCAA56268FF1BD0`.

Root-current un-applied patch: `handoff/t04-post-owner-request-id-root-current.patch`, SHA-256 `781C40AE092353364DD8F6BC82CB43FA0334F3E7B1213E39F102EB7F5EC95371`. It passes `git apply --check` against root-current preimages: `src/local_ai_hub/client.py` SHA-256 `7E326D5B21F460B9CE81299920935237A6A474F144AD64C459E3BA0C9367F2DA`, HEAD blob `32610a921ccd1c7718e0378406bedca7b21c995b`; `tests/test_client_transport.py` SHA-256 `2A130EE93E30E3C7C13DF98B51C4AFAC8078F006FEE81801AE0F3CDBDD6CAFE6`, HEAD blob `67c4b50af2ff8a82e3f9e2d1ac81d09f01d235ee`. Root was not modified by T04.

Exact T04 candidate command after GO:

```powershell
$env:PYTHONPATH = "C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src"
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_get_passes_request_id_through_singleflight tests/test_client_transport.py::test_coalesced_get_returns_server_visible_owner_request_id tests/test_client_transport.py::test_get_reuses_request_id_after_autostart_retry tests/test_client_transport.py::test_coalesced_replay_safe_post_timeout_returns_owner_request_id tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result
```

No tests/builds were run. The real-child selector exercises actual Hub auto-start, retry, HTTP search result, child ownership, and cleanup. T20 owns scheduling and GO.

## 2026-10-04 continuation receipt

No tests were run in this continuation. The earlier T20 one-shot root selector `test_coalesced_replay_safe_post_timeout_returns_owner_request_id` passed once (`1 passed in 2.07s`); that GO is consumed. T04's assigned nine-file suite separately passed `132 passed in 26.57s`, exit 0; this receipt does not cover the full T04 acceptance matrix. T20 is still active and no fresh T04 GO is available, so hold the five-selector rerun above.

Current T04 candidate remains HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`; current source/test SHA-256: `client.py` `0DDA3813ABF650127DE614ED6EA8F9646FC44805CC05CF4A7603D5FE9DFDC9ED`, `test_client_transport.py` `B988C13FF289A491CAB3C35F263AB724626B37867B6BADBDD4588AA551391406`, `test_client_startup_resilience.py` `F9E7A1E487980BCD87BC5C553AC837F42B33E3FFADB862BB1CCAA56268FF1BD0`.

The current candidate `mcp_server.py` statically carries `path_hints` through `_local_ai_repo_impl`, the public `local_ai_repo` wrapper, and `/api/search`. `tests/test_t04_root_path_hint_chain.py` contains a real-root HTTP integration selector for that route. This corrects the earlier source-only report that the public wrapper lacked the field; selector execution is still unverified. T21 adapter/runtime proof and a fresh serial validation slot remain outstanding. Shared `mcp_server.py` was not edited by this continuation. Latest T20 snapshot remains in progress: T06 archived snapshot is missing, slot refresh is pending, and no new T04 GO was issued.

## 2026-10-04 root-current integration manifest

This is a receipt for the already-authorized root integration; no root edits or tests occurred in this continuation. Root HEAD remains `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

| Root path | Preimage SHA-256 immediately before apply | Current postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/client.py` | `7E326D5B21F460B9CE81299920935237A6A474F144AD64C459E3BA0C9367F2DA` | `B598CDC9A6EDCEBCCAD9BA94C8E97082A56C410CC6601A0829E93600E86B9663` |
| `tests/test_client_transport.py` | `2A130EE93E30E3C7C13DF98B51C4AFAC8078F006FEE81801AE0F3CDBDD6CAFE6` | `AD875F7469D68FFEF6BE0D11FF52D32AC4CFAD5794E70AAB5A0459CD307106F0` |

Patch: `handoff/t04-post-owner-request-id-root-current.patch`, SHA-256 `781C40AE092353364DD8F6BC82CB43FA0334F3E7B1213E39F102EB7F5EC95371`. Its two hunks are limited to (1) `HubClient.post()` passing the already-generated owner `request_id` into replay-safe `_singleflight`, preserving that ID for a coalesced waiter's timeout result; (2) adding `test_coalesced_replay_safe_post_timeout_returns_owner_request_id`. No other paths are in this patch. It does not touch GET, `HubClient.coord`/T16 forwarding, the T07 retry classifier, T10 fixture setup, T13's copied `operational_mode.py`, `/api/context/pack`, `http_server.py`, or shared MCP routing. Existing unrelated dirty hunks remain owned by their recorded owners; this manifest does not claim ownership of whole dirty files.

Ownership/lease: T20's one-shot root integration authorization was consumed; its separately authorized root selector passed once (`1 passed in 2.07s`). No fresh root-write lease or T04 test-slot GO is recorded. T20's latest snapshot reports missing T06 archived state and pending slot refresh. Do not reapply the patch or repeat the selector.

Remaining acceptance: the plan records a 39-test public API/conversation/query/inventory receipt at commit HEAD `3658d505…`, but it predates the current dirty working-tree source; no new broad rerun occurred here. Latest nine-file suite did not include the two direct ArtifactStore tenant selectors; they passed in this continuation below. The path-hint public wrapper and real-root HTTP selector are present, but the selector is integration and has no current receipt; T21 adapter/runtime proof remains absent. Candidate nine-file suite receipt is `132 passed in 26.57s`; it does not close those gaps. Root receipt remains one selector only.

## 2026-10-04 candidate-only unit receipt

No root tests or integration ran. At candidate HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`, ran the following native command in the T04 worktree; HUB was unavailable and not called:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_public_api_contracts.py::test_artifact_list_v2_hashes_and_isolates_tenants tests/test_t04_public_api_contracts.py::test_artifact_list_legacy_hashes_and_isolates_tenants tests/test_t04_public_api_contracts.py::test_coord_task_list_forwards_query tests/test_t04_public_api_contracts.py::test_semantic_diff_action_uses_public_call_graph_diff_route
```

Result: **4 passed in 2.60s**, exit 0. The first command attempt named the wrong module for `test_coord_task_list_forwards_query`; pytest reported the selector missing and ran zero tests. The selector was corrected, then the command above passed. Candidate HEAD stayed fixed; current SHA-256 after the run: `artifacts.py` `7F598EE33012F3990CE6792D32EC2C125E12BBD113F0DF2B1A75C11C91ABB5B1`, `mcp_server.py` `1D7C6E0C0FE37FB61C23BC203E179B05E472175326DD8DDCCB388916EA1827A1`, `test_t04_public_api_contracts.py` `F95730F0D77B51C1D9163BA1B5F95B47967A981CE278128D305A2EF4C925C002`, `test_mcp_agent_routing.py` `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`. The test run introduced no source edits; these files retain their pre-run dirty/clean status. Root HEAD and its two patch post-image hashes remain unchanged.

## 2026-10-04 current transport/SSE receipt

The older 16-selector list contained stale selector `test_transport_other_connect_failure_is_not_classified_as_request_not_sent`. Current candidate test is `test_transport_other_connect_failure_is_classified_as_request_not_sent`; it simulates a connect timeout before write and asserts `request_not_sent=true`, `outcome_unknown=false`, preserving the request ID. After this evidence-based selector correction, ran this exact candidate-only command (no root tests/integration):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py::test_sse_stream_does_not_lose_event_between_replay_and_subscribe tests/test_sse_events_stream.py::test_sse_stream_timeout_bounds_queue_wait tests/test_sse_events_stream.py::test_client_stream_events_parsing tests/test_client_transport.py::test_stream_events_sends_client_identity_and_caps_timeout tests/test_client_transport.py::test_stream_events_reports_uncertain_partial_disconnect tests/test_client_transport.py::test_stream_events_cancel_event_closes_blocked_response tests/test_client_transport.py::test_stream_events_enforces_deadline_while_response_is_blocked tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown tests/test_client_transport.py::test_post_malformed_response_returns_explicit_unknown_outcome tests/test_t04_malformed_json_contract.py
```

Result: **16 passed in 3.71s**, exit 0. The stale-selector attempt ran zero tests. Candidate HEAD stayed `3658d5056354849ddf17883ed04f807f16cc44c1`; post-run SHA-256: `client.py` `0DDA3813ABF650127DE614ED6EA8F9646FC44805CC05CF4A7603D5FE9DFDC9ED`, `test_client_transport.py` `B988C13FF289A491CAB3C35F263AB724626B37867B6BADBDD4588AA551391406`, `test_sse_events_stream.py` `BCEE7A41E7A561DE6E1F4C5F7C663CCFE518CAC9616F48064A5CD86CB67EEECC`, `test_t04_malformed_json_contract.py` `D8974B8B59FF577792A50AA31E83A33959FB820C433A6EFAA617DE1B9659FDE7`. No source edits from the test command. Root remains unchanged; T21 adapter/runtime and path-hint integration proof stay open.

## 2026-10-04 owner-only client/SSE root patch

Prepared in the T04 worktree only: `handoff/t04-owner-client-sse-contract-root-current-20261004.patch`. Initial review draft SHA-256 `E6CF1C560E73E2116A11A96D36E48C59B4F99E0603AA21F4E175A92EAA51EEB9` was superseded after review; see the revision below. Candidate HEAD is `3658d5056354849ddf17883ed04f807f16cc44c1`; root target HEAD is `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

| Root path | Current preimage SHA-256 |
|---|---|
| `src/local_ai_hub/client.py` | `B598CDC9A6EDCEBCCAD9BA94C8E97082A56C410CC6601A0829E93600E86B9663` |
| `tests/test_t04_client_sse_socket_interrupt.py` | absent; patch adds this file with candidate SHA-256 `5409380F0311F46CE6A6B63F8ABA23CE0CCE70CC7AB059B4476166883A64E793` |

The patch contains only these owner hunks: in `HubClient.stream_events()`, close the underlying socket and response connection on cancellation/deadline, and classify a socket `TimeoutError` as `retry_timeout`; add an isolated regression for socket shutdown, response/connection closure, and timeout result. The existing non-dict SSE payload normalization remains unchanged. The standalone test avoids editing shared `test_client_transport.py`.

Duplicate check: candidate and root ASTs are identical for `_pooled_open`, `_open`, `_transport_failure_response`, `_singleflight`, and `coord`; the request-ID owner patch is already integrated and its root selector already passed once. None is repeated here. The older Oct 3 client/in-process/test patches fail current-root apply-check and are excluded. Current patch `git apply --check --recount` passes against root preimages; root was not modified and no root tests ran.

Fresh candidate receipts: the corrected 16-selector SSE/transport command above **16 passed in 3.71s**; new socket-interrupt regression `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_sse_socket_interrupt.py` **1 passed in 0.79s**. No root test/acceptance receipt for this patch; T20 GO remains required.

## 2026-10-04 review revision: socket import and narrow close errors

The current patch SHA-256 is `10E929819280FD07997A65B748F34787B3890EC9FFB8E82B2FE6F86C8A437A75`. Production hunk 1 adds `import socket` to the root client import block; stream interruption catches only `OSError` around socket shutdown, response close, and connection close. Candidate `client.py` SHA-256 after the same narrow close-error change is `F8F3E66468AC6539EBBFFD1A4682276486CB0ED4735C633402F3F29BEF223A5E`; the standalone test SHA-256 is unchanged at `5409380F0311F46CE6A6B63F8ABA23CE0CCE70CC7AB059B4476166883A64E793`.

Current exact candidate command, including the socket-interrupt regression and all 16 SSE/transport selectors:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_sse_socket_interrupt.py tests/test_sse_events_stream.py::test_sse_stream_does_not_lose_event_between_replay_and_subscribe tests/test_sse_events_stream.py::test_sse_stream_timeout_bounds_queue_wait tests/test_sse_events_stream.py::test_client_stream_events_parsing tests/test_client_transport.py::test_stream_events_sends_client_identity_and_caps_timeout tests/test_client_transport.py::test_stream_events_reports_uncertain_partial_disconnect tests/test_client_transport.py::test_stream_events_cancel_event_closes_blocked_response tests/test_client_transport.py::test_stream_events_enforces_deadline_while_response_is_blocked tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown tests/test_client_transport.py::test_post_malformed_response_returns_explicit_unknown_outcome tests/test_t04_malformed_json_contract.py
```

Result: **17 passed in 2.56s**, exit 0. Current root preimage `src/local_ai_hub/client.py` SHA-256 remains `B598CDC9A6EDCEBCCAD9BA94C8E97082A56C410CC6601A0829E93600E86B9663`; new root test path is absent. `git apply --check --recount` passes, exit 0. Root HEAD remains `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; root source hash is unchanged and no root tests ran.

Review audit confirmation: the revised patch contains `+import socket` in the production `client.py` hunk (not only in the test file); catches are narrowed to `OSError`.

Root-current overlay receipt: copied the exact root `src/` preimage (`client.py` SHA-256 `B598CDC9A6EDCEBCCAD9BA94C8E97082A56C410CC6601A0829E93600E86B9663`) to a temporary directory, applied this patch there (`git apply --check --recount` exit 0; apply exit 0), then ran `PYTHONPATH=<temporary-overlay>\src C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_sse_socket_interrupt.py`: **1 passed in 0.28s**, exit 0. Overlay post-image `client.py` SHA-256 `4E250AD3496E665F428FAC5B0E231238AE71017ED9078C2682513932797CA632`. Temporary overlay was removed automatically. Root checkout remains unchanged; no root test command or root edit occurred.

## Root integrated SSE sub-scope receipt (2026-10-04)

T20 reports the corrected patch integrated against the exact root preimage `src/local_ai_hub/client.py` SHA-256 `B598CDC9A6EDCEBCCAD9BA94C8E97082A56C410CC6601A0829E93600E86B9663`. Root post-image client SHA-256 is `4E250AD3496E665F428FAC5B0E231238AE71017ED9078C2682513932797CA632`, matching the tested overlay. Root test SHA-256 is `410303CC9CD8BED6E4389F0F88FF45918583E1D8C01648656A65E96FD79D0011`; after newline normalization it matches candidate SHA-256 `5409380F0311F46CE6A6B63F8ABA23CE0CCE70CC7AB059B4476166883A64E793`. Root `tests/test_client_transport.py` SHA-256 remains `AD875F7469D68FFEF6BE0D11FF52D32AC4CFAD5794E70AAB5A0459CD307106F0`; HEAD remains `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

T20-reported exact root command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_sse_socket_interrupt.py tests/test_client_transport.py` — **32 passed in 3.60s**, exit 0. This closes the client SSE socket-interruption sub-scope only; broader T04 HTTP/MCP, path-hints/service-consumer, and runtime acceptance remain open. No root edit or test ran in this documentation continuation.

## 2026-10-04 candidate-only startup/tenant receipt

At candidate HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`, native bounded candidate run only; no root tests or integration. HUB ignored as requested.

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py::test_managed_marker_refuses_client_supervisor_and_returns_exact_offline_error tests/test_client_startup_resilience.py::test_managed_client_preserves_offline_error_contract_without_autostart tests/test_client_startup_resilience.py::test_readiness_timeout_cleans_lock_after_service_start tests/test_client_startup_resilience.py::test_30_concurrent_offline_clients_share_one_startup tests/test_client_startup_resilience.py::test_cross_process_offline_clients_share_one_unmanaged_autostart tests/test_client_tenant_override.py::test_http_response_wait_is_bounded_and_cancellable tests/test_client_tenant_override.py::test_cancelled_request_before_dispatch_is_marked_not_sent tests/test_client_tenant_override.py::test_concurrent_task_requests_derive_tenant_per_root_for_same_task_id tests/test_client_tenant_override.py::test_root_scoped_post_accepts_only_matching_tenant_hints tests/test_client_startup_resilience.py::test_service_start_timeout_releases_start_lock
=> 11 passed in 4.70s
```

Current candidate SHA-256: `src/local_ai_hub/client.py` `F8F3E66468AC6539EBBFFD1A4682276486CB0ED4735C633402F3F29BEF223A5E`; `tests/test_client_startup_resilience.py` `F9E7A1E487980BCD87BC5C553AC837F42B33E3FFADB862BB1CCAA56268FF1BD0`; `tests/test_client_tenant_override.py` `C34DA8FA8C740FA1711F20C213D0CCA978515C89DD101302166F01275B05F1EF`.

This receipt proves bounded candidate behavior for the listed selectors only. It does not close root-current startup/process ownership, path-hint adapter/runtime, or the fresh full T04 acceptance matrix. No client source changed.
