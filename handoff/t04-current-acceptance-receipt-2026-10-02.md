# T04 current candidate acceptance receipt — 2026-10-02

Worktree: C:/Users/Adam/.codex/worktrees/t04-integration/.local-ai-hub
Candidate HEAD: 3658d5056354849ddf17883ed04f807f16cc44c1
Root HEAD: 01df56605ccf484ebfe2808ac60d696c4e81dffc
Root client SHA-256 (unchanged): 75B07C21735B881ED58C03BFC80B450410C3778C248D662A7C8E675549180D4F

## Fresh candidate validation

- API/conversation/inventory/task-query batch: 40 passed in 47.55s, exit 0. This run followed fixture alignment to required canonical root/principal scope. The earlier run on the unaligned fixtures had 36 passed / 4 failed: three task calls omitted required root; the artifact fixture wrote under empty tenant while no-header HTTP requests use http-default. No production guard or tenant filter was weakened.
- Transport batch: 16 passed in two groups of 8, rerun after the connect-failure classification fix. Only ConnectionRefusedError is marked definitely not sent; generic connect timeout remains outcome-unknown.
- Candidate git diff --check: pass. No source or test changes followed these runs; only this receipt was written afterward.

## Exact API/conversation command

python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_public_api_contracts.py tests/test_conversations.py tests/test_conversation_continue_route_contract.py::test_hub_client_continues_through_production_route_and_preserves_transcript tests/test_conversation_continue_route_contract.py::test_expired_conversation_is_terminal_through_production_route tests/test_conversation_continue_route_contract.py::test_competing_continuation_is_retryable_in_progress_through_production_route tests/test_mcp_agent_routing.py::test_local_ai_task_forwards_continue_with_opaque_conversation_id tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code tests/test_mcp_agent_routing.py::test_repo_review_diff_returns_foreground_result_by_default tests/test_agent_tasks.py::test_task_query_bounds_rows_scanned tests/test_agent_tasks.py::test_task_query_scan_window_is_bounded_before_stale_filter tests/test_agent_tasks.py::test_task_query_skips_stale_candidate_before_page_limit tests/test_surface_inventory.py::test_inventory_extracts_surfaces_and_resolves_dynamic_route_registry

Result: 40 passed in 47.55s. Command text SHA-256: 0B75E141227590A36D6E97AAA3057C2FAB60A9D57089244D87C0F942AAFCA7EC.

## Transport groups

Group 1: 8 passed in 2.63s after the fix. Command text SHA-256: 4DCEE30F4756D1DBBEC3F548D88499C590C2091E56F146DFAD920D87FC816CA1.

python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_client_reuses_one_http11_connection_for_sequential_requests tests/test_client_transport.py::test_client_coalesces_simultaneous_identical_requests tests/test_client_transport.py::test_client_reconnects_on_idle_disconnect tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_transport.py::test_client_does_not_replay_ambiguous_default_post tests/test_client_transport.py::test_client_does_not_coalesce_identical_mutating_posts tests/test_client_transport.py::test_client_replays_explicitly_safe_post_with_stable_request_id tests/test_client_transport.py::test_post_does_not_replay_unclassified_mutation

Group 2: 8 passed in 2.55s. Command text SHA-256: 0D3288BB8469D3B1B9EF7BDA4213E692FED0053C240D35F58CD66FEF3B82E227.

python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_post_does_not_replay_file_writing_generate_types tests/test_client_transport.py::test_post_replays_allowlisted_read_only_route tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_not_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown tests/test_client_transport.py::test_safe_posts_with_distinct_explicit_request_ids_do_not_coalesce

## Current source/test pins

- src/local_ai_hub/client.py: 007A7D932C54FBA78D411B9EC622B70FEDC35666DFCCA275311444F26C05002B
- src/local_ai_hub/mcp_server.py: 1D7C6E0C0FE37FB61C23BC203E179B05E472175326DD8DDCCB388916EA1827A1
- src/local_ai_hub/artifacts.py: 7F598EE33012F3990CE6792D32EC2C125E12BBD113F0DF2B1A75C11C91ABB5B1
- src/local_ai_hub/agent_tasks.py: 80DE9E654AAA2065AA6CC18CF47E19E4DB346D3154870560245319C382BC38AF
- tests/test_t04_public_api_contracts.py: F95730F0D77B51C1D9163BA1B5F95B47967A981CE278128D305A2EF4C925C002
- tests/test_conversations.py: DA4822506DE70C66AA1204D6A44F1CECAEA766EBAD90DA012A67E933866973D7
- tests/test_conversation_continue_route_contract.py: 32065B53B2D187648D8B181D106DCA59043BC609883A723F6760DB039BD2F3D5
- tests/test_mcp_agent_routing.py: 6150D24029076D29343E9CEF648E61C2FE4C025A9F800C221CB1868618423F54
- tests/test_agent_tasks.py: 7E303EE53AF78231EEA0BAA0FB8E3E368030767573BCE76D7794CF693E54ED05
- tests/test_surface_inventory.py: 0D3C8B45404A496ABBE6536878EEA731AD75F3E7AAC3BF19BBE91EC0372DAFCA
- tests/test_client_transport.py: FE3F90240CCA4DAE7F3B2B0DD3CAFEA8A0AA29916AC7CC1A35A9EB364C1BF242
- tests/test_client_tenant_override.py: C34DA8FA8C740FA1711F20C213D0CCA978515C89DD101302166F01275B05F1EF

