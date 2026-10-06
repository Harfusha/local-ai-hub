# T04 client hunk provenance — current candidate

Candidate only. This packet does not authorize root integration or transfer ownership.

## Identity

- Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
- Branch / base HEAD / base parent: `codex/t04-integration-2b33602` / `3658d5056354849ddf17883ed04f807f16cc44c1` / `f305ec6a8f4200b1fd9a2bde5048f43bd508db19`
- `client.py` base Git blob: `3efbfc395bf512f3cc7b9d713ee3d1a665288eb5`
- `client.py` current Git blob: `7882e8fe72bd14d9227daff118d70bff86b86207`
- `client.py` current SHA-256: `8EED9005A1374F48CD6FDC4738FE42985AB00FF2E20EDEFDB1F9D06E003759B5`
- `mcp_server.py` base/current blobs: `17883c18c2512a622af96a4e6a25de7a43219aca` / `1c516284ed716e0d264e8e3913813f2653c3a702`
- `test_runtime_hardening.py` base/current blobs: `6d5114f02bf00e0f808b57ec61241a0351aeb82f` / `0de729f0ff5738f65a181a998c69547b9029673b`
- `test_sse_events_stream.py` base/current blobs: `e964d158f5075495bd0121a2e4de31890557f4f4` / `8b8c4d4daac8089b8fd9de669ad75a52ce9ab119`

## Current client hunks and ownership

| Current lines / symbols | Provenance | Handoff boundary |
|---|---|---|
| `client.py:65-94` `_stop_owned_child`, `_live_start_lock` | T04 startup/process safety. Recent empty `O_EXCL` lock is treated as in-progress until PID write; old empty lock still expires. T04 checks PID + age only, so PID reuse and replacement races remain. | T03 candidate at HEAD `49008c8f104ea569dffc60e2f36f6eb62b92a57e` passed four focused lock regressions; its source is separate and not reconciled into T04. |
| `client.py:98-116`, `470-590`, `591-625`, `978-995` timeout cap and SSE deadline fallback | T04 client timeout/resilience; SSE server/events are T08-owned. | Shared stream seam; don't transfer SSE/server behavior without T08 review. |
| `client.py:164-226` `_pooled_open`; `238-260` `_transport_failure_response`; `462-590` request identity/replay | T04 client transport; request-ID replay/idempotence also T07; transport contract depends on T03. | Mixed hunks inside `request`; no isolated whole-method patch without T03/T07 agreement. |
| `client.py:304-437` `ensure_server` | T04 bounded autostart/process lifecycle. Mode gate at `314-323` calls T13's `operational_mode` API. Existing managed-supervisor/listener checks were already in base and are not attributed to T04. | Cross-revision probe passed against root module hash `19EDE1E62C79E160D41F47FE5BB05F0EA3048988E4A9E00C1DA8C03353667F85`; it stubs `Popen`, so real child launch remains unverified. Keep mode gate outside T04-only transfer. |
| `client.py:27-43` `PathHint`; `675-710` path-hint serialization | T21-owned path-hint contract, shared client seam requested by T04. | Exclude from a T04-only patch. Existing standalone artifact: `artifacts/t04-t21-client-propagation/t21-client-propagation.patch` (SHA-256 `eb44f8be196fad83eaa58c52ef5c49c6e417468c823a14d6c43be07067c452e4`), based on T04 HEAD; do not combine implicitly. |
| `mcp_server.py:1771` `_local_ai_repo_impl` forwards `include_code` | T04-owned, discrete one-line fix. | Standalone MCP hunk; test `tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code`. |
| `test_runtime_hardening.py:107,122,141,157` callbacks accept `*_args`; `test_sse_events_stream.py:154-155` fixture sets tenant/agent | T04 compatibility fixture updates for timeout-aware startup and SSE identity. | Test-only hunks; no production ownership transfer. |

## Existing patch artifacts

- `artifacts/t04-client-transport-owned/client-transport-owned.patch` is an earlier owner-scoped request-ID/stream-timeout patch (SHA-256 `587b56ccbc7db89ee3cde736866168eb1c7ef3c8a84e05a8b379b547192c454d`). Its manifest targets a different root base (`824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`) and its client target blob is `04c69e67c5eec46c9092d6d3385c0e99fc914b38`; it does not contain the latest startup-lock fix. Treat as historical evidence, not patch for the current blob.
- `artifacts/t04-operational-mode/operational-mode-autostart.patch` isolates the T04 callsite but depends on T13's real module. Its test uses a synthetic stub, so it is not integrated acceptance.
- `artifacts/t04-client-path-hints-transport-combined/client-path-hints-transport.patch` combines T04/T21 and is not a T04-only patch.
- `artifacts/t04-cross-revision-operational-mode/test_root_mode_compat.py` (SHA-256 `1DB14115D9359E708334720C850535F990EE01E63FE02BBB9591DDAF5044E7C2`) is a no-copy cross-revision probe: it loads the root module (`19EDE1E62C79E160D41F47FE5BB05F0EA3048988E4A9E00C1DA8C03353667F85`) in memory, drives the T04 client through the real HTTP route, and checks maintenance refusal using fresh temporary state. It passed the AST check and its approved selector below; any pass is cross-revision compatibility evidence, not integration/release acceptance.

## T04 plan coverage map

Plan source: `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md`, T04 section (lines 165-175 in this candidate).

| Plan item | Current evidence | State |
|---|---|---|
| Daemon-off MCP fallback | `tests/test_mcp_compact_transport.py::test_mcp_status_remains_usable_when_hub_daemon_is_offline` | Structured MCP text response, no spawn, and no state-directory creation asserted; earlier focused run. |
| Conversation continuation: next turn, expired ID, competing turn | `tests/test_conversation_continue_route_contract.py::test_hub_client_continues_through_production_route_and_preserves_transcript`, `::test_expired_conversation_is_terminal_through_production_route`, `::test_competing_continuation_is_retryable_in_progress_through_production_route` | Covered; these selectors were in earlier broad candidate run, which had one unrelated delegate-test failure. |
| `/api/chat/completions` supported or explicitly unsupported | `tests/test_t04_public_api_contracts.py::test_unsupported_chat_completions_rejects_valid_payload` plus invalid payload selectors | Unsupported/404 contract explicitly tested. |
| Advertised artifact list | `ArtifactStore.list()` hashes the supplied tenant and filters `tenant_identity` in both active schema branches (`artifacts` and `artifacts_v2`); `tests/test_t04_public_api_contracts.py::test_artifact_list_v2_hashes_and_isolates_tenants`, `::test_artifact_list_legacy_hashes_and_isolates_tenants`, and `::test_artifact_list_is_bounded_metadata_and_needs_no_id` | The approved narrow behavior is already in `HEAD`; `get()` remains unchanged. Existing tests cover per-schema isolation plus bounded metadata, order, and the 100-row cap. |
| GET/POST `resolve_imports`, `include_code`, semantic diff route | `::test_resolve_imports_get_and_post_share_auto_default`; `tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code`; `tests/test_t04_public_api_contracts.py::test_semantic_diff_action_uses_public_call_graph_diff_route` | Contracts covered; earlier broad run. |
| Response controls, RAG descriptions, review/diff delivery, work controls | `test_lean_rag_description_lists_every_supported_action`, `test_lean_work_description_lists_continuation_and_response_controls`, `test_repo_review_diff_returns_foreground_result_by_default` | Contracts covered; earlier broad run. |
| Request IDs, retry safety, path hints, connection resilience | `tests/test_client_transport.py`, `tests/test_client_path_hints.py`, `tests/test_client_startup_resilience.py` | HubClient supports explicit request IDs. T07 now has optional `local_ai_task(submit)` ID passthrough in its candidate; focused owner batch passed 17 tests. T04 branch does not yet contain that hunk; T07 full acceptance/handoff remains pending. T04 will not edit it. The 16 direct-client transport selectors passed; T21 confirms they contain no path-hint assertions, so separate T21 evidence remains required. |

## Current receipts

- Compatibility selectors, current `client.py` SHA above, one combined run: `5 passed in 1.99s` (not five independent runs):

  ```text
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_runtime_hardening.py::test_client_does_not_spawn_when_hub_port_is_already_owned tests/test_runtime_hardening.py::test_client_cleans_failed_start_lock_write tests/test_runtime_hardening.py::test_client_does_not_bypass_live_managed_supervisor tests/test_runtime_hardening.py::test_client_does_not_direct_spawn_during_managed_restart tests/test_sse_events_stream.py::test_client_stream_events_parsing
  ```

- Startup/real-HTTP candidate set: `4 passed in 8.37s`:

  ```text
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py::test_recent_empty_start_lock_is_treated_as_in_progress tests/test_client_startup_resilience.py::test_concurrent_offline_requests_share_one_startup tests/test_mcp_compact_transport.py::test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload tests/test_client_startup_resilience.py::test_readiness_timeout_terminates_only_owned_child_and_cleans_lock
  ```

  The test stubs `Popen` and `operational_mode`; it proves local HTTP routing/payload behavior, not real process launch or real-module acceptance.

