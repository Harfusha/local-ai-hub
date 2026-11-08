# MCP action scenario coverage

Updated 2026-11-08. This is a prompt coverage map, not execution evidence. Dedicated GPT-6 Luna prompt chats attempted cases 114-129; exact per-action runtime results are recorded in results.md, and most stateful branches remain NOT_RUN without isolated fixtures. Source-supported actions can be hidden by the current feature/profile schema; absence from one session means GATED/UNAVAILABLE for that run, not removed from the product or redundant in this catalog.

## Tool-to-case map

| MCP tool | Actions tested (some may be profile-gated) | Prompt |
|---|---|---:|
| local_ai_status | status call (no action field) | 114 |
| local_ai_artifact | get, slice, list, source | 114 |
| local_ai_rag | index, search, list, docset_index, docset_search, ingest_document, ingest_diagram | 121 |
| local_ai_work | submit, status, wait, get, continue, cancel | 128 |
| All seven tools | per-action input schema, validation, authorization, effect, output and failure branches | 129 |

## local_ai_repo

| Prompt | Actions explicitly in scope |
|---:|---|
| 115 | profile, search, map, code_index, deterministic, context, route, delegate, solve, review_diff, impact, refactor_impact, resolve_imports, audit_dependencies, ast_outline, git_status, repo_state, verify, affected_tests, topology, callers, callees, implementations, declaration, profile_digest, schema_inspect, explain_query, env_compat, circular_dependencies, dependency_slice, structural_search, context_budget, git_diff, diff, git_history_search, hotspots, cross_repo_contract, skeletonize, investigate, diagnose, briefing, semantic, intelligence, pipeline, call_graph, call_graph_diff, semantic_diff, cross_project_graph, cross_project_symbols, cross_project_impact, find_files, glob, git_log, file_info, stat, read_file, source, definition, references, find_references, find_symbol |
| 116 | generate_tests, validate_patch (validation-only input), test_matrix, security_audit, dead_code, secret_scan, reachability_dead_code, mutation_test, complexity, api_spec, migration_drift, package_audit |
| 117 | synthesize_commit, ast_refactor, generate_mocks, split_changes, synthesize_rules, code_invariants, generate_dataset, generate_types, type_stubs, generate_tests_for_diff, batch_replace (profile-gated), preprocess, preprocess_status, preprocess_refresh, preprocess_pause, preprocess_resume, preprocess_cancel, preprocess_unregister, patch, revert |

## local_ai_task

| Prompt | Actions in scenario scope |
|---:|---|
| 118 | delegate, explore, reason, continue, review, second_opinion, compress, route, batch |
| 119 | benchmark, hardware_benchmark, evaluation_record, evaluation_report, eval_suite, prompt_eval, eval_drift, submit, status, wait, result, cancel |
| 120 | candidate_create, candidate_promote, speculative_draft, complete_code, scaffold, automation, browser, vision, transcribe |

## local_ai_coord

| Prompt | Actions in scenario scope |
|---:|---|
| 122 | task_budget_increase, task_checkpoint, task_claim, task_cleanup_worktree, task_complete, task_create, task_fail, task_get, task_heartbeat, task_list, task_repair_session, task_resume, task_rollback, task_sync, task_transition, task_zombie_reap |
| 123 | context_compile, memory_delete, memory_find, memory_get, memory_promote, memory_record, negative_knowledge_find, negative_knowledge_record, record_native_receipt, session_briefing, verify_completion, verify_export, verify_receipt |
| 124 | board_item_create, board_item_delete, board_item_get, board_item_list, board_item_update, board_summary, milestone_create, milestone_status, plan_adopt_legacy_board, plan_archive, plan_bind_task, plan_board_view, plan_create, plan_get, plan_init, plan_list, plan_reconcile_steering, plan_task_delete, plan_task_edit, plan_update, plan_validate |
| 125 | answer, ask, blackboard_delete, blackboard_get, blackboard_list, blackboard_merge, blackboard_update, claim, leases, pubsub_poll, pubsub_publish, release, renew, semaphore_acquire, semaphore_release, semaphore_status, wait_for_event |
| 126 | simulate_merge, swarm_cancel, swarm_dispatch, swarm_list, swarm_status, swarm_step, worktree_lease, worktree_release |
| 127 | curate_dataset, gpu_reservation_release, gpu_reservation_release_authorized, gpu_reservation_status, incident_decision |

## Subfunction and branch dimensions

Each action in scope gets a separate result in its prompt group. If a source-supported action is hidden by the live schema, record its exact gate as GATED/UNAVAILABLE; do not delete the scenario or count it PASS. A group-level result cannot conceal a failed subfunction.

