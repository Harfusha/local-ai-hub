# T04 criterion-to-evidence audit — 2026-10-02

Status: source/handoff audit only. No tests run, no root edits, no `/api/context/pack` edits. T20 owns root acceptance run and serial test allocation. Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`; worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`.

## T04 master-plan criteria map

| Criterion | Existing selector/evidence | Audit status at current candidate |
|---|---|---|
| Conversation continuation: `task`, transcript, expired conversation, concurrent turn | `tests/test_conversation_continue_route_contract.py::test_hub_client_continues_through_production_route_and_preserves_transcript`, `::test_expired_conversation_is_terminal_through_production_route`, `::test_competing_continuation_is_retryable_in_progress_through_production_route`; store/service cases in `tests/test_conversations.py`; MCP opaque-ID forwarding selector in `tests/test_mcp_agent_routing.py` | Covered by recorded 40-pass candidate receipt. Receipt pins `client.py` to `DCDF8B…`, current client is `338A2C…`; current-byte acceptance must be re-established by T20 or later slot. |
| `/api/chat/completions` contract | `tests/test_t04_public_api_contracts.py::test_unsupported_chat_completions_rejects_valid_payload`, `::test_unsupported_chat_completions_returns_404_for_invalid_payloads`, `::test_unsupported_chat_completions_returns_404_for_non_object_messages` | Recorded in 40-pass receipt. Current API receipt lists public API test hash `AAFA9B…`; current file still matches. No handler is advertised; outcome remains unsupported-route 404. |
| Artifact list: callable without ID, bounded metadata, tenant isolation | `::test_artifact_list_is_bounded_metadata_and_needs_no_id`, `::test_artifact_list_v2_hashes_and_isolates_tenants`, `::test_artifact_list_legacy_hashes_and_isolates_tenants` | Source and selectors present. `artifacts.py` SHA-256 `7F598EE…`; test SHA-256 `AAFA9BF…`. 40-pass receipt includes all three. Receipt contract preserves newest-first, max 100, metadata-only, and unchanged `get()`. |
| `resolve_imports` default | `::test_resolve_imports_get_and_post_share_auto_default` | Recorded in 40-pass receipt; test file still matches its receipt pin. |
| `include_code` and `call_graph_diff` / `semantic_diff` alias | `tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code`; `tests/test_t04_public_api_contracts.py::test_semantic_diff_action_uses_public_call_graph_diff_route` | Both covered by 40-pass receipt. Current MCP source hash matches T20 handoff pin `A6449D…`. |
| Shared response controls, RAG action descriptions, review/diff delivery, work controls | `test_t04_public_api_contracts.py::test_lean_rag_description_lists_every_supported_action`, `::test_lean_work_description_lists_continuation_and_response_controls`; `tests/test_mcp_response_budget.py::test_mcp_compact_applies_aggregate_budget`, `::test_mcp_compact_reuses_unchanged_payload`, `::test_mcp_compact_delta_profile_returns_changed_payload_only`; `tests/test_projection_extra_fields.py::test_mcp_compact_passes_extra_fields`; `tests/test_mcp_agent_routing.py::test_repo_review_diff_returns_foreground_result_by_default` | Description/review selectors are in the 40-pass receipt. The dedicated delta/reuse/extra-fields selectors exist and are in prior suite evidence, but current source/test pin set is not freshly validated as a whole. Reuse T20 evidence if its exact input pins match; otherwise defer to next slot. |
| Task-list query, current plan addendum | `test_t04_public_api_contracts.py::test_task_list_query_filters_contract_and_checkpoint_before_limit`, `::test_task_list_query_skips_stale_matches_before_limit`, `::test_task_list_surfaces_query_scan_truncation`, `::test_task_list_post_rejects_non_string_query`, `::test_coord_task_list_forwards_query`; bounded scan selectors in `tests/test_agent_tasks.py` | Covered by recorded 40-pass receipt; current files match receipt pins. |
| API surface inventory, current plan addendum | `tests/test_surface_inventory.py::test_inventory_extracts_surfaces_and_resolves_dynamic_route_registry` | Covered by recorded 40-pass receipt; source/test pin is `0D3C8B…`. |

## T04 client/transport continuation map