- Daemon-off status + timeout cleanup + synthetic active-mode autostart receipt from earlier focused run: `4 passed in 7.48s`:

  ```text
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_compact_transport.py::test_mcp_status_remains_usable_when_hub_daemon_is_offline tests/test_client_startup_resilience.py::test_readiness_timeout_terminates_only_owned_child_and_cleans_lock tests/test_client_operational_mode_autostart.py::test_ensure_server_autostarts_for_active_or_missing_mode
  ```

  This verifies structured offline MCP failure and no spawn, not successful remote task execution while the daemon is off.

## Cross-worktree safety dependency

- T03 candidate `HEAD 49008c8f104ea569dffc60e2f36f6eb62b92a57e`, client SHA-256 `16E9F55A0E6A353C5F6292C77F7310C082BD28DFD4E2E1C54AEBDF6BC1EED1F4`, autostart test SHA-256 `14A2C47E580EB1F1CC050D09D5AE8B96D381B0869C79FBE3B66D97E8D87231FC`. Four updated lock regressions passed (`4 passed in 3.11s`); Bugbot reported no further issue. T03 slot released. Code remains in separate worktree, not reconciled into T04.
- T04's two stale-lock cleanup sites check `_live_start_lock()` and then unlink by path without guarding the identity of the file being removed. A concurrent owner can replace that path between check and unlink, so T04 can remove another owner's new lock; its PID + age rule also does not detect PID reuse. T03's process-identity sidecar and guarded transitions address this dependency, but must be reconciled from the tested, reviewed T03 owner change before T04 can claim safe process ownership.
- Do not copy T03 code into T04 yet. T04 acceptance remains partial until the tested T03 revision is explicitly reconciled into the candidate, followed by T04 lock/process-owner checks. The approved root-module probe passed as cross-revision compatibility only; it does not close process-ownership acceptance.

- `git diff --check` passed; AST parse passed for 12 Python acceptance/source files. `/api/context/pack` is absent from the diff.
- Earlier 146-test candidate run was `146 passed, 1 failed` before the Popen monkeypatch was isolated. No broad rerun was authorized after that correction.
- The sole earlier failure was the real-HTTP delegate test's process-count assertion; subsequent focused runs identified and fixed test-only global `subprocess.Popen` interception, and the 4-test startup set passed. This does not replace a later broad acceptance run.
- Approved cross-revision probe, after correcting its expectations for the contract-wrapped prompt and HTTP-normalized payload (`max_tokens=160`, `latency_budget_ms=1500.0`): `1 passed in 6.71s`.

  ```text
  python -B -m pytest -q -p no:cacheprovider --tb=short artifacts/t04-cross-revision-operational-mode/test_root_mode_compat.py::test_t04_client_gate_and_http_route_with_actual_root_operational_mode
  ```

  Hash guards confirmed the T04 client SHA-256 above and the root `operational_mode.py` SHA-256 above. The probe uses the actual root module in memory, a real local HTTP route, and temporary state; it stubs the client's `Popen`, so OS child launch/ownership is not proven. Slot released to the coordinator after the run.

- User-approved native rerun of 16 transport selectors passed in two groups. Connection/replay safety: `9 passed in 1.91s`.

  ```text
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_reuses_one_http11_connection_for_sequential_requests tests/test_client_transport.py::test_client_coalesces_simultaneous_identical_requests tests/test_client_transport.py::test_client_reconnects_on_idle_disconnect tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_transport.py::test_client_does_not_replay_ambiguous_default_post tests/test_client_transport.py::test_client_does_not_coalesce_identical_mutating_posts tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_not_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown
  ```

  Request-ID/route retry: `7 passed in 1.95s`.

  ```text
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_replays_explicitly_safe_post_with_stable_request_id tests/test_client_transport.py::test_post_does_not_replay_unclassified_mutation tests/test_client_transport.py::test_post_does_not_replay_file_writing_generate_types tests/test_client_transport.py::test_post_replays_allowlisted_read_only_route tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_safe_posts_with_distinct_explicit_request_ids_do_not_coalesce
  ```

  Tested T04 client SHA-256 `F0C3DDC837A509743D0795E7BE2DEE10840C80FD141FE64365C92A30F9CE86CF`; test file SHA-256 `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`. T21 confirms these selectors do not test path-hint behavior; separate T21-owned hint selectors/evidence remain open.

  T03 four-test batch completed before T04's two groups; T04 then explicitly released slot to coordinator. No further T04 tests ran.

## Safe-transfer decision

No full `client.py` diff is safe to transfer as T04-only. Clear T04-owned implementation is thread-local connection pooling and HTTP transport (`client.py:115-208`). Bounded startup/readiness code (`304-310`, `396-433`) is T04-owned only inside shared `ensure_server()`; extract after removing T13 mode gate and reconciling T03 lock semantics. Transport error/status normalization (`211-258`) and retry timeout flow (`462-625`) remain T04/T07 shared hunks, not owner-only patch candidates.

Overlap boundaries: `request()` (`462-590`) mixes T04 transport with T07 explicit-ID validation, replay and single-flight; `post()` (`675-710`) mixes T07 replay classification with T21 path-hint shaping. Mode gate (`314-323`) depends on T13. SSE client/event contract (`978-995`) crosses T08. Lock helper/check/unlink behavior (`65-94`, `348-395`) needs the tested T03 revision before T04 can claim process safety. T07 candidate is clean at `457bf1e`, client SHA-256 `442C66D6B33E216B1E7DEEDDE119B99FC6A7E5CF9A15E9B6CB1AF01FD3F3ADBF`; its request-ID changes touch same methods as T04. T21 owner reports its submit request-ID hunk is separate from path hints; path-hint ownership remains T21. No whole-file transfer or root integration authorized.

T07 caller-ID pass-through is in a separate working diff at T07 base `457bf1eb25ae52ed1cab2acdb0847670f7e026e8`: `mcp_server.py` SHA-256 `61D4A68E0E530F73DCC1C005DB76FD8F11696808DB85211365F0F8C55EDBEE32`; route adds optional `request_id` and passes it to `CLIENT.post('/api/async-jobs', ..., request_id=request_id or None)`. Owner reports 17 focused request-ID/replay selectors passed in 4.22s. This proves T07 candidate behavior only; T04 candidate still lacks caller-to-MCP passthrough. T07 full-scope review/handoff remains outstanding.

T07's exact two-hunk MCP pass-through is preserved as `artifacts/t07-submit-request-id-pass-through-to-t04.patch` (SHA-256 `CFE092E17AFBFD8B4EA551C51E0E748BE9B55673ACEF0B8BA5BEA419C2659EC6`). `git apply --check` passed against current T04; patch was not applied. T07 owner command/result:

```text
python -B -m pytest -p no:cacheprovider --tb=short -q -c pyproject.toml tests/test_command_replay_policy.py tests/test_mcp_agent_routing.py::test_async_task_submit_reuses_explicit_request_id tests/test_mutation_replay.py::test_direct_async_submit_carries_caller_request_id tests/test_mutation_replay.py::test_http_retry_replays_outcome_and_rejects_changed_payload tests/test_mutation_replay.py::test_http_retry_from_two_clients_dispatches_once tests/test_mutation_replay.py::test_http_retry_from_two_live_clients_dispatches_once
=> 17 passed in 4.22s
```

## T03 lock-only reconciliation candidate (not applied)

To unblock T04 safe-start ownership review without transferring T03's unrelated client changes, an owner-scoped candidate patch was generated from the tested T03 worktree `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub` (HEAD `49008c8f104ea569dffc60e2f36f6eb62b92a57e`, client SHA-256 `16E9F55A0E6A353C5F6292C77F7310C082BD28DFD4E2E1C54AEBDF6BC1EED1F4`). It isolates `process_identity`/`terminate_tree` imports, lock helpers/guard functions, and the `ensure_server()` lock/start/release block. T04 HTTP transport and request/retry code are not in the candidate.

