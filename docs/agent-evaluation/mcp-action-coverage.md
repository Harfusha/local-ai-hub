# MCP action scenario coverage

Updated 2026-11-08. This is a prompt coverage map, not execution evidence. Dedicated GPT-6 Luna prompt chats attempted cases 114-134; exact per-action runtime results are recorded in results.md, and stateful branches remain NOT_RUN without isolated fixtures. Call an enum complete only with evidence of its provenance and completeness. If a complete enum omits an action, record UNAVAILABLE for that session; use GATED only with an evidenced feature/profile cause. If completeness is unknown, record NOT_VERIFIED. A source-supported read-only action explicitly named by a case may be called once to test callable-surface mismatch; rejection means UNAVAILABLE for that session, success proves the enum was incomplete. Never probe actions outside the case scope. Stateful or mutating actions require verified enum exposure and isolated state. None of these states means an action was removed from the product or is redundant in this catalog.

## Tool-to-case map

| MCP tool | Actions tested (some may be profile-gated) | Prompt |
|---|---|---:|
| local_ai_status | status call (no action field) | 114 |
| local_ai_artifact | get, slice, list, source | 114 |
| local_ai_rag | index, search, list, docset_index, docset_search, ingest_document, ingest_diagram | 121 |
| local_ai_work | source-supported submit, status, wait, get, continue, cancel; session exposure classified separately | 128, 134 |
| All seven tools | per-action input schema, validation, authorization, effect, output and failure branches | 129 |

## local_ai_repo

| Prompt | Actions explicitly in scope |
|---:|---|
| 010 | local_ai_repo.declaration |
| 011 | local_ai_repo.search, local_ai_repo.callers |
| 052 | local_ai_repo.code_index |
| 070 | local_ai_repo.map, local_ai_repo.search, local_ai_repo.preprocess |
| 115 | search, find_files, definition, references, callers, callees, stat, source, git_status, git_diff, git_history_search, profile, context |
| 116 | test_matrix, security_audit, dead_code, secret_scan, reachability_dead_code, complexity, api_spec, migration_drift, package_audit |
| 117 | synthesize_commit, ast_refactor, generate_mocks, split_changes, synthesize_rules, code_invariants, generate_dataset, generate_types, type_stubs, generate_tests_for_diff, batch_replace (source-only in current contract snapshot; call only if live enum exposes it), preprocess, preprocess_status, preprocess_refresh, preprocess_pause, preprocess_resume, preprocess_cancel, preprocess_unregister, patch, revert |
| 130 | deterministic, repo_state, profile_digest, ast_outline, topology, implementations, explain_query, schema_inspect, context_budget, structural_search, skeletonize, briefing, glob, git_log, file_info, read_file, find_references, find_symbol, pipeline |
| 131 | impact, refactor_impact, resolve_imports, affected_tests, audit_dependencies, env_compat, circular_dependencies, dependency_slice, hotspots, cross_repo_contract, semantic, intelligence, call_graph, call_graph_diff, semantic_diff, cross_project_graph, cross_project_symbols, cross_project_impact |
| 132 | delegate, solve, review_diff, generate_tests, validate_patch, mutation_test, investigate, diagnose, route, verify, diff |
| 133 | security_audit, dead_code, reachability_dead_code, complexity, api_spec, test_matrix (positive populated-source coverage) |

`operation_contracts.py` exposes 93 source `local_ai_repo` action names, all assigned to prompt cases. The contract snapshot contains 92 action rows; `batch_replace` is documented separately as source-only and remains a conditional branch in case 117. This is a prompt-to-source map, not per-session runtime evidence; each chat records live exposure and execution status separately.

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

Each action in scope gets a separate result in its prompt group. A complete live enum that omits an action means UNAVAILABLE for that session; attach an explicit feature/profile reason before calling it GATED. With a missing/incomplete enum, use NOT_VERIFIED; do not probe arbitrary candidates. Explicit, source-supported read-only case actions may be tested once to distinguish callable mismatch from true unavailability. Stateful or mutating actions require complete live exposure and isolated state. Never delete source-supported scenarios from this catalog because one session cannot expose them. A group-level result cannot conceal a failed subfunction.