| Slice | Existing selectors | Current gap / evidence boundary |
|---|---|---|
| HTTP client retry/auth/malformed response/request-ID behavior | `tests/test_client_transport.py`; `tests/test_t04_client_auth_transport.py`; `tests/test_t04_client_retry_acceptance.py`; `tests/test_t04_malformed_json_contract.py`; `tests/test_t04_request_id_preflight.py`; `tests/test_t04_client_request_id_http.py` | Older receipts report focused green runs. Current `client.py` SHA-256 `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`, different from full-suite/API receipt pin `DCDF8BB…`; do not claim those receipts validate current client bytes. Root-current compatibility proposal is separate; see patch receipt below. |
| Opt-in in-process transport | `tests/test_inprocess_transport.py` nine contract selectors, combined with `tests/test_client_transport.py` | Prior recorded combined run: 37 passed. Its pins (`inprocess_transport.py` `A5567C…`, test `57EDD3…`) differ from current candidate (`25528A…`, `699321…`). Needs post-change slot and receipt. Root-current targeted attempt is failed/unknown as separately reconciled; no retries. |
| Cold client/MCP startup and exact child cleanup | `tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result`; `tests/test_t04_mcp_status_actual_hub_child.py::test_first_mcp_status_starts_and_reaps_real_hub_entrypoint`; `tests/test_t04_mcp_stdio_daemon_independent.py` simultaneous-client and timeout selectors | Prior receipts provide real-child evidence; current `test_client_startup_resilience.py` SHA-256 `67264628…`. Root acceptance remains T20-owned. |
| Path hints from MCP through service to `/api/search` | Client tests: `tests/test_client_path_hints.py::test_post_transmits_path_hints_over_http_and_returns_search_result`, `::test_search_sends_exact_typed_path_hints_request_body`; candidate real-root selector: `tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http` | Concrete candidate gap: current `mcp_server.py` public `local_ai_repo` / `_local_ai_repo_impl` has no `path_hints`; `services.repo_search(root, query, top_k, context_lines, enrich)` has no `path_hints`. Client-only stubs prove serialization, not MCP/service consumption. Requires exact T03 wrapper/route owner handoff plus T21 service-consumer/runtime proof. T04 must not author those owner hunks. `/api/context/pack` excluded. |

## Hash pins

Current candidate source/test pins read during this audit:

- `docs/superpowers/plans/2026-09-26-t04-end-to-end.md`: `F7A00A8CFD311BADAB52C8E562EFAA3BFCD3D1CBEA75C320D8470911902C0A24`
- `src/local_ai_hub/client.py`: `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`
- `src/local_ai_hub/inprocess_transport.py`: `25528A07417E5FDA4D86A954A0A44B73C30145A1FABC5B5E6244D0C3CEE51B47`
- `src/local_ai_hub/mcp_server.py`: `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`
- `src/local_ai_hub/services.py`: `3C15C8351791AC791C6F4F2C9F5D37CBE696D118FA2C628FAF7120D148E09F7F`
- `src/local_ai_hub/http_server.py`: `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7`
- `src/local_ai_hub/artifacts.py`: `7F598EE33012F3990CE6792D32EC2C125E12BBD113F0DF2B1A75C11C91ABB5B1`
- `tests/test_t04_public_api_contracts.py`: `AAFA9BF5713002C32EFDDE7D0CA77CFD7CD11CA9D38220F95B40BC8BF226ADFB`
- `tests/test_conversations.py`: `DA4822506DE70C66AA1204D6A44F1CECAEA766EBAD90DA012A67E933866973D7`
- `tests/test_conversation_continue_route_contract.py`: `32065B53B2D187648D8B181D106DCA59043BC609883A723F6760DB039BD2F3D5`
- `tests/test_mcp_agent_routing.py`: `6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54`
- `tests/test_agent_tasks.py`: `7E303EE53AF78231EEA0BAA0FB8E3E368030767573BCE76D7794CF693E54ED05`
- `tests/test_surface_inventory.py`: `0D3C8B45404A496ABBE6536878EEA731AD75F3E7AAC3BF19BBE91EC0372DAFCA`
- `tests/test_inprocess_transport.py`: `6993215113A42C8DE0077C5160FBCF537663C0E6E7DA347C94B643272FE74FEE`
- Prior T20 handoff before this audit: `handoff/t04-t20-acceptance-handoff-2026-10-02-v1.md` SHA-256 `4DBF5BF092F03F840DB303CA13568D74DCE36E4033BA93564D94C844CCE93D9D`.
- Prior root-current reconciliation: `handoff/t04-root-current-validation-reconciliation-2026-10-02.md` SHA-256 `A74346BCAFEF1D781890AE90807CF491AD098E276DB9B3F444DB9987288C1641`.