## Root-current handoff

- Composed client patch: handoff/t04-root-current-tenant-deadline-combined.patch, SHA-256 FBED6CF6CD42699A81F1B6128FF046105835A0E303EF4B5B25951E4D1B01F007. git apply --check passes against root.
- Tenant contract test patch: handoff/t04-root-current-tenant-contract-test.patch, SHA-256 BBA355321A566E4C9EC44D68591B7118719048AA95E9B7D1ECB2A91F4E796BD2. git apply --check passes against root.
- Root checkout was not edited.

## Remaining acceptance gaps

- Public MCP path_hints wrapper is T03-owned and absent from this candidate; T03 work remains pending.
- Current root contains HTTP operational-mode enforcement: `_http_mode_policy` at `src/local_ai_hub/http_server.py:340`, `_http_mode_gate_error` at `:374`, and GET/POST gate call sites. Root hashes: `http_server.py` `A8DF17496129DDA67BB74711A7D83568385FC301AB670AF3FB8F1659C7E3221D`; test `tests/test_operational_mode_http_gate.py` `4985B116CE2A7F12978BB5B2884608BA67D3BD56F0FB7A746AB33F8D7ABE9C6D`. T20 matrix SHA-256 `DADD58000EE398AA2E863FF0A8384F02F6BEE70AF01CFBF00B308C39FDEA7D07` records **3 passed in 0.31s** on root; T20 thread records serial GO #2 relayed for this test. This is HTTP gate unit/contract proof, not MCP-over-HTTP E2E. Root files were inspected, not edited in this turn.
- T21 adapter/runtime evidence is absent; no live daemon/runtime acceptance is claimed.
- This is candidate-worktree proof, not integrated root proof.

## T03 dependency handoff

T03 completed its e809 candidate with proxy/transport patch SHA-256 700A4D11A870A247922999FF3F8CDEC283873B43C53A6D3C3201BA647FCB2FC0 and path_hints patch SHA-256 44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00. Both apply checks fail against current root because the root mcp_server.py / operation_contracts.py / tests differ from clean e809; no root files were changed. T03 reports no new test run because T20 serial GO was absent. The owner must produce a root-current T03 patch and obtain its serial test slot.

## Serial GO audit

- The 16 transport selectors had direct user authorization (“Yes, run them”); no separate T20 serial GO was recorded. Candidate-only.
- The initial 40-selector run, fixture diagnostics, targeted transport reruns, and final 40-selector rerun have no T20 GO receipt. The final 40-selector command was already running when T20 said it could finish. T20 matrix marks it candidate-only because command/GO provenance had not been verified there; this receipt now pins the exact command and inputs, but does not claim T20 GO.
- No tests ran after that command completed. The root mode-gate 3-pass result is attributed to T20’s separate GO #2 receipt, not this turn’s test execution.

## Runtime acceptance update — 2026-10-03

Evidence below was supplied by the user and was not independently collected in this T04 turn:

- Service state reports `running`, PID `231460`, restart count `1174`.
- HTTP process PID `150832`, start time `00:16:55`. The PID difference alone does not establish a duplicate daemon; topology needs a parent/child and listener check.
- `hub_stderr` repeatedly ends with `RuntimeError('agent_state changed during schema preflight')` from `agent_events.py`.
- Preprocessing reports SQLite `database is locked`.
- `supervisor.log` reports failed startup health checks followed by recycling.
- Observed load: 54 MCP and 2 HTTP clients/processes, approximately 3.65 GB RSS.

**Acceptance: FAIL / runtime blocked.** Repeated supervisor recycle, schema-preflight races, and SQLite lock errors violate stable startup/shared-state requirements. A single-daemon claim is not established by these counters alone. Preserve all runtime logs as one incident receipt with timestamp, resolved config path, state directory, process tree, listening PID, restart delta, and RSS before/after recovery. Do not classify previous mocked client tests as runtime evidence.

### Quick recovery (operator procedure; not executed here)

1. Pause new MCP clients and stop request ingress so no new tasks/preprocessing writes arrive.
2. Use the configured service manager to stop the managed supervisor/Hub gracefully. Do not kill a PID based only on the two reported numbers; first verify executable, command line, parent PID, config path, state directory, and listening socket. Do not delete SQLite database, WAL/SHM, start-lock, or supervisor files to clear the symptom.
3. After writers exit, make a consistent SQLite backup using SQLite's backup API/CLI, then run `PRAGMA integrity_check` against the backup. Keep the original database and logs intact.
4. Start exactly one configured supervisor instance with the same resolved config/state directory. Wait for health readiness; confirm one supervisor, one expected HTTP child/listener, zero restart increase, and no new schema-preflight or database-lock errors during a stability window.
5. Reconnect one MCP client first; observe health, restart count, logs, and RSS before restoring the remaining clients gradually.

Stop recovery and leave service offline if database integrity fails, the identity/config of either process is ambiguous, or the single supervisor cannot reach healthy state. This procedure cannot repair the `agent_events.py` schema-preflight race; that needs an owner-scoped code fix and T20-authorized validation.