| Prompt | Subfunctions and branches the case must distinguish |
|---:|---|
| 114 | Tool status vs artifact retrieval; list/source/slice/get; root binding; offsets and size limits; exact file identity; missing/forbidden artifact errors. |
| 115 | Indexed vs lexical/degraded retrieval; advertised enum vs callable subfunction mismatch; path hints; search limit/offset/returned_count/next_offset/has_more and bounded pagination; adjacent-page duplicate check; distinct count/coverage fields; symbol/caller/callee navigation; read-only Git facts; missing symbols, missing request IDs and incomplete/truncated index. |
| 116 | Advertised enum vs callable analysis actions; fixture-root containment; metadata-only stat for evidence paths; synthetic-secret redaction; zero-file/zero-finding is not clean without inventory; test-matrix bounds; dependency/migration missing-input errors; no runtime-coverage claim. |
| 117 | Source-supported read-only action vs advertised-enum mismatch; before/after proof gates; stateful actions require full enum and isolated checkout/Hub state; gated batch_replace; approval/path guards; patch/revert/preprocess lifecycle; symlink confinement; unknown outcomes. |
| 118 | Model readiness; route threshold vs deterministic short-circuit; distinguish selected ranges from selector invocation; diff-grounded second opinion; compression fact retention; batch order/per-item failure; live-schema/backend action mismatch; truncation/backend failure. |
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
| 129 | Live endpoint inventory vs active tool metadata; exact counts parsed from ALL_TOOLS when available; incomplete/missing enum = NOT_VERIFIED; source snapshot/tests and feature gates; falsey/missing `offset`, `include_code`, `query`; retired `tenant` rejection layer and request identity; no invalid-action probes or valid mutations. |
| 130 | Deterministic facts/structure and exact metadata/source reads; root confinement; `git_log` non-empty query, `limit`→`max_commits`, omitted optional `path`; pipeline order, per-action results, stale/truncated evidence. |
| 131 | Impact vs refactor impact vs affected tests; import/dependency slice and call graph; incomplete-index vs empty result; semantic backend gate; cross-project root identity and no implicit preprocess/indexing. |
| 132 | Evidence-grounded repo reasoning/review and route/verify/diff behavior; generated tests are suggestions only; validate_patch does not apply; mutation_test uses one explicit disposable target; unknown/partial results and no mutation. |

## Authorization and side-effect gates

- `local_ai_status` and `local_ai_artifact` are read-only; artifact reads still require an authorized root/workspace and confined paths. Exact source reads may pin a file SHA; binary reads return bounded metadata.
- `local_ai_repo` actions inherit root/path confinement. Feature-gated actions include semantic/Serena and Agent OS cross-project operations. Repository-state effects are `patch`, `revert`, and preprocess register/refresh/pause/resume/cancel/unregister; they require disposable roots and mutation authorization. A generated suggestion is not an applied patch.
- `local_ai_task` actions are filtered by current feature/profile and backend qualifications; evaluation recording writes evaluation state and candidate actions write candidate state. Promotion needs the candidate and approver fields and must remain isolated. Local model output is advisory evidence.
- `local_ai_rag` project indexing/search/ingestion requires an explicit authorized absolute root and bound workspace; docset actions use the separate owner-global namespace. Index/ingest mutates stored content and needs a new disposable scope.
- `local_ai_coord` feature gates include Agent OS. Memory mutations require explicit root/scope/provenance/record identity; plans use canonical root and expected revisions; task/session ownership and repository identity must match. GPU release requires consent plus audit reason and only expired/dead-owner or authorized-release paths. Lease owner is the actual task/execution, never credentials.
- The source contract lists `local_ai_work` actions submit/status/wait/get/continue/cancel; live exposure is per session. Cases 128 and 134 preserve lifecycle and availability coverage. Submit/continue are high-profile, feature/quality/permission-gated bounded work; never infer exposure or removal from the source list, and do not substitute `local_ai_task` actions for these contracts.
- Loopback transport, command/capability authorization, and server-side root authorization remain independent controls. A visible endpoint or valid schema does not grant permission to mutate.

## Coverage interpretation and outstanding validation