The root-current patch packet and pre/post hashes are in the reconciliation receipt: fixture, client, mode-output, path-gate. Those patches are not applied. Root preimages were validated with `git apply --check` when the receipt was produced; T20 currently owns root acceptance, so these hashes are historical pins until rechecked after T20 finishes.

## T20 disposition

- Reuse 40/API and 133/full-suite receipts only for source hashes they actually pin. At least `client.py` and in-process transport/test have changed since those receipts; current candidate does not have fresh complete acceptance on those bytes.
- Preserve four un-applied root-current patches for owner review; no root integration from T04.
- Root/T20 test run is external to this audit. Wait for T20 receipt before any selector execution.
- Remaining cross-owner path-hint gate: T03 public wrapper/HTTP route patch plus T21 `repo_search` consumer and runtime receipt. No additional T04 production patch is authorized or identified.
- Handoff does not claim full T04 completion. Historical release scanner still has no pass receipt because it scanned an untracked artifact file; tracked-source scan is distinct evidence.

## T20 startup-fallback failure triage (2026-10-02)

T20 reported 3 passed / 1 failed with an assertion for `result["retried"]`; exact selector, actual result payload, and failure log were not included in the handoff. Source audit in this T04 worktree:

- `tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints` simulates first-attempt pre-send refusal, successful auto-start, then successful second POST. Contract asserts exact result `{"success": true}` and stable request ID/body across attempts; success response passes through unchanged, with no `retried` marker.
- `src/local_ai_hub/client.py` (`338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`) adds `retried: true` only when the second attempt itself fails/throws and a transport-failure result is returned. Successful HTTP error or success response is returned as server response.

Conclusion: if T20 selector asserts `retried` on successful startup fallback, expectation conflicts with existing public client contract and is stale; no source patch warranted. If assertion concerns retry failure, actual payload and exact selector are needed before classifying. No test or root read/write performed for this triage; no patch created. T20 log excerpt requested from user because task-to-task messaging is not authorized by this chat.

## Resume/baseline audit (2026-10-02)

