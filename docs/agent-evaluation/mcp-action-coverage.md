# Active MCP action coverage

Updated 2026-11-08. Source: active MCP tool schemas exposed to this session. This is a prompt coverage map, not execution evidence. Cases 114-129 were added but remain NOT_RUN until independently executed. Actions gated by profile or authorization are mapped to a negative/availability assertion; that does not count as a successful functional run.

## Tool-to-case map

| MCP tool | Active action(s) | Prompt |
|---|---|---:|
| local_ai_status | status call (no action field) | 114 |
| local_ai_artifact | get, slice, list, source | 114 |
| local_ai_rag | index, search, list, docset_index, docset_search, ingest_document, ingest_diagram | 121 |
| local_ai_work | status, wait, get, cancel | 128 |
| All seven tools | per-action input schema, validation, authorization, effect, output and failure branches | 129 |

## local_ai_repo

| Prompt | Actions explicitly in scope |
|---:|---|
| 115 | profile, search, map, code_index, deterministic, context, route, delegate, solve, review_diff, impact, refactor_impact, resolve_imports, audit_dependencies, ast_outline, git_status, repo_state, verify, affected_tests, topology, callers, callees, implementations, declaration, profile_digest, schema_inspect, explain_query, env_compat, circular_dependencies, dependency_slice, structural_search, context_budget, git_diff, diff, git_history_search, hotspots, cross_repo_contract, skeletonize, investigate, diagnose, briefing, semantic, intelligence, pipeline, call_graph, call_graph_diff, semantic_diff, cross_project_graph, cross_project_symbols, cross_project_impact, find_files, glob, git_log, file_info, stat, read_file, source, definition, references, find_references, find_symbol |
| 116 | generate_tests, validate_patch (validation-only input), test_matrix, security_audit, dead_code, secret_scan, reachability_dead_code, mutation_test, complexity, api_spec, migration_drift, package_audit |
| 117 | synthesize_commit, ast_refactor, generate_mocks, split_changes, synthesize_rules, code_invariants, generate_dataset, generate_types, type_stubs, generate_tests_for_diff, preprocess, preprocess_status, preprocess_refresh, preprocess_pause, preprocess_resume, preprocess_cancel, preprocess_unregister, patch, revert |

## local_ai_task

| Prompt | Active actions |
|---:|---|
| 118 | delegate, explore, reason, continue, review, second_opinion, compress, route, batch |
| 119 | benchmark, hardware_benchmark, evaluation_record, evaluation_report, eval_suite, prompt_eval, eval_drift, submit, status, wait, result, cancel |
| 120 | candidate_create, candidate_promote, speculative_draft, complete_code, scaffold, automation, browser, vision, transcribe |

## local_ai_coord

| Prompt | Active actions |
|---:|---|
| 122 | task_budget_increase, task_checkpoint, task_claim, task_cleanup_worktree, task_complete, task_create, task_fail, task_get, task_heartbeat, task_list, task_repair_session, task_resume, task_rollback, task_sync, task_transition, task_zombie_reap |
| 123 | context_compile, memory_delete, memory_find, memory_get, memory_promote, memory_record, negative_knowledge_find, negative_knowledge_record, record_native_receipt, session_briefing, verify_completion, verify_export, verify_receipt |
| 124 | board_item_create, board_item_delete, board_item_get, board_item_list, board_item_update, board_summary, milestone_create, milestone_status, plan_adopt_legacy_board, plan_archive, plan_bind_task, plan_board_view, plan_create, plan_get, plan_init, plan_list, plan_reconcile_steering, plan_task_delete, plan_task_edit, plan_update, plan_validate |
| 125 | answer, ask, blackboard_delete, blackboard_get, blackboard_list, blackboard_merge, blackboard_update, claim, leases, pubsub_poll, pubsub_publish, release, renew, semaphore_acquire, semaphore_release, semaphore_status, wait_for_event |
| 126 | simulate_merge, swarm_cancel, swarm_dispatch, swarm_list, swarm_status, swarm_step, worktree_lease, worktree_release |
| 127 | curate_dataset, gpu_reservation_release, gpu_reservation_release_authorized, gpu_reservation_status, incident_decision |

## Subfunction and branch dimensions

Each action in the tables above is tested separately in its prompt group. Compound groups must record a result per action; a group-level result cannot conceal a failed subfunction.