- The action lists above preserve source-supported operations, including profile-gated actions. Compare them with each run's live schema; schema exposure is not proof that a backend is available or that an operation passed.
- Actions absent from one session's complete live schema remain in scope when present in the source contract. Record UNAVAILABLE for that run, and record GATED only with evidence for the specific gate; do not delete the prompt branch or count it PASS. An incomplete/missing enum is NOT_VERIFIED.
- Every listed action now has an explicit prompt case. Round 12 chats for cases 130-132 remain NOT_VERIFIED where they lacked a complete live enum. Round 13 directly verified case 130 `git_log`; Round 14 verified its omitted-path/limit branch in the isolated chat. Round 15 ran case-130 `ast_outline`, `structural_search`, `profile_digest`, and a non-representative missing-path `file_info`; Round 16 ran `read_file` and exposed an extra repeated `file_info` call against the one-call rule. Overall case 130 remains PARTIAL. `profile_digest` exposed a missing-root adapter bug, now fixed and installed; the post-install live call reached its expected missing-profile-file branch. Case 131 ran four single-root actions but remains PARTIAL due incomplete import evidence and truncated affected-tests output; cross-project stays NOT_RUN. Case 132 GPU-dependent branches are GATED only while admission is unknown, with other model/fixture branches NOT_RUN or NOT_VERIFIED. Round 17 exercised the `validate_patch` valid and corrupt branches; both returned expected status fields, but the malformed query changed in transit, so its test vector is not fully verified.
- Case 130 must use the exact fixture path manifest, valid profile inputs, and a sanitized disposable root for broad `repo_state`/`topology`/`pipeline` actions. When no safe baseline check is supplied, HEAD/hash equality is NOT_VERIFIED; do not use shell or inspect a shared dirty diff to manufacture that evidence.
- Prompt 129 is the field-level contract audit: record each live action's required/non-empty fields, conditional/action-scoped fields, type/enum/range/default constraints, feature/auth gates, effects, output schema, and relevant result branches. Also reconcile source-supported actions absent from the live schema; record their exact gate as GATED/UNAVAILABLE without deleting their scenarios.
- Per-action declared fields and validator branches are indexed in mcp-action-contracts.md. That source-contract snapshot is not the current live action inventory; reconcile per-run availability against this schema before running a prompt.
- For code-backed schema parity, run tests/test_operation_contracts.py. That verifies declared/generated contracts for the covered operation-contract tools; it is not runtime evidence for every action or for tools outside that contract set.
- For a feature unavailable under this Hub profile, record BLOCKED/NOT_RUN with the returned reason. Do not infer a pass from an invalid-action probe, documentation, source inspection, or a successful unrelated action.
- Record each action's actual request, result, fixture identity and cleanup in results.md. For compound prompts, per-action status is required; an overall PASS requires every action in the prompt to pass.
- Full pytest is intentionally excluded. Run only the focused contract test and the smallest relevant fixture tests after preparing isolated fixtures.
- Round 17 also covered `validate_patch` input branches. The service now distinguishes Git-reported corrupt syntax from a syntactically valid but inapplicable patch. The isolated chat's malformed query differed from the supplied manifest, so it is not exact-vector proof; record the observed arguments and keep the case PARTIAL until a faithful fixture chat passes.
- Round 18 reproduced a `refactor_impact` / `call_graph` mismatch on qualified call edges and added a focused regression. The local focused file passes, but post-install isolated chats returned no expected edge from either direction; `code_index` was truncated with `freshness=not_checked`. Keep case 131 PARTIAL / NOT_VERIFIED until a fresh, complete index-bound runtime retest agrees; do not use `success=true` or zero results as completeness evidence. The prompt now explicitly captures coverage, index availability, freshness and truncation fields.
- Follow-up Round 18 also fixed `refactor_impact` to expose unknown risk and incomplete index freshness, and `call_graph` to propagate its callers/callees query metadata and failures. A faithful post-install prompt chat used exactly two calls and correctly returned NOT_VERIFIED, but the runtime index still did not expose the known caller. Thus prompt classification is verified; product graph correctness against current indexed data remains NOT_VERIFIED.
- A single read-only `preprocess_status` probe identified the current cause: background indexing was still running at 25% (`318/1921`, `complete=false`); the fixture consumer path was not reported. Do not infer missing call edges from this incomplete index, and do not poll or refresh it as part of the read-only case.