- Original worktree only: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`. No checkout switch or root edit.
- Dirty baseline before further changes: 9 tracked dirty paths and 20 untracked entries. Tracked paths: T04 plan, client.py, http_server.py, mcp_server.py, test_client_transport.py, test_mcp_agent_routing.py, test_mcp_compact_transport.py, test_runtime_hardening.py, test_sse_events_stream.py. Preserve mixed ownership; no changes to these paths made in this resume.
- Current T04-owned source/test work already present: client.py, inprocess_transport.py, tests/test_inprocess_transport.py, startup/path-hint acceptance tests, and prior patch/receipt artifacts. Owner-controlled T03/T07/T13 hunks/files remain outside T04 edit scope.
- This resume added/updated only this handoff audit and the earlier T04 reconciliation receipt; no implementation/test changes.
- Token-economizer plan-only script absent at both documented `.agents` and `.codex` skill paths; no tools installed and no PATH changed.
- Hub `local_ai_status(detail="agent_state")` returned terminal 500 `MCP output contract failed: result does not match a declared output variant for action='agent_state'`, retryable false. No repeat. `local_ai_coord(task_list, query="T04")` returned two unrelated planned items, no active T04 completion task. `local_ai_coord(leases)` returned no lease entries. These results do not constitute explicit T20 serial-slot release.
- User says T20 slot 32 reported 3 passed / 1 failed. Root import/transport validation remains gated by the original goal's explicit-release condition. No fresh T20 release receipt is present in this worktree.

## PR #3 continuation / slot update

After slot A was manually closed by T20, the PR #3 T04-only review found missing polling for HTTP `in_progress` after safe-request restart retry. T04 changed only `src/local_ai_hub/client.py` and `tests/test_t04_client_retry_acceptance.py`; hashes and exact targeted command are in `handoff/t04-pr3-safe-request-retry-review-2026-10-02.md` (SHA-256 `06A78E11A280783260625A575AC03525F767F348EABC96D9C6970AE73DB2CE35`). New code/test changes are not verified. T20 says slot D belongs to T15; no tests until next exclusive T04 slot.

## Latest PR #3 scope pins (2026-10-02)

Supersedes this audit's earlier PR #3 source pins. Current T04 candidate: `client.py` SHA-256 `89633C62382606CC6E5B134158D2992C061B3DA7B9ED46CE30B16803C8613E8D`; retry test `47A1F4B9DC1D2568D2D1C63E9825B8B7B182478E60468D0702AE017F2A9EBBDD`; startup test `ECAAF238CB64046D22AB825DB7BB0A85EB98F75EDBD330C640FEA44E880627E4`. Retries now require `replay_safe=True`; `/api/search` is in read-only allowlist. Explicit false mutation no-retry and post-restart `in_progress` selectors await fresh T20 slot. Detailed PR-only review receipt: `handoff/t04-pr3-safe-request-retry-review-2026-10-02.md`, SHA-256 `3F637CA788C7AED49D2D3FBABF70200E54C32C0E9595F6570D0DE6E32ACD2815`.

## PR #3 strict-gate amendment (2026-10-02)

Latest T04 source/test pins supersede previous PR #3 pins: `client.py` `ECDFAE20344CD8BE228CD2E2A034F787314627856E5EA588EEA4CCB99CB68879`; retry selectors `FA3958885FD096A0748CD438D9CDFB45671092CA5777BF1A824F2D95CBC8269E`; startup selector file `ECAAF238CB64046D22AB825DB7BB0A85EB98F75EDBD330C640FEA44E880627E4`. Poll intermediate `in_progress` only for `replay_safe=True`; explicit false never polls/restarts; terminal 503 never retries. Detailed receipt SHA-256 `1D750EE4773A74EF2E9084A0C7E8308E74459CCAF5789943E00AB3E80D64BFD6`. New test bytes await an exclusive T04 validation slot; slot D remains with T15.

## Path-hints current-candidate note (2026-10-02)

The T04 client test fixture now matches T03/T21 tuple `templates/element` / `repository_search` / `repository_search`; test SHA-256 `032BF90E3B4C39CEAFAAE77D1750EDB9EC7A97BDFC74D1382EA4FE5E9DEACE24`. Client source remains `ECDFAE20344CD8BE228CD2E2A034F787314627856E5EA588EEA4CCB99CB68879`. No post-edit test receipt exists. Full MCP path-hints acceptance remains blocked by the missing T03-owned public wrapper in this candidate. Focused validation awaits a fresh exclusive T04 slot from T20; current slot D belongs to T15.

## T04 MCP path-hints forwarding (2026-10-02)

T04 now appends optional `path_hints` to `_local_ai_repo_impl` and public `local_ai_repo`, then forwards them only through the `search` action to `HubClient.post` for `/api/search`. The parameter stays last to preserve positional compatibility. `client.py` retains route filtering, accepted-field filtering, and the 64-hint cap. The existing registered-tool real-HTTP acceptance selector is `tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http`. No tests ran because T20 slot G is UNKNOWN. Static checks passed: `git diff --check` and `ast.parse` over six source/test files. Current hashes: MCP source `1D7C6E0C0FE37FB61C23BC203E179B05E472175326DD8DDCCB388916EA1827A`; client source `ECDFAE20344CD8BE228CD2E2A034F787314627856E5EA588EEA4CCB99CB68879`. Exact focused command and full selector list are in `handoff/t04-pr3-safe-request-retry-review-2026-10-02.md`.

## T07 replay-safe guard handoff (2026-10-02)

f374 now has a T07 copy of T04's replay-safe in-progress polling guard and a T07-owned explicit-false test in `tests/test_client_transport.py`. Preserve T04 branch; later integration should keep one matching source guard and both T04 and T07 acceptance coverage. T20 slot-I selector ended with `Transport closed` / `outcome UNKNOWN`; no retry or native fallback; slot I released. No passing validation receipt exists.

## Empty path-hints case (2026-10-02)

T04 aligned the client with existing MCP-to-service acceptance: empty `path_hints` now behaves as omitted. Added `test_post_omits_empty_path_hints`. Source/test hashes: `CA624A5356A8632AD0CF603DBB8A9B37221DB68F6FD2B97FF8DE5EE0D47153B2` / `6FC0EF7185D6EEC8313C7919AB9346BBD28A1F72820F1A36173D71F094309A6D`. `git diff --check` and AST parse passed; no tests ran. Exact focused validation command awaits an exclusive T04 slot and is recorded in the PR3 receipt.

## Slot-I attribution correction (2026-10-02)

T20 confirms slot I belonged to T07. Its `Transport closed` / `outcome UNKNOWN` result is not a T04 test outcome. T04 has no slot-I attempt; current path-hints/retry changes remain unverified. Prior slot-A in-process pass is historical only.