Candidate: `artifacts/t03-start-lock-only-to-t04.patch`, SHA-256 `26B2F25E213A39C8377986C58E70D1D33EC53C320B6AE60B649A82175E60A0CA` (366 lines). `git apply --check` passed against T04 HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`; patch is now applied in the assigned T04 worktree only. Its T03 source hash `16E9F55A0E6A353C5F6292C77F7310C082BD28DFD4E2E1C54AEBDF6BC1EED1F4` and test hash `14A2C47E580EB1F1CC050D09D5AE8B96D381B0869C79FBE3B66D97E8D87231FC` match the tested T03 checkout. Exact T03 command: `python -B -m pytest -q -p no:cacheprovider --tb=short --rootdir . --confcutdir . tests/test_mcp_autostart.py::test_partially_published_start_lock_sidecar_stays_live tests/test_mcp_autostart.py::test_aged_start_lock_is_kept_while_launcher_identity_matches tests/test_mcp_autostart.py::test_dead_daemon_sidecar_overrides_live_launcher_identity tests/test_mcp_autostart.py::test_timeout_keeps_lock_while_unreaped_child_is_alive` => `4 passed in 3.11s` at HEAD `49008c8f104ea569dffc60e2f36f6eb62b92a57e`. These four regressions were copied into T04 `tests/test_client_startup_resilience.py` for an assigned-worktree rerun. After application, T04 `git diff --check` and AST parsing for client + startup tests passed; T04 test selectors have not yet run on the patched source, so the T03 receipt is supporting provenance, not T04 integration proof. At patch application, T04 client SHA-256 was `9EDA95831DB60EFF4828604207FBFD11083BAAC026984E131DE78C0E670CEF54`; startup test SHA-256 was `7C2DB9111E320ED8C803ED9FC33DDCA816CA419DE8675366EF129209DA3C850A`. Current shared test slot is assigned to T07 after T15 completes; T04 has no fresh assignment and did not start pytest.

## Artifact list approval reconciled against T04 current state

The approved legacy tenant filter is already present in the current T04 tracked `src/local_ai_hub/artifacts.py`: both `artifacts_v2` and legacy `artifacts` tenant-scoped SELECTs filter `tenant_identity=?` with the existing SHA-256-derived `tenant_identity`; `LIMIT ?`, descending `created_at`, and metadata projection remain intact. `ArtifactStore.get()` was not changed, and `git status --short -- src/local_ai_hub/artifacts.py` is clean. The saved two-line patch `artifacts/t04-minimal-artifact-list-legacy-tenant-filter.patch` targets the separate root/master base blob recorded in its manifest; `git apply --check` fails against T04 because that code already contains the intended filter. No patch was applied here. The T04 plan records three artifact-list regressions passing (`bounded metadata`, `v2 tenant isolation`, `legacy tenant isolation`, 5.43s); this turn did not rerun them because T04 has no shared test-slot assignment.


## Follow-up review: exact child ownership

Review of T03's timeout path found it called `terminate_tree(process.pid)` after `Popen.poll()`. On Windows that helper falls back to `taskkill /PID`; a process can exit and its PID be reused between the poll and kill, so that does not prove exact child ownership. T04 now keeps a bounded `_stop_owned_child(Popen)` helper and uses the retained `Popen` handle to terminate/wait/kill only the child started by this attempt; if the handle still reports it alive, the nonce sidecar and lock remain. Added/retained T04 regression `test_timeout_keeps_lock_while_unreaped_child_is_alive`; existing `test_readiness_timeout_terminates_only_owned_child_and_cleans_lock` covers the exact-handle cleanup path. `git diff --check` and AST parse passed after these edits. These T04 tests have not yet run on the current source. Current hashes: `src/local_ai_hub/client.py` `BAF0C769F0F7A0536F5A9E2A1CE9CF5606275AFFF42D674AFC25C855A6664261`; `tests/test_client_startup_resilience.py` `4D9B182FAB4414FBA9AEF72497DBECB6B6028CE5F4BF5E911253AD28B6E03F91`. No pytest was launched: root coordinator reports T15 measuring and T07 next for the shared slot.

## HTTP probe hash guard

Updated `artifacts/t04-cross-revision-operational-mode/test_root_mode_compat.py` to require current `client.py` SHA-256 `BAF0C769F0F7A0536F5A9E2A1CE9CF5606275AFFF42D674AFC25C855A6664261` after lock reconciliation and exact-handle cleanup review. Probe syntax passed; its earlier `1 passed` receipt belongs to old client hash `F0C3...` and is historical only. Rerun this real local HTTP payload/result probe at the updated hash when assigned the shared test slot.

The readiness-timeout `Child` test double now marks itself exited after a successful `wait()`. Its previous `poll()` always returned `None`, contradicting the reap result and the new rule to retain a lock for a still-live child. Updated test-file hash is `4D9B182FAB4414FBA9AEF72497DBECB6B6028CE5F4BF5E911253AD28B6E03F91`; AST parse and `git diff --check` pass, no pytest rerun yet.

## Current T04 state audit (2026-09-30)

- Branch/HEAD: `codex/t04-integration-2b33602` / `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Current `client.py` SHA-256: `8EED9005A1374F48CD6FDC4738FE42985AB00FF2E20EDEFDB1F9D06E003759B5`; current `mcp_server.py`: `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`.
- Current regression hashes: `test_client_path_hints.py` `5610A0AABB5CB7A236B15C9A53EEC983188F18ADF6839B3584C09A6E5DA6608F`; `test_mcp_agent_routing.py` `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`.
- Static checks: AST parse passed for `mcp_server.py` and `test_mcp_agent_routing.py`; `git diff --check` passed with existing LF/CRLF warning. No T04 pytest ran at these hashes.
- T07 caller-to-MCP `request_id` hunk is integrated from candidate commit `3383499633f55bd202d9c270c24957706ed3fed1`; T04 includes `test_async_task_submit_reuses_explicit_request_id`. Test remains pending.
- Client path hints serialize only for `/api/search`; explicit `path` takes precedence. T21 MCP repo-search adapter/runtime proof remains separate. `/api/context/pack` source was not edited.
- `ArtifactStore.list()` already filters by hashed `tenant_identity` in both schema branches and preserves limit/order/metadata. `artifacts.py` is clean; prior T04 list regressions remain tied to unchanged source.
- T13 owner reports its 100-test suite finished and says slot is free. Coordinator's latest serialized queue is T06, then T13, then T04, then T07. T04 has no assignment; do not start pytest before explicit handoff.
- No root/master files changed.

## Next assigned validation sequence

Run only after explicit T04 slot handoff. Current HEAD remains `3658d5056354849ddf17883ed04f807f16cc44c1`:

1. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_reuses_one_http11_connection_for_sequential_requests tests/test_client_transport.py::test_client_coalesces_simultaneous_identical_requests tests/test_client_transport.py::test_client_reconnects_on_idle_disconnect tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_transport.py::test_client_does_not_replay_ambiguous_default_post tests/test_client_transport.py::test_client_does_not_coalesce_identical_mutating_posts tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_not_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown`.
2. Run the second seven-selector command in `Exact 16 direct-client transport selectors`.
3. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_agent_routing.py::test_async_task_submit_reuses_explicit_request_id`.
4. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py tests/test_client_path_hints.py tests/test_client_operational_mode_autostart.py tests/test_mcp_compact_transport.py::test_mcp_status_remains_usable_when_hub_daemon_is_offline tests/test_mcp_compact_transport.py::test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload`.
5. `python -B -m pytest -q -p no:cacheprovider --tb=short artifacts/t04-cross-revision-operational-mode/test_root_mode_compat.py::test_t04_client_gate_and_http_route_with_actual_root_operational_mode` (guard requires current `client.py` hash `8EED...`; the probe stubs OS `Popen`).

T21 MCP path-hint acceptance remains a separate dependency. Do not claim it from T04 client tests.

T07 caller-to-MCP request-ID integration is still owner-controlled and not applied. Revalidated now: `git apply --check -- artifacts/t07-submit-request-id-pass-through-to-t04.patch` passes against the current T04 worktree. Patch SHA-256 remains `CFE092E17AFBFD8B4EA551C51E0E748BE9B55673ACEF0B8BA5BEA419C2659EC6`; current T04 `mcp_server.py` SHA-256 is `F7EE15C8DCEDD7C9F21E3F1FD4EB684DD88F68D2AB72C68FAE1332AF62702E24`; T07 owner file SHA-256 remains `61D4A68E0E530F73DCC1C005DB76FD8F11696808DB85211365F0F8C55EDBEE32`. The T07 owner-reported 17-test receipt belongs to that T07 candidate only.


## Path-hint route-scope review (2026-09-30)

T04 initially forwarded explicit `path_hints` to both `/api/search` and `/api/command`. T21's current owner scope only releases `local_ai_repo(action="search")` / `/api/search`; command and context-pack are outside it. Narrowed `HubClient.post()` to forward hints only when `route == "/api/search"`; updated T04 tests to assert command receives the unchanged payload and moved the retry/path-hint startup regression to `/api/search`. The `/api/context/pack` assertion remains a preservation check; that implementation is untouched. This work is static-only until a slot is assigned. Current hashes: `client.py` `8EED9005A1374F48CD6FDC4738FE42985AB00FF2E20EDEFDB1F9D06E003759B5`; `tests/test_client_path_hints.py` `BACF56621E171C9F2EE1D06D96BCC27C96205C16333442D0265DD596F2F397C1`; `tests/test_client_startup_resilience.py` `C830B9FCEDA60B72AEF18B3D782FB7F25928105F94C3EF148B32AC4F177273A7`. Updated the cross-revision probe hash guard to `8EED...`; AST and `git diff --check` pass, pytest not run.

## Read-only T21 path-hint dependency check

The T21 conversation is attached to the empty `worktrees/4294` path, but a separate actual Git checkout exists at `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub` (HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`). Read-only status shows modified `project_config.py` and `mcp_server.py`, plus untracked `tests/test_mcp_repo_path_hints.py`. Its MCP candidate accepts `path_hints` on repo search and calls the API client with those hints; its three candidate tests cover repo-search shaping and `/api/search` route forwarding. No tests were run and no T21 files were changed. This proves a candidate exists, not integration or acceptance; keep T21 test/runtime proof open until its owner validates and hands it off.

Latest bounded wait still shows T15 candidate session `90018` active and slower than baseline; no T04 test slot is assigned. T04 source/static changes remain as recorded above.

## Shared-slot status correction