| Prompt | Subfunctions and branches the case must distinguish |
|---:|---|
| 114 | Tool status vs artifact retrieval; list/source/slice/get; root binding; offsets and size limits; exact file identity; missing/forbidden artifact errors. |
| 115 | Indexed vs lexical/degraded retrieval; path hints; pagination; symbol and caller/callee navigation; read-only Git facts; missing symbols and incomplete index. |
| 116 | Generation vs validation/reporting; test-matrix bounds; secret/dead-code/security findings; dependency and migration analysis; never infer runtime test execution. |
| 117 | Read-only vs mutating repo actions; approval/path guards; patch validation and rollback; preprocess register/status/pause/resume/cancel/unregister; unknown outcomes. |
| 118 | Model availability and route selection; reasoning vs evidence; review/second-opinion grounding; compression constraints; batch per-item isolation; truncation/backend failure. |
| 119 | Evaluation input validation; model/hardware gates; submit vs existing job lifecycle; stable IDs; one-shot wait/result/cancel; unknown, in-progress and timeout states. |
| 120 | Candidate creation vs promotion; consent/evidence gates; draft vs execution; generated-code scope; browser/network denial; image/audio capability and unsupported media. |
| 121 | Project index/search/list vs owner-global docsets; document/diagram ingestion; root/symlink confinement; empty/duplicate/malformed inputs; independent backend failures and cleanup. |
| 122 | Task create/claim/heartbeat/checkpoint/transition/resume/fail/complete/rollback; owner/session/revision checks; budget/repair/reap/cleanup gates; deadline and cancellation. |
| 123 | Memory find/get vs scoped mutations; canonical scope/provenance; compiled-context completeness; strict receipts and task/session matching; export/briefing identity. |
| 124 | Plan initialization/create/list/get/view/update/archive; task and board-item CRUD; milestone lifecycle; current vs stale revision; binding/reconciliation and incomplete responses. |
| 125 | Blackboard CAS/merge; pubsub payload and cursor; question/answer identity; lease owner/renew/release/expiry; semaphore exclusivity; wait timeout/cancel. |
| 126 | Swarm dispatch/step/status/cancel; worktree lease fencing and delete flag; merge simulation/conflict; authorized path and cleanup proof. |
| 127 | Dataset schema/receipt threshold; owner-global GPU status; release consent/reason/expiry/owner-death branches; malformed metadata fail-closed; incident provenance. |
| 128 | Existing work identity/scope; status/get/wait/cancel; artifact retrieval; unknown/in-progress/timed-out/cancelled states; no resubmit or duplicate polling. |
| 129 | For every live action: required/non-empty, action-scoped/forbidden fields, type/enum/bounds/defaults, feature/authorization gates, side-effect classification, output/failure branches and safe fixture behavior. |

## Authorization and side-effect gates

- `local_ai_status` and `local_ai_artifact` are read-only; artifact reads still require an authorized root/workspace and confined paths. Exact source reads may pin a file SHA; binary reads return bounded metadata.
- `local_ai_repo` actions inherit root/path confinement. Feature-gated actions include semantic/Serena and Agent OS cross-project operations. Repository-state effects are `patch`, `revert`, and preprocess register/refresh/pause/resume/cancel/unregister; they require disposable roots and mutation authorization. A generated suggestion is not an applied patch.
- `local_ai_task` is gated by model availability; `vision` has an additional vision capability gate. `submit` creates durable work; `evaluation_record` writes evaluation state; candidate actions write candidate state; automation mutates browser/desktop state. Promotion needs the candidate and approver fields and must remain isolated. Local model output is advisory evidence.
- `local_ai_rag` project indexing/search/ingestion requires an explicit authorized absolute root and bound workspace; docset actions use the separate owner-global namespace. Index/ingest mutates stored content and needs a new disposable scope.
- `local_ai_coord` feature gates include Agent OS. Memory mutations require explicit root/scope/provenance/record identity; plans use canonical root and expected revisions; task/session ownership and repository identity must match. GPU release requires consent plus audit reason and only expired/dead-owner or authorized-release paths. Lease owner is the actual task/execution, never credentials.
- `local_ai_work` exposes only status/wait/get/cancel in this active schema. Each operates on an existing work ID; submit/continue are absent and must be recorded UNAVAILABLE, never reached through another endpoint.
- The MCP/API token and server-side root authorization are independent of dashboard UI access. A visible endpoint or valid schema does not grant permission to mutate.

## Coverage interpretation and outstanding validation

- The action lists above were copied from the active schema, including profile-gated actions. Tool schema exposure is not proof that a backend is available or that an operation passed.
- Every listed action now has an explicit prompt case. Cases 114-129 are new coverage proposals and have no practical execution evidence yet.
- Prompt 129 is the field-level contract audit: record each live action's required/non-empty fields, conditional/action-scoped fields, type/enum/range/default constraints, feature/auth gates, effects, output schema, and relevant result branches. Source contracts can contain profile-gated actions absent from the live schema; use the live schema as the executed inventory and label absent actions UNAVAILABLE.
- Per-action declared fields and validator branches are indexed in mcp-action-contracts.md. It was reconciled against the active tool actions: 218 active rows, with repo batch_replace and work submit/continue source actions marked gated/unavailable.
- For code-backed schema parity, run tests/test_operation_contracts.py. That verifies declared/generated contracts for the covered operation-contract tools; it is not runtime evidence for every action or for tools outside that contract set.
- For a feature unavailable under this Hub profile, record BLOCKED/NOT_RUN with the returned reason. Do not infer a pass from an invalid-action probe, documentation, source inspection, or a successful unrelated action.
- Record each action's actual request, result, fixture identity and cleanup in results.md. For compound prompts, per-action status is required; an overall PASS requires every action in the prompt to pass.
- Full pytest is intentionally excluded. Run only the focused contract test and the smallest relevant fixture tests after preparing isolated fixtures.