| Prompt | Subfunctions and branches the case must distinguish |
|---:|---|
| 114 | Tool status vs artifact retrieval; list/source/slice/get; root binding; offsets and size limits; exact file identity; missing/forbidden artifact errors. |
| 115 | Indexed vs lexical/degraded retrieval; path hints; pagination; symbol and caller/callee navigation; read-only Git facts; missing symbols and incomplete index. |
| 116 | Generation vs validation/reporting; test-matrix bounds; secret/dead-code/security findings; dependency and migration analysis; never infer runtime test execution. |
| 117 | Read-only vs mutating repo actions including gated batch_replace; approval/path guards; patch validation and rollback; preprocess lifecycle and fast-path traversal/symlink confinement; unknown outcomes. |
| 118 | Model availability and route selection; reasoning vs evidence; diff-grounded second opinion; compression fact retention; batch order/per-item failure; truncation/backend failure. |
| 119 | Evaluation input validation; model/hardware gates; frozen-set rubric and true-baseline drift; three-input 60-second cold/warm benchmark; stable IDs; one-shot wait/result/cancel; unknown/timeout states. |
| 120 | Candidate creation vs promotion; consent/evidence gates; draft vs execution; generated-code scope; browser/network denial; vision observation vs estimate; uncertain audio transcription. |
| 121 | Project index/search/list vs owner-global docsets; marker ingest/retrieval/provenance; document/diagram ingestion; root/symlink confinement; empty/duplicate/malformed inputs; independent backend failures and cleanup. |
| 122 | Task create/claim/heartbeat/checkpoint/transition/resume/fail/complete/rollback; reject untrusted false receipt, missing execution record and task mismatch; owner/session/revision checks; budget/repair/reap/cleanup gates; deadline and cancellation. |
| 123 | Memory find/get vs scoped mutations; reject missing/alias fields without writes; canonical scope/provenance; exact pagination of incomplete context artifacts; strict receipts and task/session matching; export/briefing identity. |
| 124 | Plan initialization/create/list/get/view/update/archive; task and board-item CRUD; milestone lifecycle; current vs stale revision; binding/reconciliation and incomplete responses. |
| 125 | Blackboard CAS/merge; pubsub payload and cursor; question/answer identity; lease owner/renew/release/expiry; semaphore exclusivity; wait timeout/cancel. |
| 126 | Swarm dispatch/step/status/cancel; worktree lease fencing and delete flag; merge simulation/conflict; authorized path and cleanup proof. |
| 127 | Dataset schema/receipt threshold; owner-global GPU status; release consent/reason/expiry/owner-death branches; malformed metadata fail-closed; incident provenance. |
| 128 | Synthetic work submission; existing work identity/scope; status/get/wait/continue/cancel; artifact retrieval; unknown/in-progress/timed-out/cancelled states; no duplicate polling. |
| 129 | Live endpoint inventory vs per-tool action enums, source snapshot/tests and profile gates; distinguish client-schema rejection from Hub pre-dispatch validation; falsey/missing `offset`, `include_code`, `query`; retired `tenant` rejection layer and request identity; no valid mutations. |

## Authorization and side-effect gates

- `local_ai_status` and `local_ai_artifact` are read-only; artifact reads still require an authorized root/workspace and confined paths. Exact source reads may pin a file SHA; binary reads return bounded metadata.
- `local_ai_repo` actions inherit root/path confinement. Feature-gated actions include semantic/Serena and Agent OS cross-project operations. Repository-state effects are `patch`, `revert`, and preprocess register/refresh/pause/resume/cancel/unregister; they require disposable roots and mutation authorization. A generated suggestion is not an applied patch.
- `local_ai_task` actions are filtered by current feature/profile and backend qualifications; evaluation recording writes evaluation state and candidate actions write candidate state. Promotion needs the candidate and approver fields and must remain isolated. Local model output is advisory evidence.
- `local_ai_rag` project indexing/search/ingestion requires an explicit authorized absolute root and bound workspace; docset actions use the separate owner-global namespace. Index/ingest mutates stored content and needs a new disposable scope.
- `local_ai_coord` feature gates include Agent OS. Memory mutations require explicit root/scope/provenance/record identity; plans use canonical root and expected revisions; task/session ownership and repository identity must match. GPU release requires consent plus audit reason and only expired/dead-owner or authorized-release paths. Lease owner is the actual task/execution, never credentials.
- `local_ai_work` currently exposes submit/status/wait/get/continue/cancel. Submit and continuation must use an isolated synthetic work item and the declared gates; do not substitute `local_ai_task` actions for these contracts.
- The MCP/API token and server-side root authorization are independent of dashboard UI access. A visible endpoint or valid schema does not grant permission to mutate.

## Coverage interpretation and outstanding validation

- The action lists above preserve source-supported operations, including profile-gated actions. Compare them with each run's live schema; schema exposure is not proof that a backend is available or that an operation passed.
- Actions absent from one session's live schema remain in scope when present in the source contract. Record the exact feature/profile gate as GATED/UNAVAILABLE for that run; do not delete the prompt branch or count it PASS.
- Every listed action now has an explicit prompt case. Cases 114-129 are new coverage proposals and have no practical execution evidence yet.
- Prompt 129 is the field-level contract audit: record each live action's required/non-empty fields, conditional/action-scoped fields, type/enum/range/default constraints, feature/auth gates, effects, output schema, and relevant result branches. Also reconcile source-supported actions absent from the live schema; record their exact gate as GATED/UNAVAILABLE without deleting their scenarios.
- Per-action declared fields and validator branches are indexed in mcp-action-contracts.md. That source-contract snapshot is not the current live action inventory; reconcile per-run availability against this schema before running a prompt.
- For code-backed schema parity, run tests/test_operation_contracts.py. That verifies declared/generated contracts for the covered operation-contract tools; it is not runtime evidence for every action or for tools outside that contract set.
- For a feature unavailable under this Hub profile, record BLOCKED/NOT_RUN with the returned reason. Do not infer a pass from an invalid-action probe, documentation, source inspection, or a successful unrelated action.
- Record each action's actual request, result, fixture identity and cleanup in results.md. For compound prompts, per-action status is required; an overall PASS requires every action in the prompt to pass.
- Full pytest is intentionally excluded. Run only the focused contract test and the smallest relevant fixture tests after preparing isolated fixtures.