The latest authoritative `wait_threads` event now shows T15's benchmark turn **completed** and its thread idle (the final report contains paired benchmark results); T15 states it released the slot to T02. T02's latest note says it cannot confirm the slot free because its earlier read still showed the benchmark active, and it has not launched tests. Root coordinator has not assigned T04 the slot. Therefore T04 still must not run pytest until an explicit fresh assignment; previous note saying T15 session `90018` was active is superseded by this event.

## Current validation queue (2026-09-30)

T15 is now terminal/idle. T06's thread is currently active, reviewing a process-group identity regression; T07 reports the single test slot is still held by T06 and is waiting to run its focused acceptance. T02's earlier note also did not confirm the slot free. No fresh assignment names T04, so keep T04 tests pending and do not launch them yet.

## Validation queue update

T07's latest owner report says its focused request-ID policy suite passed (`21 passed`) and its full assigned acceptance is now running after T15 released. T06 is next after T07; its current thread is doing source review without tests. T21's thread confirms its valid checkout is `t21-project-config`; it is restricted to its core resolver/schema and T21-owned tests, with consumer adapters remaining under their owners. T04 has not received a slot. No test command launched from this worktree.

## Current slot reassignment and T07 update

Latest coordinator/T02 messages now explicitly assign the shared test slot to T02. T07's full run returned `247 passed, 1 skipped, 1 failed`; the remaining failure is `tests/test_mutation_replay.py::test_repair_loop_requires_explicit_validation_replay_safety`, which T07 says contradicts the user-selected policy and is updating. T07 plans a focused rerun only after T02 releases the slot. T04 still has no assignment and must wait; no T04 tests ran.

## Queue recheck

Current owner messages still assign the single shared test slot to T02. T07 reports its focused suite at `21 passed`; its full acceptance has one unresolved failure at `tests/test_mutation_replay.py::test_repair_loop_requires_explicit_validation_replay_safety` and is awaiting a corrected assertion plus a new slot. T06 remains ahead of T04 in the coordinator's queue. T04 source hashes are unchanged from the preceding section; no pytest started here.

## T07 request-ID dependency update

T07 owner reports correcting the lone full-run failure by renaming the stale test to `test_repair_loop_honors_explicit_unsafe_validation_replay_safety` and setting its classifier fixture `replay_safe: false`. Their full rerun is waiting for T02 to release the slot. This change is outside T04; the earlier `t07-submit-request-id-pass-through-to-t04.patch` remains an apply-ready but owner-controlled MCP integration candidate. T04 has no slot assignment.

## Latest shared-slot observation (2026-09-30)

T02 still owns the single shared test slot. Its owner reports running 25 repetitions of `tests/test_benchmark_suite.py` followed by `tests/test_surface_benchmarks.py`, then one reverse-order control run. T02 confirmed T07's earlier pytest process exited and found no matching process. T04 has no assignment; no T04 pytest launched.

## Static acceptance review (client SHA-256 `8EED9005A1374F48CD6FDC4738FE42985AB00FF2E20EDEFDB1F9D06E003759B5`)

Reviewed `HubClient.post()` and `request()`: request IDs are preflight-validated and reused in retry headers; non-replay-safe POSTs retry only after proven pre-send connection refusal when autostart is enabled; uncertain post-send transport failures return uncertainty. Explicit path hints are shaped and forwarded only for `/api/search`, with explicit `path` taking precedence. Startup retains the owned `Popen` handle for timeout cleanup and guarded lock ownership. Static review only; current-source acceptance tests and real HTTP probe remain pending.

## Static reviewer finding and fixture correction

An independent read-only review found `test_post_caps_path_hints_and_drops_unlisted_fields` sent its request to `/api/command` while asserting that route received path hints. The implementation intentionally permits hints only on `/api/search`, so the test indexed a missing `path_hints` key. Corrected that fixture to call `/api/search` with a query payload. Current test file SHA-256: `5610A0AABB5CB7A236B15C9A53EEC983188F18ADF6839B3584C09A6E5DA6608F`. AST parse and `git diff --check` pass; pytest remains pending shared-slot assignment.

## Queue advance (2026-09-30)

T02's 25-run sequence is terminal. All three repetitions failed the same queue cancel expectation (`cancel()` returned `running`, expected `cancelled`); T02 did not run its reverse-order control and released the slot. The coordinator assigned the slot to T07 next. T07 reports starting its focused rerun. T04 remains queued and has not run pytest.

## T07 dependency status (owner report, 2026-09-30)

T07 reports its corrected focused run passed 22 tests and its wider acceptance passed 248 tests with 1 POSIX test skipped. T07 is checking its final diff before handing off the request-ID candidate and shared slot to T06. This is not T04 verification. The apply-ready patch `artifacts/t07-submit-request-id-pass-through-to-t04.patch` remains unapplied pending the owner handoff; T04 still has no slot.

## T07 handoff and queue (2026-09-30)

T07 reports completion at candidate commit `3383499633f55bd202d9c270c24957706ed3fed1` on `codex/t07-retries-idempotence-20260930`, with 248 passed/1 skipped in its wider suite and 22 passed in its focused suite. T07 released the shared slot to T06. The T07 change remains a separate candidate; its caller-to-MCP request-ID hunk is not yet integrated in T04. T04 has no slot assignment.

## Exact 16 direct-client transport selectors

Run as two groups after T04 receives slot:

1. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_reuses_one_http11_connection_for_sequential_requests tests/test_client_transport.py::test_client_coalesces_simultaneous_identical_requests tests/test_client_transport.py::test_client_reconnects_on_idle_disconnect tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_transport.py::test_client_does_not_replay_ambiguous_default_post tests/test_client_transport.py::test_client_does_not_coalesce_identical_mutating_posts tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_not_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown`
2. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_replays_explicitly_safe_post_with_stable_request_id tests/test_client_transport.py::test_post_does_not_replay_unclassified_mutation tests/test_client_transport.py::test_post_does_not_replay_file_writing_generate_types tests/test_client_transport.py::test_post_replays_allowlisted_read_only_route tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_safe_posts_with_distinct_explicit_request_ids_do_not_coalesce`

Earlier receipts are 9 passed + 7 passed at client SHA-256 `F0C3...`; they must be rerun at current SHA-256 `8EED...`.

## T06 validation queue (2026-09-30)

The coordinator confirms the shared pytest slot is assigned to T06. T06's first targeted run of `tests/test_command_rollback.py tests/test_cache_invalidation.py tests/test_command_timeout_cache_contract.py tests/test_auxiliary_action_policy.py tests/test_daemon_lifecycle_hardening.py tests/test_process_utils.py` ended with `exit_code=1` and multiple failures; T06 is checking the completed process and triaging. T07 also has a separate static-review P2 follow-up on replay-safety defaulting. T04 has no assignment and has not run pytest.

## T07 caller request-ID hunk integrated (2026-09-30)

Applied the owner-scoped patch `artifacts/t07-submit-request-id-pass-through-to-t04.patch`, derived from T07 candidate commit `3383499633f55bd202d9c270c24957706ed3fed1`. Added `request_id` to the public `local_ai_task` schema and forwarded it to `CLIENT.post()` for async-job actions. Ported T07's exact regression `test_async_task_submit_reuses_explicit_request_id` into T04 `tests/test_mcp_agent_routing.py`; it checks public signature/schema and two identical submit retries reaching `/api/async-jobs` with the same ID. Patch SHA-256: `CFE092E17AFBFD8B4EA551C51E0E748BE9B55673ACEF0B8BA5BEA419C2659EC6`. Current source/test SHA-256: `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`; `test_mcp_agent_routing.py` `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`. AST parse and `git diff --check` pass. No T04 pytest yet; shared slot is assigned to T06. T07's separate replay-safety P2 review remains outside this hunk and must be resolved by its owner.

## T04 authorized validation and slot handoff (2026-09-30)

