# T01 behavioral coverage matrix — root snapshot (provisional)

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a` (per T20 snapshot).
- Source matrix: `docs/API_COVERAGE.md`; SHA-256 `e3b5a6559c5f0e6adec165b6a416e6de600c7f00b121da4615b176abda397a49`; 685 rows, 685 unique operation IDs.
- Baseline provenance: root snapshot at `C:\Users\Adam\.local-ai-hub`, root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, baseline document SHA `E3B5A6559C5F0E6ADEC165B6A416E6DE600C7F00B121DA4615B176ABDA397A49`. Candidate test import origin and candidate document hash are recorded under validation; they are distinct from this root baseline.
- Root paths in T20 snapshot: `http_server.py`, `mcp_server.py`, `hubctl.py`, `operation_contracts.py`, and `docs/API_COVERAGE.md` are dirty; T03 completed static registry-gap analysis without edits/tests; its recommended MCP contract changes are still unresolved in the root snapshot. T19 parity review is also pending. Matrix remains provisional until T20 confirms source/docs freeze.
- No root API_COVERAGE regeneration/check or root write was performed. This handoff is candidate-only; T03 owns prioritized contract-gap analysis.

## Behavioral coverage by actual surface

| Surface | Operations | Asserted behavior | Metadata only | Owner task labels | Examples: operation → test |
|---|---:|---:|---:|---|---|
| HTTP POST | 223 | 14 | 209 | unassigned: 223 | `/api/agent-state/context` → `tests/test_agent_state_transport.py::test_http_context_transport_forwards_scope_context`; `/api/agent-state/memory` → `tests/test_agent_os_enhancements.py::test_http_server_flat_payload_fallbacks` |
| MCP action local_ai_repo | 80 | 6 | 74 | unassigned: 80 | `context_compile` → `tests/test_agent_state_transport.py::test_mcp_actions_dispatch_and_compact`; `investigate` → `tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code` |
| HTTP GET | 69 | 6 | 63 | unassigned: 68, T01: 1 | `/api/adoption` → `tests/test_adoption_metrics.py::test_http_adoption_endpoint_returns_aggregates_only`; `/api/debug-traces` → `tests/test_reliability_core.py::test_http_auth_json_limits_security_headers_and_binary_bundle` |
| HubClient target | 57 | 26 | 31 | unassigned: 57 | `POST /api/agent-state/tasks` → `tests/test_client_operation_acceptance.py::test_client_create_task_targets_agent_state_tasks`; `POST /api/agent-state/memory` → `tests/test_client_operation_acceptance.py::test_client_record_memory_targets_agent_state_memory` |
| HubClient method | 56 | 15 | 41 | unassigned: 56 | `_online` → `tests/test_reliability_integration.py::test_client_caps_get_timeout_and_treats_overload_as_live`; `ensure_server` → `tests/test_mcp_autostart_contract.py::test_daemon_off_start_timeout_reaps_only_owned_child` |
| MCP action local_ai_coord | 51 | 16 | 35 | unassigned: 51 | `blackboard_update` → `tests/test_mcp_agent_routing.py::test_coord_forwards_explicit_receipt_criterion_and_blackboard_identity`; `claim` → `tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_claim_forwards_owned_paths_and_lease_identity` |
| MCP action local_ai_task | 28 | 11 | 17 | unassigned: 28 | `candidate_create` → `tests/test_agent_state_transport.py::test_mcp_actions_dispatch_and_compact`; `candidate_promote` → `tests/test_agent_state_transport.py::test_mcp_actions_dispatch_and_compact` |
| MCP action local_ai_command | 27 | 10 | 17 | unassigned: 27 | `auto_fix` → `tests/test_mcp_command_operation_acceptance.py::test_mcp_command_auto_fix_forwards_bounded_repair_policy`; `cancel` → `tests/test_mcp_command_operation_acceptance.py::test_mcp_command_cancel_targets_execution_and_returns_cancel_state` |
| CLI operation | 18 | 15 | 3 | unassigned: 18 | `agent-state` → `tests/test_agent_os_enhancements.py::test_hubctl_agent_state_and_cleanup`; `clean` → `tests/test_hubctl_unlinked_operations.py::test_hubctl_clean_dispatches_cleanup_and_json_output` |
| MCP action alias local_ai_coord | 12 | 0 | 12 | unassigned: 12 | `ctx (alias for context_compile)` → no asserted behavior test |
| MCP tool | 8 | 8 | 0 | unassigned: 8 | `local_ai_artifact` → `tests/test_mcp_agent_routing.py::test_artifact_and_command_success_do_not_expose_semantic_handoff`; `local_ai_command` → `tests/test_mcp_agent_routing.py::test_artifact_and_command_success_do_not_expose_semantic_handoff` |
| MCP action local_ai_rag | 7 | 7 | 0 | unassigned: 7 | `docset_index` → `tests/test_rag_work_operation_acceptance.py::test_mcp_rag_docset_index_uses_query_as_name_and_returns_index_receipt`; `docset_search` → `tests/test_rag_work_operation_acceptance.py::test_mcp_rag_docset_search_defaults_name_and_clamps_top_k` |
| MCP action schema gap local_ai_coord | 7 | 0 | 7 | unassigned: 7 | `claim_batch` → no asserted behavior test |
| MCP action local_ai_work | 6 | 6 | 0 | unassigned: 6 | `cancel` → `tests/test_rag_work_operation_acceptance.py::test_mcp_work_cancel_returns_cancelled_state`; `continue` → `tests/test_rag_work_operation_acceptance.py::test_mcp_work_continue_forwards_answer_and_preserves_updated_state` |
| MCP action local_ai_status | 5 | 1 | 4 | unassigned: 5 | `agent_state` → `tests/test_operation_contracts.py::test_mcp_boundary_rejects_invalid_operation_before_handler` |
| MCP action schema gap local_ai_status | 5 | 1 | 4 | unassigned: 5 | `health` → `tests/test_operational_mode.py::test_mcp_agent_tool_is_rejected_before_dispatch_but_status_remains_available` |
| MCP detail local_ai_status | 5 | 2 | 3 | unassigned: 5 | `agent_state` → `tests/test_agent_state_transport.py::test_mcp_actions_dispatch_and_compact`; `brief` → `tests/test_mcp_compact_transport.py::test_mcp_call_tool_returns_compact_minified_json` |
| MCP action alias local_ai_command | 4 | 0 | 4 | unassigned: 4 | `patch (alias for patch_and_verify)` → no asserted behavior test |
| MCP action alias local_ai_repo | 4 | 0 | 4 | unassigned: 4 | `idx (alias for code_index)` → no asserted behavior test |
| MCP action alias local_ai_task | 3 | 0 | 3 | unassigned: 3 | `gen (alias for delegate)` → no asserted behavior test |
| MCP action local_ai_artifact | 3 | 2 | 1 | unassigned: 3 | `get` → `tests/test_mcp_compact_transport.py::test_mcp_artifact_page_rejects_store_slice_larger_than_text_limit`; `list` → `tests/test_mcp_task_mode_gate.py::test_gaming_allows_cheap_artifact_read` |
| Generated manifest | 2 | 0 | 2 | unassigned: 2 | `docs/INSTALL_PROMPT.md` → no asserted behavior test |
| MCP action schema gap local_ai_command | 2 | 1 | 1 | unassigned: 2 | `speculative_lint` → `tests/test_mcp_command_operation_acceptance.py::test_mcp_command_speculative_lint_submits_bounded_paths_and_job_identity` |
| MCP action schema gap local_ai_repo | 2 | 1 | 1 | unassigned: 2 | `batch_replace` → `tests/test_mcp_agent_routing.py::test_local_ai_repo_batch_replace_does_not_use_staged_as_dry_run` |
| MCP action schema gap local_ai_work | 1 | 0 | 1 | unassigned: 1 | `local_ai_work` → no asserted behavior test |

## Needs, returns, policy and acceptance gaps

- Every row has a structured `Contract` field. It contains `input_schema` and `output_schema`; per-operation required inputs, returned fields, access classification, cache key, tenant scope, timeouts, side effects, provenance, test IDs, and benchmark cohort stay in the source matrix.
- Root matrix behavioral disposition: 148 operation rows link asserted behavior tests; 537 rows are metadata-only and remain behavior-unverified.
- Snapshot owner labels remain 684 `unassigned` and 1 `T01`. The candidate deterministic projection assigns all 685 rows across T01–T21 (counts recorded below); it is provisional and has not changed the root document.

| Contract gap | Rows |
|---|---:|
| `benchmark_cohort` | 685 |
| `cache_key` | 685 |
| `tenant_scope` | 685 |
| `timeout` | 677 |
| `schema_status` | 639 |
| `backend_availability` | 603 |
| `fixtures` | 539 |
| `behavioral_disposition` | 537 |
| `test_coverage` | 537 |
| `response_contract` | 335 |
| `auth_identity` | 292 |
| `idempotence` | 292 |
| `limits` | 292 |
| `required_fields` | 292 |
| `side_effects` | 292 |
| `classification` | 291 |
| `output_schema` | 260 |
| `operation_side_effects` | 168 |
| `response_mapping` | 113 |
| `retry_policy` | 107 |
| `status_codes` | 83 |
| `target` | 56 |
| `http_target` | 45 |
| `request_payload` | 24 |
| `changed_files` | 18 |
| `dependency_scope` | 18 |
| `os` | 18 |
| `parameter_scope` | 18 |
| `recovery` | 18 |
| `scope` | 18 |
| `return_code_scope` | 18 |
| `acceptance` | 17 |
| `condition` | 17 |
| `format` | 3 |
| `test_ids` | 2 |

## Recorded acceptance evidence

- Candidate broad targeted command: `PYTHONPATH=src C:\Python313\python.exe -B -m pytest -q --tb=short tests/test_surface_inventory.py tests/test_client_operation_acceptance.py tests/test_http_route_operation_acceptance.py tests/test_hubctl_unlinked_operations.py tests/test_mcp_command_operation_acceptance.py tests/test_mcp_coord_operation_acceptance.py tests/test_rag_work_operation_acceptance.py` — 746 passed in 54.60 s after fixing generic owner inference and the synthetic task-id fallback assertion. Candidate HEAD `689165fbe18101feacf5f489847a4890fc27ed1f`; generator SHA-256 `6513D91FAB541B3B32FC10845F007FF495BD8177D56E34371AA029A19A11A1E2`; test SHA-256 `ADF8B12B7E4C90FD852C0C5A3889EC9E3D055BF24EC547496AD74548537B9099`.
- Verifier import origin is candidate-only: `tests/test_surface_inventory.py` sets `ROOT = Path(__file__).resolve().parents[1]` then loads `ROOT/tools/surface_inventory.py` by file spec. In this run that resolves to `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub\tools\surface_inventory.py`. The verifier's candidate `docs/API_COVERAGE.md` SHA is `4B83315C990B6FC74F3BF89CBB49337CFF9AA085266FE3DA4004EEA72AC80C72`; it differs from the root-baseline doc below, so this suite is not a root-source receipt.
- Root stale-check selector after applying SHA patch: `test_check_mode_reports_stale_coverage_without_repairing`, 1 passed in 3.93 s, root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `tools/surface_inventory.py --check` returned expected drift (exit 1; 685 rows; coverage mismatch) with `API_COVERAGE.md` SHA-256 `E3B5A6559C5F0E6ADEC165B6A416E6DE600C7F00B121DA4615B176ABDA397A49` unchanged before/after. No `--write-doc` or root doc regeneration was run.
- These receipts cover only the named checks; linked selectors in the 685-row CSV are references, not fresh pass receipts. The 537 metadata-only rows remain behavior-unverified.


## Provisional deterministic owner projection

- Candidate assigns all 685 current root-snapshot operation rows; projection counts: T01 1, T02 9, T03 25, T04 132, T05 21, T06 11, T07 1, T08 105, T09 14, T10 178, T11 21, T12 25, T13 14, T14 7, T15 42, T16 10, T17 16, T18 37, T19 12, T20 2, T21 2.
- Full row-level projection: `handoff/T01-operation-owner-behavior-matrix-root-snapshot-20261001.csv`; SHA-256 `d58bf0a2e6891c0abec1ab7ff5cfaaafa7b6f53d9594501d5fcfb77ffa577974`; 685 rows. It retains required inputs, response fields, policy, test references, contract gaps and source evidence alongside assigned owner.
- The 537 unverified rows have owners: T01 1, T02 7, T03 14, T04 117, T05 15, T06 3, T08 70, T09 9, T10 171, T11 13, T12 19, T13 12, T14 4, T15 34, T16 3, T17 11, T18 24, T19 8, T20 2. T07 and T21 own zero unverified rows in this snapshot.
- Root-current owner patch: `handoff/T01-operation-owners-root-current.patch`; SHA-256 `7BB9B5B3EC5F4E02DD44C08EBFBDE0FDC17822482FF6AFFCF568642D1ADA4478`; `git apply --check` passed individually and with the schema-fallback patch concatenated (`handoff/T01-root-current-combined-check.patch`, SHA-256 `730E4333F245DCECCB192522DB93596A13F8D7B5744D1040694F378A54F52463`). Root preimages at check: generator `862731FDB1312D2B6A604A1EB7F2559C196EAC11985C032C091633DEA960A85C`, test `F58FD04FE2BD0C11D7F0374A9750EF74CFC628F8E5AB53A46A6A3DD4EBFD3F9B`, docs `E3B5A6559C5F0E6ADEC165B6A416E6DE600C7F00B121DA4615B176ABDA397A49`. Patch remains unapplied; no root tests or doc writes were run for owner projection.
- Deterministic ownership is a proposed work routing projection, not acceptance ownership or proof that assigned operation behavior passes. T20 should apply/merge only after source owners finish and then regenerate the root document from a stable snapshot.


## Alias proof and high-impact owner triage

- Static AST comparison found 23 candidate MCP alias rows and 23 source `_ACTION_ALIASES` entries; every alias/canonical pair and owner matches. Proof artifact: `handoff/T01-alias-source-proof-root-snapshot-20261001.csv`, SHA-256 `074A610FCED0515538A3D17DED4E31A87EB0608FA19CB3E68F31AA893C0155C8`. All 23 still lack asserted operation tests. Keep them inventoried; the static mapping proof does not prove dispatch behavior and is not a reason to prune a public alias.
- Owner triage artifact: `handoff/T01-unverified-high-impact-owner-triage-root-snapshot-20261001.csv`, 46 unverified operation/surface rows with direct-call evidence and owners, SHA-256 `364EE175A5F5CB2BC873ACB33A8A5C16E8717E4D3A80355BCA42CF8C18EE3552`. It now records one candidate receipt for T08 task rollback; the other rows remain unverified. The snapshot has no authoritative P0 field; these are high-impact review candidates, not certified P0s. Operation owners must supply actual acceptance evidence.
- T01 `/api/context/pack` is a registered dynamic `GET` owned by T01; registry note says source release is pending and T19's `POST` candidate behavior is excluded. This documents the inventory classification; no handler body or route source was changed, and behavior remains unverified.
- T09 typed command receipts remain pending the new receipt enum from T09. Inventory does not invent an enum or treat generic command output as a typed receipt. T20 owns root doc generation/check after route registry and mode fields stabilize; dashboard line-position changes must not drive dynamic route identity. No additional root `--check` or doc write was run in this continuation; the earlier stale-check receipt is recorded separately.
- Earlier 746-pass command included `tests/test_http_route_operation_acceptance.py`, whose fixture opens an ephemeral localhost socket (`127.0.0.1:0`); do not describe that run as port-free. After no-ports steering, two direct T08 task rollback selectors passed in 2.89 s without sockets: unknown `delete_all` returns 400 and leaves tasks/events empty; FastMCP `call_tool` dispatches `local_ai_coord` through `HubClient.coord` to real `Handler.do_POST`, restores a temp file snapshot, then a reopened SQLite `TaskStore` reads the prior checkpoint and `task.rolled_back` event. Candidate `collect_inventory` linked the exact behavior selector to `MCP action local_ai_coord::task_rollback`; its module origin was asserted under the candidate worktree. Exact selectors and import path assertions are in the test. Receipt: `handoff/T01-operation-level-receipts-candidate-20261001.csv`, SHA-256 `78E9F5E7C258B8E63C105CD515CF642C5B67EB4DE43756B66994D4F33665C192`.
- Incremental test patch: `handoff/T01-task-rollback-acceptance-incremental.patch`, SHA-256 `2BCE4ADEEDEECBCFFA92F421B7129027537143F95A978569904F493700567227`. Combined fallback + owner + test patch: `handoff/T01-root-current-with-task-rollback-check.patch`, SHA-256 `5F13DB93ACA13315A77BFEFE80350B51ED8C124489174A42DF7421129EA5D40D`; `git apply --check` passed. Root test-module preimage SHA-256 `303BB30536AD6BBF223C21738CBC482AF22539BEC09726CEF390D4CDF7F8FCFF`; candidate test module SHA-256 `6E63AA4324650F2AF8A6951284D8548EBC507FD393FED8409A31B797CC55F9A8`. No root tests or writes were done.


## T03 registry mismatches affecting behavioral acceptance

T03 completed a static root-source audit without edits or tests. T03 owns the source changes and focused registry tests below; this section records impact only and does not duplicate its prioritized contract-gap matrix.

| Operation | Handler inputs missing from registry | Focused acceptance still needed |
|---|---|---|
| `local_ai_status` | `adoption_signal`, `target_tool`, `target_action` | Registered dispatch accepts a valid bypass and rejects an incomplete target/action pair. |
| `local_ai_task` | `phase`, `focus`, `preload_profile`, `repository_revision`, `changed_paths` | Action-scoped `reason` accepts context fields; unrelated `cancel` rejects them. |
| `local_ai_repo` | `context_compile`: `include_diagnostics`, identity/revision fields; `pipeline`: `steps`; `preprocess`: `is_worktree`, `parent_root` | Valid action accepts its fields; unrelated `search` rejects them. |
| `local_ai_work` | `extra_fields` is present in the signature but unused | Keep out of registry; decide separately whether to remove the inactive signature parameter. |
| T21-owned route context | `path_hints` | Already represented in the contract; not a T01/T03 gap. |


## Reproducibility blocker before document parity

- Root generator fallback at `tools/surface_inventory.py:449` calls `load_config()` when the checked-out project has no `config.toml`, so `LOCAL_AI_CONFIG` or a developer home config can alter generated MCP schemas. T01 candidate instead requires project `defaults.toml` and loads it explicitly.
- Root generator SHA-256: `862731FDB1312D2B6A604A1EB7F2559C196EAC11985C032C091633DEA960A85C`; candidate generator SHA-256 after owner mapping: `0B961F07D24E1BEED1E7E234A87D166D4FF579AE7889FB5A058CD092F8E04D5C`.
- Candidate regression `test_schema_fallback_uses_project_defaults_not_ambient_config` passed in the targeted 2-test run above. Root-current source+test patch: `handoff/T01-schema-fallback-root-current.patch`, SHA-256 `893E913D470BC7395F7904F4ECD94BB57A33680FB844B6772D031E1EE548F85C`; `git apply --check` passed, root files stayed byte-identical, and patch is not applied.
- Do not run doc parity check/write until T20 resolves T03 registry changes and T19 docs parity. Then use one interpreter, root, env, and task ID for explicit `--write-doc` followed by `--check`.