Current worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`. User authorized native reruns and the narrow artifact tenant filter; HUB remains unavailable and was not used.

- Direct transport selectors: 9 passed, then 7 passed. Logs: `artifacts/t04-transport-group-1.log` SHA-256 `BCB437BD93DE15949A9E194977AE7AE3EC0714C5C0F85F5AF20D54D63339B735`; `artifacts/t04-transport-group-2.log` SHA-256 `68797372198E140A1A3DD60E3F0089CE581946840CDEA20FDA6307D319F07F78`.
- Integrated T07 explicit request-ID MCP regression: 1 passed. `artifacts/t04-request-id-mcp.log`, SHA-256 `6BB56A36788EDF8A42305A477E440EF55067665A3F1DFF8D14B1A800D2C38792`; current source/test SHA-256: `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`, `test_mcp_agent_routing.py` `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`.
- Initial startup/path-hint/MCP integration batch: 22 passed, 2 failed because active/missing-mode startup mock reported online before mocked `Popen`. Corrected test fixture only; targeted mode cases 2 passed, then combined integration rerun 24 passed. Logs: `artifacts/t04-operational-mode-retest.log` SHA-256 `407E59645AE920F4CB153FFD05EB24E56E92D9C8BD4FA68EE2E254AC25B2FA84`; `artifacts/t04-startup-pathhints-mcp-retest.log` SHA-256 `1FBF7A6646A8D68BEC9F2C7A72F8958ED3EFE592569FC542872A3B5EB86B515E`. Current path-hints fixture SHA-256 `5610A0AABB5CB7A236B15C9A53EEC983188F18ADF6839B3584C09A6E5DA6608F`; autostart fixture SHA-256 `EF9F7A51DC2B4913B396CCBD3D62D4B848A7EBABF39CE943E33F92759398172A`.
- Real local HTTP payload/result plus actual root operational-mode module probe: 1 passed in 7.34s; client `Popen` stubbed, so OS process launch remains unverified. Log `artifacts/t04-cross-revision-http.log`, SHA-256 `E8F98C63CAF0DB3A5D7A9AC270204BAF6BAF5CCE386A05D8AC7BB087EC0DE9D9`.
- Full assigned affected suite command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py tests/test_mcp_agent_routing.py tests/test_mcp_compact_transport.py tests/test_runtime_hardening.py tests/test_sse_events_stream.py tests/test_client_startup_resilience.py tests/test_client_path_hints.py tests/test_client_operational_mode_autostart.py` => `128 passed, 1 failed in 19.95s`. Log `artifacts/t04-full-assigned-suite.log`, SHA-256 `2CBA2062DBA9140C49DBBC4274CA32BFF94ED95517A596375A98795F7AE2F3DA`.
- Sole failure is unrelated preprocessor test `tests/test_runtime_hardening.py::test_registry_repair_reactivates_the_selected_project`; exact isolated selector already ran while T04 held slot and failed (`1 failed in 0.32s`), log `artifacts/t04-registry-repair-baseline.log`, SHA-256 `CDC75F10D00DCEC586325573E3FAEF39ED692FB4FE162A20A1B732FA26DD2CEC`. Do not repeat identical selector. Fixture uses `ProjectPreprocessor.__new__`, omits runtime locks, and inserts two nonexistent project roots. `_repair_registry()` takes invalid-root branch and calls `_forget_project_runtime()`, which accesses missing `_dirty_lock`; broad exception handler swallows error before commit. `preprocess.py` is unchanged from HEAD; diff in `test_runtime_hardening.py` is limited to four timeout-aware `_online(*_args)` fixture updates. `git blame` attributes failing test and repair path to baseline `ee0a2cb7f91e4df24378fdc2da74450a6091344c`; keep fix with preprocessing owner, outside T04.
- Earlier 22/2 is superseded by corrected fixture-only 24-pass rerun. `git diff --check` passed; `/api/context/pack` untouched. Remaining limits: real child launch/process ownership still needs proof against reconciled T03 code; T21 adapter/runtime proof remains separate; T07 replay-safety P2 remains owner-controlled.
- T04 explicitly releases shared test slot to T06 after this receipt. T20 coordinator informed with exact selector, root-cause evidence, logs, and handoff. T04 full suite is not all-green because of unrelated baseline preprocessor failure.

## Current T04 plan and objective audit (2026-09-30)

Plan checked at `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md:165-175`; implementation hashes unchanged from previous validation: `client.py` `8EED9005A1374F48CD6FDC4738FE42985AB00FF2E20EDEFDB1F9D06E003759B5`, `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`, `artifacts.py` `7F598EE33012F3990CE6792D32EC2C125E12BBD113F0DF2B1A75C11C91ABB5B1` (clean vs HEAD).

| Requirement | Current evidence | Verdict |
|---|---|---|
| Plan 169, public conversation continuation through HubClient/service, next turn, expired ID, concurrent turn | Receipt lines 42 lists three production-route selectors; prior candidate-wide run only. Latest 128-test assigned suite omitted those selectors. | Prior evidence exists; current candidate needs scoped rerun. |
| Plan 170, `/api/chat/completions` contract | Receipt lines 43 lists explicit unsupported/404 regression. Latest assigned suite omitted public API contracts. | Prior evidence exists; current candidate needs scoped rerun. |
| Plan 171, advertised artifact list | Current `ArtifactStore.list()` hashes tenant, filters both schema tables, caps at 100, orders descending, projects metadata only (`artifacts.py:545-564`); source clean vs HEAD. Three listing selectors previously passed per receipt line 44. | Source and prior test evidence align; no T04 change needed. |
| Plan 172, resolve_imports, include_code, semantic diff | Latest MCP test passed `include_code`; receipt line 45 records earlier coverage for GET/POST resolve_imports and semantic-diff route. | Partial current evidence; rerun remaining public API selectors. |
| Plan 173, response controls, RAG descriptions, review/diff, work controls | Receipt line 46 records prior candidate-wide coverage. Latest assigned suite did not include those broad API contract files. | Prior evidence exists; current candidate needs scoped rerun. |
| Objective: 16 retry/request-ID transport selectors | 9 + 7 current-client selectors passed; MCP caller request-ID regression passed 1. Logs and hashes in prior section. | Passed on current candidate. |
| Objective: path hints and resilience | Path-hint serialization/route filtering, concurrent startup, readiness timeout, unavailable executable, and operational-mode cases passed in latest 24-test group; full assigned suite covered 128 tests. | Client side passed; T21-owned repo adapter contract/runtime proof remains unverified and code scope is not released. |
| Objective: daemon-off fallback, bounded autostart, process ownership | Offline MCP status path, no-spawn behavior, bounded readiness, owned-child cleanup, startup-lock regressions covered by latest runs. Tests stub process creation. | Unit/integration checks passed; real OS child launch not verified. |
| Objective: actual HTTP payload/result match | Real local HTTP route and payload/result probe passed 1 test against actual root operational-mode module; client's `Popen` was stubbed. | HTTP evidence passed; actual child launch/runtime remains unverified. |
| Full assigned suite | 128 passed, 1 unrelated preprocessor fixture failure; isolated selector reproduces it. | Not all-green; failure handed to T20 for preprocessing owner. |

Next required shared-slot work: rerun T04 public API/conversation selectors on this exact candidate; run any current T21 adapter regression only after T21 releases its consumer scope; perform approved process runtime check if environment supports it. T06 currently active in shared slot; T07 and T21 still queued. No tests started in this turn.

## Coordinator and dependency corrections (2026-09-30)

T20 later assigned the unrelated registry-repair failure to T10 for audit/fix. T04 must rerun its full assigned suite only after T10's targeted selector passes and a shared slot is assigned. T06 currently owns the slot; T20 reports T06's full suite has four failures under diagnosis. No T04 tests started in this continuation.

T04 source tree does not contain `src/local_ai_hub/operational_mode.py`; `client.py::HubClient.ensure_server()` imports it before attempting `Popen`. T04 autostart tests inject a stub, and the cross-revision HTTP probe loads actual root mode code in-process while still stubbing `Popen`. T13's separate candidate has untracked `operational_mode.py`, HEAD `6050c41ce5510a6de3eaeb674a180560ea404f24`, SHA-256 `3A083FA9DFF1B42E634B434ECAB8519916EBDC825579920CCF448B84AEC8F145`; no owner handoff exists, so it was not copied. Actual T04 child-launch acceptance needs an authorized T13 module handoff into this worktree first. Root remains untouched.

## Latest queue update (2026-09-30)

T20 assigned T10 to repair the invalid project-root fixture by creating both directories while keeping assertions unchanged. T10's exact selector has not yet passed. T06 currently runs its final six-file suite after its own fixes. T04 must not rerun its 128/1 suite until T06 releases and T10's selector passes. No T04 tests started in this continuation; no T10-owned files changed here.

## T06 latest slot observation (2026-09-30)

T06 reported its final six-file suite after fixes: `155 passed, 6 skipped, 48.15s, exit 0`. At this observation it was saving hashes/diff-check and had not explicitly released the slot. T10's corrected fixture selector remains pending. Root coordinator requested T13 provide exact owner-reviewed `operational_mode.py` source/dependency/test receipt and explicit handoff; T04 will not copy before handoff. Next T04 work is current-candidate public API/conversation rerun plus actual child-launch/API test after both dependencies are satisfied.

## Explicit next-slot assignment (2026-09-30)

T20 confirms T06 released slot to T10. T10 now owns exact `test_registry_repair_reactivates_the_selected_project` selector; T04 must not run it. After T10 passes and explicitly releases, T04 owns the next slot for its exact full assigned suite, with final exit/count/log hash and explicit release required. T04 has not started that rerun. T13 module handoff remains separately pending; no source was copied.

## T10 targeted selector receipt (2026-09-30)

T20 reports T10's exact registry-repair selector passed once: `1 passed / 0.39s`, log SHA-256 `7148718990D7EA797310A566F73839AFC086A66A233D8B87A51420DBD3998814`. Await T10's final diff/HEAD receipt and explicit slot release, then T20 assignment. T04 does not start tests before that handoff.

## T13 owner receipt, handoff still pending (2026-09-30)

T13 owner reports `operational_mode.py` at SHA-256 `3A083FA9DFF1B42E634B434ECAB8519916EBDC825579920CCF448B84AEC8F145`, 556 lines, untracked at HEAD `6050c41ce5510a6de3eaeb674a180560ea404f24`. Public API: `OperationalModeSnapshot`, `load_operational_mode`, `set_operational_mode`, `operational_mode_gate_error`, and accelerator-unload helpers. Dependencies: standard library, lazy `.config.load_config`, optional torch only in CUDA cleanup. Owner reports the file was included in earlier T13 suite (`100 passed / 25.24s`); CUDA cleanup used mocks. T13 states source/dependency/test receipt is ready but it did not send the file to T04; direct permission to hand it off is still pending. No T04 copy or edit occurred. Actual child launch remains unverified until the explicit handoff and authorized T04 integration.

## Stale-fixture rerun disposition (2026-09-30)

After T10's separate selector passed, T04 ran the assigned full command once before the owner fixture hunk had been handed into this worktree. Result remains `128 passed, 1 failed` (`test_registry_repair_reactivates_the_selected_project`, expected newest status `queued`, got `waiting`); log `artifacts/t04-full-assigned-suite-after-t10.log`, SHA-256 `C6A000F36069CA0566D1CF405FA2679505ADC969D0DC0113AF97AF9AB9FE9439`. This is stale-fixture evidence, not the required post-fix rerun. T20 now requires T10's explicit owner-approved fixture hunk (create both expected project roots, keep assertions unchanged), then scope check and one exact full-suite run. No T10-owned edit applied; T04 retains its assigned next slot while awaiting that handoff.

## T04 acceptance continuation receipt (2026-09-30)

T13 operational-mode module was copied into this T04 worktree after exact SHA-256 verification and approved handoff. Current source SHA-256: `3A083FA9DFF1B42E634B434ECAB8519916EBDC825579920CCF448B84AEC8F145`. Current client real-child HTTP acceptance is implemented in `tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result`; it starts a real child process, reaches real `/api/search`, checks response content and `hub.pid`, then cleans up the owned handle.

Latest failure diagnosis and fixes:
- `src/local_ai_hub/client.py`: close failed lock-write descriptor before unlink; avoids Windows sharing violation leaving stale `hub.start.lock`.
- `tests/test_mcp_compact_transport.py`: preconstruct app before fake `Popen` callback; keep payload/result assertions, avoid synchronous fake launch consuming startup timeout.

Validation on exact candidate:
- `git diff --check`: passed; only CRLF advisory for `tests/test_client_transport.py`.
- Exact regression command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_compact_transport.py::test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload tests/test_runtime_hardening.py::test_client_cleans_failed_start_lock_write`; `2 passed in 8.13s`; log `artifacts/t04-targeted-lock-and-mcp-after-fix.log`, SHA-256 `D0376250CB40EAFA716203B0D27F3B8162C9397CEFC76B29F49EB09026D8077F`.
- Full assigned nine-file suite: `132 passed in 26.57s`, exit 0; log `artifacts/t04-full-assigned-suite-after-fix.log`, SHA-256 `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`.
- Current `src/local_ai_hub/client.py` SHA-256 `B582F3DD53B656A7CD56E3D0A4E35F3E099D22452CD7D9060C8FAEFBE3294144`; `src/local_ai_hub/mcp_server.py` SHA-256 `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`; compact transport test SHA-256 `DB248D4A234D0965B4714C4ECDD3EFC4C719543FD8CC33FC301574A2B6FD7206`; runtime hardening test SHA-256 `3AAA236D1813598982EDF90942BC2DAA9CB12A16475A6D71007AD460CA0065EE`; op-mode test SHA-256 `C0DA99DF497E6418AF898C7084B0C3F1938CBDFA8F34640B83A9B5C871C6A87B`; real-child test SHA-256 `7C209E127DA857FF1DE2E379FBB56855CCA9E95E61333BD5578EB924ED35DD31`.

Older statements above saying no handoff, no real child test, 128 passed/1 failed, or no T04 rerun are superseded by this receipt. T04 released shared test slot to T06 after the green suite. Plan public API/conversation selectors and T21 adapter/runtime proof remain unverified/outside this assigned nine-file suite; full end-to-end acceptance remains partial until those owners' evidence is current. `/api/context/pack` and `http_server.py` unchanged.

## Closeout: exact ownership and working-tree receipt (2026-09-30)

Base `HEAD`: `3658d5056354849ddf17883ed04f807f16cc44c1`.

Hunk ownership for this closeout:
- T04-owned in this continuation: failed lock-write descriptor close/unlink fix in `src/local_ai_hub/client.py`; app preconstruction fixture correction in `tests/test_mcp_compact_transport.py`; real-child HTTP test in `tests/test_client_startup_resilience.py`; operational-mode test `tests/test_operational_mode.py`.
- T10-owned authorized fixture hunk only: directory setup in `tests/test_runtime_hardening.py`; test assertions unchanged.
- T13-owned source copied after approved handoff and hash check: `src/local_ai_hub/operational_mode.py`.
- Inherited/other-owner or ownership not asserted by this closeout: remaining hunks in `client.py`; all `mcp_server.py` changes and `tests/test_mcp_agent_routing.py` request-ID changes (T07); remaining hunks in `tests/test_mcp_compact_transport.py` and `tests/test_runtime_hardening.py`; `tests/test_client_transport.py`, `tests/test_sse_events_stream.py`, `tests/test_client_path_hints.py`, `tests/test_client_operational_mode_autostart.py`; unrelated existing contents under `artifacts/`. These were not rewritten or reset. Worktree was already dirty; preserve them as-is.

`git diff --check` passed. No more tests run after the green assigned suite. Targeted log SHA-256 `D0376250CB40EAFA716203B0D27F3B8162C9397CEFC76B29F49EB09026D8077F`; full log SHA-256 `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`.

Current file SHA-256: `client.py` `B582F3DD53B656A7CD56E3D0A4E35F3E099D22452CD7D9060C8FAEFBE3294144`; `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`; `operational_mode.py` `3A083FA9DFF1B42E634B434ECAB8519916EBDC825579920CCF448B84AEC8F145`; `test_client_transport.py` `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`; `test_mcp_agent_routing.py` `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`; `test_mcp_compact_transport.py` `DB248D4A234D0965B4714C4ECDD3EFC4C719543FD8CC33FC301574A2B6FD7206`; `test_runtime_hardening.py` `3AAA236D1813598982EDF90942BC2DAA9CB12A16475A6D71007AD460CA0065EE`; `test_sse_events_stream.py` `56B539AC59B2A2EB7C3C6346C0355A03D312D8247580DA67A634C196531EC602`; `test_client_startup_resilience.py` `7C209E127DA857FF1DE2E379FBB56855CCA9E95E61333BD5578EB924ED35DD31`; `test_client_path_hints.py` `5610A0AABB5CB7A236B15C9A53EEC983188F18ADF6839B3584C09A6E5DA6608F`; `test_client_operational_mode_autostart.py` `EF9F7A51DC2B4913B396CCBD3D62D4B848A7EBABF39CE943E33F92759398172A`; `test_operational_mode.py` `C0DA99DF497E6418AF898C7084B0C3F1938CBDFA8F34640B83A9B5C871C6A87B`.

## Current-state acceptance review (2026-09-30; source-only)

Reviewed current T04 plan and source after the 132-test run. Plan addendum in `docs/superpowers/plans/2026-09-26-t04-end-to-end.md` is 10 lines; SHA-256 `A695BDCA3D432D3FACFD07370DDBA075FC4A30D5EE5AE8ACACC75646501E057B`.

- Approved artifact-list change is present in clean `src/local_ai_hub/artifacts.py`: `ArtifactStore.list()` hashes supplied tenant with SHA-256, filters `tenant_identity` in both v2 and legacy schemas, caps limit at 100, sorts newest first, returns metadata fields only. `get()` unchanged. `tests/test_t04_public_api_contracts.py` contains bounded metadata, v2 hash/isolation, and legacy hash/isolation regressions. These tests were not in the current 132-test suite; rerun them with the rest of plan acceptance after slot assignment.
- Current transport suite covers stable request IDs across safe retry, no replay of unclassified mutations, invalid IDs rejected before network, stable explicit IDs, and MCP async forwarding. Latest assigned suite is current evidence for those client-owned requirements.
- Real-child test does launch exact OS child, posts root/query/top_k to real `/api/search`, checks returned source marker, PID file, startup-lock cleanup, and reaps exact child. It does not send path hints through that real child route. Client path-hint serialization/scope/cap tests are present and passed in current suite, but they stub HTTP. No T21 adapter/runtime implementation or test appears in this T04 checkout's bounded `PathHint/path_hints` search. Keep T21 end-to-end path-hint acceptance open until owner evidence or authorized handoff.
- Public API/conversation/operation/inventory evidence in plan's earlier sections is tied to previous candidate HEAD `f305ec6a8f4200b1fd9a2bde5048f43bd508db19`, not current HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`. Current T04 plan now records exact rerun scope. No tests were started: shared slot remains assigned to T06.
- `git diff --check` passed after plan update. Plan diff only appends current-candidate evidence; no runtime code or `/api/context/pack` change.

## MCP path-hint dependency found (2026-09-30; source-only)

Exact current-T04 source review: `_local_ai_repo_impl` and public `local_ai_repo` have no `path_hints` parameter. Their `action == "search"` branch calls `CLIENT.post("/api/search", {"root", "query", "top_k", "enrich"}, ...)`; it does not pass hints. `HubClient.post` filtering/serialization is therefore not reachable from current MCP repository caller. `mcp_server.py` has a T07-owned request-ID change; T03 owns public MCP wrapper and T21 private dispatch is isolated in another worktree. No overlapping edit made. Need exact owner handoff, MCP caller regression and actual HTTP route evidence. T06 currently owns shared test slot; no tests run.

## Re-run after T20 slot assignment (2026-09-30)

T10 fixture and T13 module hashes rechecked against authorized values; no unexpected change. Targeted selector group: 4 passed / 9.34s, log SHA-256 `282A486870BD60AB10259BD26B05EA19F4CA74C4CDD5625136CEAF44BC6AE8BB`. Full assigned nine-file suite: 132 passed / 25.79s, exit 0, log SHA-256 `5FEB8236E743C5984E8931ED842299AEF04DBA9CDBD2A01DC26383C51BF10935`. `git diff --check` passes. Test slot explicitly released to T07 through T20. Remaining gates unchanged: public API/conversation/operation/inventory rerun on current candidate; T03/T21 public MCP path-hint handoff and actual HTTP validation.

## Cross-owner queue snapshot (2026-09-30)

Read-only T03/T20 status check: T03 reports the public wrapper contract now exposes `path_hints`, validates path safety, and returns `unsupported` for non-empty hints until T21 private consumer adopts it; the T03 worktree is recovering from archive. This report is not T04-source evidence: the current T04 `mcp_server.py` still lacks the argument and forwarding branch. T20 says T07 owns next shared test run; T04's current-candidate public API selectors follow T07. No files transferred; no tests started after the 132-pass assigned suite. Keep goal open.

## Latest owner/slot state (2026-09-30)

T03 reports `/api/search` path-hint forwarding is still being added after recovering its archived checkout; `/api/context/pack` excluded. T21 reports its configured 4294 worktree is empty; its prior `t21-project-config` checkout was not handed off. T20 reports T07 owns active shared test slot; T04 public API selectors follow T07. These remain external owner reports only. T04 changed no overlapping source and ran no tests during this status check.

## Current candidate selector map (2026-09-30; no tests run)

The latest green 132-test suite includes all current `tests/test_mcp_agent_routing.py`, proving the current equivalent tests `test_local_ai_repo_investigate_preserves_include_code` and `test_repo_review_diff_returns_foreground_result_by_default`. Old plan receipts reference `tests/test_operation_contracts.py`, which is absent from this T04 checkout; equivalents are covered in MCP routing. Remaining public API/conversation/query/inventory command is recorded in the plan addendum for after T07 release. T07 remains active; no T04 test started.

## Current-candidate API acceptance receipt (2026-09-30)

After explicit T20 assignment, queued public API/conversation/query/inventory command ran: **39 passed in 43.83s**, exit 0. Log SHA-256 `9FC7FD1F9D623B9503C798DFDA70F15AF5F0E8A945830D12CE59E3C6335178A5`. Includes all `test_t04_public_api_contracts.py`, conversation store and production-route expiry/concurrency tests, three bounded task-query selectors, current API inventory, and current include_code/review equivalents. Candidate HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`. `git diff --check` passed. Shared slot released to T20; T03/T21 path-hint handoff and actual MCP-to-HTTP verification remain open.

## T03 active-search source review (2026-09-30; read-only)

Inspected T03 `e809` worktree only. Its MCP search wrapper normalizes and forwards public path hints; HTTP `/api/search` checks `repo_search` signature and returns 501 if unsupported. T03 `services.repo_search(root, query, top_k=12, context_lines=None, enrich=False)` still lacks `path_hints`, so actual service consumption is not present and hinted HTTP calls intentionally fail closed. None of this T03 code was copied into T04; T03 has not handed off hunks or run hint tests. No T04 tests this turn. `/api/context/pack` untouched.

## T03/T21 owner update (2026-09-30; external reports, not T04 source proof)

T03 completed its public wrapper work in restored worktree `e809`: MCP path hints now forward through `/api/search`; HTTP returns 501 when the selected service lacks hint support. T03 reports static AST checks, `git diff --check`, and Bugbot only; it ran no tests. These hunks are not in T04 and no exact code handoff has been recorded.

T21 reports configured worktree `4294` is empty and is waiting for approval to use existing `t21-project-config`. No service-consumer code or test receipt is handed to T04. The full path-hint E2E gate remains open until T03 and T21 deliver exact owner-reviewed hunks, T04 integrates only authorized paths, and T20 assigns the shared test slot. Current T04 source remains unchanged; `/api/context/pack` excluded.

## Registered T04 baseline reconciliation (2026-09-30; read-only inventory)

Confirmed registered worktree `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`; active-chat `393c` path is absent. Branch `codex/t04-integration-2b33602`; base `HEAD` `3658d5056354849ddf17883ed04f807f16cc44c1`. `git status --short --untracked-files=all` reports exactly 33 dirty files: 8 tracked modifications, 5 new source/test files, 20 untracked artifact files. `git diff --check` passes; only CRLF advisories.

Tracked hunks are mixed; preserve whole-file diffs. The current ownership map above marks only confirmed T04 hunks: client failed-lock-write cleanup, compact-transport fake-start fixture correction, real-child startup test, and operational-mode regression. T10 owns its runtime fixture hunk; T13 owns `operational_mode.py`; T07 owns request-ID changes in `mcp_server.py` and MCP routing tests. Remaining `client.py`, MCP, SSE, and fixture hunks are shared, other-owner, or inherited; no transfer by filename.

Five new source/test files: `operational_mode.py` is T13 handoff; `test_client_startup_resilience.py` contains T04 real-child test; `test_operational_mode.py` contains T04 acceptance tests. `test_client_path_hints.py` and `test_client_operational_mode_autostart.py` remain outside the confirmed T04-only hunk allowlist. Twenty untracked artifacts include T04-owned manifests/logs, T03/T07/T21 patches, and mixed T04/T21 patches; preserve all. Manifests bind patch bases to `3658d505...` and integration target base `824c9eb...`; stale/historical patches are not safe to apply wholesale.

Read-only owner candidates: T03 restored worktree `e809`, HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`, 6 dirty paths; its current hashes are `mcp_server.py` `92090A62D959BDFD97B4769A4438A1FACC072EDAE2108C148D489C80E8661A51`, `http_server.py` `BBC2510ED6365CE52DE207869F72C715F16345E7F216AC8050842278A5F2742B`, `services.py` `26B65B2B5198E0875EEB0BC6E667F0567529066BBA15D87FDA60480F0B374256`. T21 `t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`, 23 dirty paths; its dirty `services.repo_search` accepts `path_hints`, but mixed file is not handed off. Current hashes: `services.py` `15DAA1136C301F59FD4A630D3DEC870CEA621C2053A3A1AC13B2B01CE2098C60`, private `mcp_server.py` `AD9FB2D3DA93FA45A5E5DB1D1B6F493487BFA49BCA87356F4F01B8ADBCB9FE8C`, integration test `FA849D33998C70BD6351A6A46BC354395DA72A0194E92CBA09EA5C3BD957AC7B`, MCP hint test `BC26B0ACB7ED589332CF124630E89696295476E638482495D1432E67A7E146F6`. T21 tests have no run receipt. No source hunks copied; request exact owner patch and serialized slot through T20.

## Safe-start current-source correction (2026-09-30; supersedes older warning)

Current T04 `client.py` already records and validates process-creation identity in startup lock tokens and daemon sidecars (`_live_start_lock`, lines 80-133; `ensure_server`, around lines 426-460). Current `tests/test_client_startup_resilience.py` covers aged lock identity match, dead-daemon sidecar overriding launcher identity, partial sidecar publication, timeout with unreaped child, and exact real-child cleanup. These selectors are included in the green current 9-file suite. Earlier statements that T04 checks PID+age only or lacks lock identity are stale; do not transfer duplicate identity logic.

`_stop_owned_child` currently terminates, waits, then kills/reaps only its exact `Popen` handle (lines 65-77). The untracked historical T03 patch adds `terminate_tree` and differs at the import/cleanup hunk; `git apply --reverse --check` fails at `client.py:16`, so it is not a compatible current patch. T04 has real-child evidence for its exact child, but no process-tree descendant test. Keep this as a separate T03-owned review/handoff question; do not replace T04 cleanup or infer a safety gap from the stale PID-only note.

## T21 latest path-hint normalization evidence (2026-09-30; external candidate)

T21 completed a source-only change in existing `t21-project-config` checkout, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`, 23 dirty paths. `project_config.py` now normalizes contained absolute hint paths and maps `.` to repository root; escape checks remain. Current file hashes: `project_config.py` `BC647F65AA60A17D2843E3563290678502A8A2E3434027FCC907782716E039AD`, `tests/test_project_path_hints.py` `25F5F56701402C49CD542E95FA1D0ECD2AAB0F760C0A2F760CAD7BBEBE7B0B58`. Related untested consumer hashes remain `services.py` `15DAA1136C301F59FD4A630D3DEC870CEA621C2053A3A1AC13B2B01CE2098C60` and `tests/test_project_config_service_integration.py` `FA849D33998C70BD6351A6A46BC354395DA72A0194E92CBA09EA5C3BD957AC7B`.

T21 reports AST checks and `git diff --check` only; no pytest. These are mixed dirty T21 files, not T04 proof. Exact path-only hunk manifest and test slot remain outstanding. T04 source unchanged.

## Shared-slot delta (2026-09-30)

T20 latest live status: T08 fixed its scope parameterization; 8 tests pass. T08 still owns the slot while addressing a SQLite `ResourceWarning` and awaiting clean rerun/release. T06 and later runs wait. T04 has no slot assignment; no T04 tests ran in this turn. T21 source-only path-hint candidate remains untested and not handed off.

## Queue correction (2026-09-30)

T20 latest live status supersedes prior T08 `8 tests pass` update: newer targeted run is 3/4 because one skip reason mismatches; combined run had cleanup error. T08 still owns shared slot and is debugging. Do not treat the earlier 8-pass snapshot as current release evidence. T06 and T04 remain queued; no T04 tests ran in this turn.

## T21 service hunk boundary (2026-09-30; read-only)

T21 `services.py` diff changes `LocalAIServices.repo_search` in one large, approximately 209-line hunk. It combines request path-hint parsing/consumption with project-policy resolution, exclude filtering, fail-closed behavior, and full-search fallback handling. Related integration tests also cover policy/fallback behavior beyond hints. This is not a narrow path-hint-only patch. T04 requires T21 to provide an owner-reviewed exact transfer boundary or approve the complete service slice; no copy by inference. T20 latest slot remains T08; no T04 tests ran.

## Shared-slot delta (2026-09-30; latest)

T20 latest live status supersedes the 3/4 failure snapshot: T08 now confirms 9 targeted tests passed, 0 failed, no `ResourceWarning`; it is recording log/hash provenance. Explicit slot release is still pending. T06 remains waiting; T04 has no assignment and ran no tests this turn.

## Path-hint test-scope review (2026-09-30; source-only)

T21 `tests/test_mcp_repo_path_hints.py` monkeypatches `mcp_server.CLIENT` to `SimpleNamespace(post=...)`; it proves caller arguments only. T21 `test_project_config_service_integration.py` invokes `services.repo_search` directly. Neither spans MCP public action through a real HTTP route into service and returned result. T04 still needs one assigned caller-to-HTTP integration regression after T03/T21 exact owner handoff. Do not infer E2E from the owner-level unit tests.

## T04 client-to-HTTP path-hint test (2026-09-30)

Owned change: `tests/test_client_path_hints.py` only. The existing `_client` helper now accepts an optional port for ephemeral loopback servers. New `test_post_transmits_path_hints_over_http_and_returns_search_result` exercises `HubClient.post()` over a real socket, verifies the JSON body includes path-hint records, verifies `X-LocalAI-Request-ID`, and asserts the returned JSON result. Current SHA-256: `D94A3AD064AC9D02E47EB85AE8348B1DB15CBD5DBF1A55AB3334A6C686B3AF5D`.

Receipt: selector file **7 passed in 2.31s**, log SHA-256 `347095BA30F1D9A4A000FF9E0345103D6501A7031E4B79E6857041DC8FCB0836`; full assigned suite **133 passed in 27.74s**, log SHA-256 `46B51D4C7733C8E335EF885DC5F0B1F8709A818068219A7CE0AC9B4C3A0DABFF`; remaining current-plan API/conversation/query/inventory selectors **36 passed in 47.61s**, log SHA-256 `C6ADB138EC9E10C00B00FC8523C3ABF46E6024B0741151600A5DCE5BFEB8FFF1`. Candidate HEAD for all: `3658d5056354849ddf17883ed04f807f16cc44c1`. Test slot released to T20.

Boundary: the new test proves the HubClient wire boundary with a local HTTP server, not the production T03 MCP wrapper or T21 repository service. No T03/T21 hunks were copied. `mcp_server.py`, `http_server.py`, and `/api/context/pack` remain untouched in T04.
## Fresh path-hint owner boundary (2026-10-01; read-only)

T03 `e809` at HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`: wrapper `mcp_server.py` SHA-256 `92090A62D959BDFD97B4769A4438A1FACC072EDAE2108C148D489C80E8661A51` accepts/normalizes hints; `http_server.py` SHA-256 `BBC2510ED6365CE52DE207869F72C715F16345E7F216AC8050842278A5F2742B` gates forwarding on service signature and returns 501 without support; `services.py` SHA-256 `26B65B2B5198E0875EEB0BC6E667F0567529066BBA15D87FDA60480F0B374256` still lacks `path_hints`.

Prior T21 `t21-project-config` checkout HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` has a dirty path-hint-capable `services.py` (SHA-256 `15DAA1136C301F59FD4A630D3DEC870CEA621C2053A3A1AC13B2B01CE2098C60`). T21 has not handed that file to T03/T04; its latest report says only `project_config.py` transferred. Read-only inspection only. Full production MCP-to-service path-hint E2E remains open pending exact owner handoff and a production HTTP result. No T03/T21 file was copied or edited.

## Current-root compatibility and acceptance delta (2026-10-01)

T04 remains at candidate HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`; candidate hashes: `client.py` `B582F3DD53B656A7CD56E3D0A4E35F3E099D22452CD7D9060C8FAEFBE3294144`, `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`, `tests/test_client_path_hints.py` `D94A3AD064AC9D02E47EB85AE8348B1DB15CBD5DBF1A55AB3334A6C686B3AF5D`, `tests/test_client_startup_resilience.py` `7C209E127DA857FF1DE2E379FBB56855CCA9E95E61333BD5578EB924ED35DD31`.

Fresh root compatibility check used root HEAD `8f9ce9c6cd89c3d30e5184a3c5b729d911ec1319`, root `client.py` SHA-256 `DDB55EDA5F1949B19A876106E056A0C92992AA4D00BF711D85EFB67D3809A562`, and root `mcp_server.py` SHA-256 `49E82A3AC7B7784A9DF6D6F1711A31495279529CD44A3EC8738DB059CD104690`. `git apply --check --recount artifacts/t03-start-lock-only-to-t04.patch` failed at `src/local_ai_hub/client.py:62` (`patch does not apply`). Patch SHA-256 remains `26B2F25E213A39C8377986C58E70D1D33EC53C320B6AE60B649A82175E60A0CA`; it contains `_stop_owned_child`/import context outside the lock-only transfer, so it is not a safe current-root patch. Root lock lifecycle still has PID plus age only; transferring T04 nonce/creation-identity semantics requires coordinated lifecycle hunks, not helper-only cherry-pick. No root files changed.

Current T04 path-hint source audit: `_local_ai_repo_impl` and public `local_ai_repo` expose no `path_hints`, so client `/api/search` serialization is unreachable from MCP in this candidate. T03 owns public wrapper; T21 owns service/runtime consumer. Full production MCP-to-service proof remains blocked on exact owner handoff. Existing T04 receipts above prove HubClient-to-loopback HTTP only. T20 test-slot request remains pending; no tests rerun in this delta.

## Full T04 client/API commit comparison (2026-10-01)

Compared T04 branch `codex/t04-integration-2b33602` at `3658d5056354849ddf17883ed04f807f16cc44c1` with current dirty root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; common base `2b33602adef0d030fea66cdcc04ca742c60b2e32`. T04 commits touching client/API: `e2dcd2c` (public API contract corrections), `f305ec6` (task-list query), `3658d50` (query truncation and contract tests). Current root already contains `HubClient.list_tasks(query)` and `continue_conversation(task=...)`; AST comparison of both methods is identical. Root also contains MCP task-list query forwarding, GET/POST task query filtering and truncation, GET resolve-imports `auto` default, path-hint forwarding through MCP/service, and artifact listing filtered by hashed tenant identity in both v2 and legacy tables. Root has equivalent coverage in `tests/test_agent_task_query.py`, `tests/test_artifact_tenant_isolation.py`, and `tests/test_client_transport.py`; exact T04 API-contract selector names are absent (15 names); exact T04 client query regression selector is absent.

Two source acceptance gaps remain in current root: `_validate_api_payload` still validates `/api/chat/completions` messages before unsupported-route handling, and POST `/api/resolve_imports` still defaults `language` to `csharp`. Root-safe source-only patch is `artifacts/t04-current-root-api-contracts.patch`, SHA-256 `1CC4C06059CB9346344F2B0C918165450D59E474680E66F85A9082FFF8448A31`; root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a` `git apply --check --recount` passed. It contains only those two missing HTTP contract hunks. No root files changed.

The client query implementation already exists in root; exact regression test is missing. The minimal combined root-safe patch is `artifacts/t04-current-root-api-acceptance.patch`, SHA-256 `1E8740300FDACFC3B407788E2DD5D20321407A005EB6F802B84F85FDAF4171A1`; it includes only the two missing HTTP contract hunks and four focused tests (resolver GET/POST default, unsupported chat valid/invalid payloads, and task-query serialization). `git apply --check --recount --verbose` passed against root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; both HTTP hunks applied in check at offsets +1. No root files changed.

Exact root command after T20 applies the patch: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_current_root_acceptance.py tests/test_client_transport.py::test_continue_conversation_sends_task_over_real_http_and_keeps_transcript`. No current-root test ran in this delta because T20 still owns exclusive shared test scheduling. Candidate receipts remain previous T04 36-selector and 133-test results at candidate HEAD above; they are not current-root receipts.
