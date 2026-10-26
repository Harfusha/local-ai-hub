"""Immutable selector table for existing HTTP POST handler branches."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RouteRule:
    route_id: str
    paths: frozenset[str]


POST_ROUTE_REGISTRY: tuple[RouteRule, ...] = (
    RouteRule('post_admin_mode_1', frozenset(('/api/admin/mode',))),
    RouteRule('post_bundle_import_1', frozenset(('/api/bundle/import',))),
    RouteRule('post_telemetry_tool_accounting_1', frozenset(('/api/telemetry/tool-accounting',))),
    RouteRule('post_work_orders_1', frozenset(('/api/work-orders',))),
    RouteRule('post_config_update_1', frozenset(('/api/config/update',))),
    RouteRule('post_browser_capability_1', frozenset(('/api/browser/capability',))),
    RouteRule('post_browser_capture_abandon_1', frozenset(('/api/browser/capture/stage', '/api/browser/capture/commit', '/api/browser/capture/abandon'))),
    RouteRule('post_browser_capture_1', frozenset(('/api/browser/capture',))),
    RouteRule('post_delegate_1', frozenset(('/api/delegate',))),
    RouteRule('post_conversations_continue_1', frozenset(('/api/conversations/continue',))),
    RouteRule('post_async_jobs_1', frozenset(('/api/async-jobs',))),
    RouteRule('post_agent_state_tasks_1', frozenset(('/api/agent-state/tasks',))),
    RouteRule('post_agent_state_memory_1', frozenset(('/api/agent-state/memory',))),
    RouteRule('post_agent_state_incidents_1', frozenset(('/api/agent-state/incidents',))),
    RouteRule('post_agent_state_verification_1', frozenset(('/api/agent-state/verification',))),
    RouteRule('post_agent_state_context_1', frozenset(('/api/agent-state/context',))),
    RouteRule('post_agent_state_learning_1', frozenset(('/api/agent-state/learning',))),
    RouteRule('post_agent_state_cleanup_1', frozenset(('/api/agent-state/cleanup',))),
    RouteRule('post_agent_state_blackboard_1', frozenset(('/api/agent-state/blackboard',))),
    RouteRule('post_agent_state_swarm_dispatch_1', frozenset(('/api/agent-state/swarm/dispatch',))),
    RouteRule('post_agent_state_swarm_step_1', frozenset(('/api/agent-state/swarm/step',))),
    RouteRule('post_agent_state_swarm_cancel_1', frozenset(('/api/agent-state/swarm/cancel',))),
    RouteRule('post_benchmark_run_1', frozenset(('/api/benchmark/run',))),
    RouteRule('post_delegate_repo_1', frozenset(('/api/delegate/repo',))),
    RouteRule('post_solve_repo_1', frozenset(('/api/solve/repo',))),
    RouteRule('post_route_1', frozenset(('/api/route',))),
    RouteRule('post_delegate_batch_1', frozenset(('/api/delegate/batch',))),
    RouteRule('post_review_1', frozenset(('/api/review',))),
    RouteRule('post_review_diff_1', frozenset(('/api/review/diff',))),
    RouteRule('post_reason_1', frozenset(('/api/reason',))),
    RouteRule('post_second_opinion_1', frozenset(('/api/second-opinion',))),
    RouteRule('post_compress_1', frozenset(('/api/compress',))),
    RouteRule('post_generate_tests_1', frozenset(('/api/generate_tests',))),
    RouteRule('post_patch_validate_1', frozenset(('/api/patch/validate',))),
    RouteRule('post_query_expand_1', frozenset(('/api/query/expand',))),
    RouteRule('post_audit_dependencies_1', frozenset(('/api/audit_dependencies',))),
    RouteRule('post_refactor_impact_1', frozenset(('/api/refactor_impact',))),
    RouteRule('post_resolve_imports_1', frozenset(('/api/resolve_imports',))),
    RouteRule('post_git_status_1', frozenset(('/api/git/status',))),
    RouteRule('post_repo_state_1', frozenset(('/api/repo/state',))),
    RouteRule('post_git_diff_1', frozenset(('/api/git/diff',))),
    RouteRule('post_git_history_search_1', frozenset(('/api/git/history_search',))),
    RouteRule('post_hotspots_1', frozenset(('/api/repo/hotspots',))),
    RouteRule('post_generate_tests_for_diff_1', frozenset(('/api/repo/generate_tests_for_diff',))),
    RouteRule('post_cross_repo_contract_1', frozenset(('/api/repo/cross_repo_contract',))),
    RouteRule('post_git_synthesize_commit_1', frozenset(('/api/git/synthesize_commit',))),
    RouteRule('post_test_matrix_1', frozenset(('/api/test_matrix',))),
    RouteRule('post_affected_tests_1', frozenset(('/api/repo/affected_tests',))),
    RouteRule('post_repo_topology_1', frozenset(('/api/repo/topology',))),
    RouteRule('post_ast_rename_1', frozenset(('/api/code/ast_rename',))),
    RouteRule('post_code_generate_mocks_1', frozenset(('/api/code/generate_mocks',))),
    RouteRule('post_security_audit_1', frozenset(('/api/security_audit',))),
    RouteRule('post_code_intelligence_query_1', frozenset(('/api/code-intelligence/query',))),
    RouteRule('post_code_ast_outline_1', frozenset(('/api/code/ast_outline',))),
    RouteRule('post_code_batch_replace_1', frozenset(('/api/code/batch_replace',))),
    RouteRule('post_maintenance_optimize_db_1', frozenset(('/api/maintenance/optimize_db',))),
    RouteRule('post_maintenance_purge_cache_1', frozenset(('/api/maintenance/purge_cache',))),
    RouteRule('post_maintenance_resolve_errors_1', frozenset(('/api/maintenance/resolve_errors',))),
    RouteRule('post_doctor_1', frozenset(('/api/doctor',))),
    RouteRule('post_code_symbol_1', frozenset(('/api/code/symbol',))),
    RouteRule('post_code_find_symbol_1', frozenset(('/api/code/find_symbol',))),
    RouteRule('post_code_find_declaration_1', frozenset(('/api/code/find_declaration',))),
    RouteRule('post_code_find_implementations_1', frozenset(('/api/code/find_implementations',))),
    RouteRule('post_code_find_referencing_symbols_1', frozenset(('/api/code/find_referencing_symbols',))),
    RouteRule('post_code_symbols_overview_1', frozenset(('/api/code/symbols_overview',))),
    RouteRule('post_code_diagnostics_1', frozenset(('/api/code/diagnostics',))),
    RouteRule('post_code_intelligence_control_1', frozenset(('/api/code-intelligence/control',))),
    RouteRule('post_complete_1', frozenset(('/api/complete',))),
    RouteRule('post_preprocess_1', frozenset(('/api/preprocess',))),
    RouteRule('post_dead_code_1', frozenset(('/api/repo/dead_code',))),
    RouteRule('post_symbol_callgraph_1', frozenset(('/api/symbol_callgraph',))),
    RouteRule('post_cross_project_graph_1', frozenset(('/api/cross_project_graph',))),
    RouteRule('post_cross_project_symbols_1', frozenset(('/api/cross_project_symbols',))),
    RouteRule('post_cross_project_impact_1', frozenset(('/api/cross_project_impact',))),
    RouteRule('post_repo_call_graph_diff_1', frozenset(('/api/repo/call_graph_diff',))),
    RouteRule('post_bundle_export_1', frozenset(('/api/bundle/export',))),
    RouteRule('post_benchmark_1', frozenset(('/api/benchmark',))),
    RouteRule('post_evaluation_1', frozenset(('/api/evaluation',))),
    RouteRule('post_repo_profile_1', frozenset(('/api/repo/profile',))),
    RouteRule('post_repo_map_1', frozenset(('/api/repo/map',))),
    RouteRule('post_repo_code_index_1', frozenset(('/api/repo/code-index',))),
    RouteRule('post_repo_investigate_1', frozenset(('/api/repo/investigate',))),
    RouteRule('post_repo_diagnose_1', frozenset(('/api/repo/diagnose',))),
    RouteRule('post_repo_briefing_1', frozenset(('/api/repo/briefing',))),
    RouteRule('post_repo_deterministic_1', frozenset(('/api/repo/deterministic',))),
    RouteRule('post_repo_impact_1', frozenset(('/api/repo/impact',))),
    RouteRule('post_search_1', frozenset(('/api/search',))),
    RouteRule('post_artifact_get_1', frozenset(('/api/artifact/get',))),
    RouteRule('post_artifact_list_1', frozenset(('/api/artifact/list',))),
    RouteRule('post_evidence_verify_1', frozenset(('/api/evidence/verify',))),
    RouteRule('post_evidence_get_1', frozenset(('/api/evidence/get',))),
    RouteRule('post_leases_claim_1', frozenset(('/api/leases/claim_batch',))),
    RouteRule('post_leases_release_1', frozenset(('/api/leases/release',))),
    RouteRule('post_leases_renew_1', frozenset(('/api/leases/renew',))),
    RouteRule('post_memory_put_1', frozenset(('/api/memory/put',))),
    RouteRule('post_memory_get_1', frozenset(('/api/memory/get',))),
    RouteRule('post_memory_search_1', frozenset(('/api/memory/search',))),
    RouteRule('post_memory_delete_1', frozenset(('/api/memory/delete',))),
    RouteRule('post_embed_1', frozenset(('/api/embed',))),
    RouteRule('post_rerank_1', frozenset(('/api/rerank',))),
    RouteRule('post_rag_index_1', frozenset(('/api/rag/index',))),
    RouteRule('post_rag_search_1', frozenset(('/api/rag/search',))),
    RouteRule('post_speculative_draft_1', frozenset(('/api/task/speculative_draft',))),
    RouteRule('post_scaffold_1', frozenset(('/api/task/scaffold',))),
    RouteRule('post_db_query_1', frozenset(('/api/db/query',))),
    RouteRule('post_models_manage_1', frozenset(('/api/models/manage',))),
    RouteRule('post_reachability_dead_code_1', frozenset(('/api/repo/reachability_dead_code',))),
    RouteRule('post_mutation_test_1', frozenset(('/api/repo/mutation_test',))),
    RouteRule('post_repo_type_stubs_1', frozenset(('/api/repo/type_stubs',))),
    RouteRule('post_repo_skeletonize_1', frozenset(('/api/repo/skeletonize',))),
    RouteRule('post_agent_state_events_delta_1', frozenset(('/api/agent-state/events/delta',))),
    RouteRule('post_task_vision_1', frozenset(('/api/task/vision', '/api/vision', '/api/vision/review'))),
    RouteRule('post_task_browser_1', frozenset(('/api/task/browser',))),
    RouteRule('post_task_automation_1', frozenset(('/api/task/automation',))),
    RouteRule('post_repo_split_changes_1', frozenset(('/api/repo/split_changes',))),
    RouteRule('post_repo_synthesize_rules_1', frozenset(('/api/repo/synthesize_rules',))),
    RouteRule('post_rag_docset_index_1', frozenset(('/api/rag/docset/index',))),
    RouteRule('post_rag_docset_search_1', frozenset(('/api/rag/docset/search',))),
    RouteRule('post_telemetry_timeline_1', frozenset(('/api/telemetry/timeline',))),
    RouteRule('post_task_transcribe_1', frozenset(('/api/task/transcribe',))),
    RouteRule('post_code_invariants_1', frozenset(('/api/repo/code_invariants',))),
    RouteRule('post_generate_dataset_1', frozenset(('/api/repo/generate_dataset',))),
    RouteRule('post_profile_digest_1', frozenset(('/api/repo/profile_digest',))),
    RouteRule('post_coord_worktree_lease_1', frozenset(('/api/coord/worktree_lease',))),
    RouteRule('post_coord_worktree_release_1', frozenset(('/api/coord/worktree_release',))),
    RouteRule('post_coord_worktrees_1', frozenset(('/api/coord/worktrees',))),
    RouteRule('post_coord_worktree_prune_1', frozenset(('/api/coord/worktree_prune',))),
    RouteRule('post_callers_1', frozenset(('/api/repo/callers',))),
    RouteRule('post_callees_1', frozenset(('/api/code/callees',))),
    RouteRule('post_repo_patch_1', frozenset(('/api/repo/patch',))),
    RouteRule('post_repo_call_graph_1', frozenset(('/api/repo/call_graph',))),
    RouteRule('post_repo_git_status_1', frozenset(('/api/repo/git_status',))),
    RouteRule('post_repo_revert_1', frozenset(('/api/repo/revert',))),
    RouteRule('post_repo_find_files_1', frozenset(('/api/repo/find_files',))),
    RouteRule('post_repo_file_info_1', frozenset(('/api/repo/file_info',))),
    RouteRule('post_implementations_1', frozenset(('/api/code/implementations',))),
    RouteRule('post_declaration_1', frozenset(('/api/code/declaration',))),
    RouteRule('post_repo_secret_scan_1', frozenset(('/api/repo/secret_scan',))),
    RouteRule('post_repo_schema_inspect_1', frozenset(('/api/repo/schema_inspect',))),
    RouteRule('post_explain_query_1', frozenset(('/api/repo/explain_query',))),
    RouteRule('post_env_compat_1', frozenset(('/api/repo/env_compat',))),
    RouteRule('post_coord_pubsub_publish_1', frozenset(('/api/coord/pubsub_publish',))),
    RouteRule('post_coord_pubsub_poll_1', frozenset(('/api/coord/pubsub_poll',))),
    RouteRule('post_coord_simulate_merge_1', frozenset(('/api/coord/simulate_merge',))),
    RouteRule('post_coord_wait_for_event_1', frozenset(('/api/coord/wait_for_event',))),
    RouteRule('post_coord_semaphore_acquire_1', frozenset(('/api/coord/semaphore_acquire',))),
    RouteRule('post_coord_semaphore_release_1', frozenset(('/api/coord/semaphore_release',))),
    RouteRule('post_coord_semaphore_status_1', frozenset(('/api/coord/semaphore_status',))),
    RouteRule('post_coord_board_item_create_1', frozenset(('/api/coord/board_item_create',))),
    RouteRule('post_coord_board_item_update_1', frozenset(('/api/coord/board_item_update',))),
    RouteRule('post_coord_board_item_get_1', frozenset(('/api/coord/board_item_get',))),
    RouteRule('post_coord_board_item_delete_1', frozenset(('/api/coord/board_item_delete',))),
    RouteRule('post_coord_board_item_list_1', frozenset(('/api/coord/board_item_list',))),
    RouteRule('post_coord_board_summary_1', frozenset(('/api/coord/board_summary',))),
    RouteRule('post_coord_milestone_create_1', frozenset(('/api/coord/milestone_create',))),
    RouteRule('post_coord_milestone_status_1', frozenset(('/api/coord/milestone_status',))),
    RouteRule('post_coord_session_briefing_1', frozenset(('/api/coord/session_briefing',))),
    RouteRule('post_eval_suite_1', frozenset(('/api/task/eval_suite',))),
    RouteRule('post_prompt_eval_1', frozenset(('/api/task/prompt_eval',))),
    RouteRule('post_eval_drift_1', frozenset(('/api/task/eval_drift',))),
    RouteRule('post_circular_dependencies_1', frozenset(('/api/repo/circular_dependencies',))),
    RouteRule('post_generate_types_1', frozenset(('/api/repo/generate_types',))),
    RouteRule('post_complexity_1', frozenset(('/api/repo/complexity',))),
    RouteRule('post_api_spec_1', frozenset(('/api/repo/api_spec',))),
    RouteRule('post_dependency_slice_1', frozenset(('/api/repo/dependency_slice',))),
    RouteRule('post_migration_drift_1', frozenset(('/api/repo/migration_drift',))),
    RouteRule('post_package_audit_1', frozenset(('/api/repo/package_audit',))),
    RouteRule('post_repo_structural_search_1', frozenset(('/api/repo/structural_search',))),
    RouteRule('post_context_budget_1', frozenset(('/api/repo/context_budget',))),
    RouteRule('post_context_pack_1', frozenset(('/api/context/pack',))),
    RouteRule('post_ingest_document_1', frozenset(('/api/rag/ingest_document',))),
    RouteRule('post_ingest_diagram_1', frozenset(('/api/rag/ingest_diagram',))),
    RouteRule('post_chat_1', frozenset(('/api/generate', '/api/chat', '/api/embed'))),
)


POST_ROUTE_HANDLER_BOUNDARIES: Mapping[str, str] = MappingProxyType({
    "post_work_orders_1": "_handle_post_work_orders",
    "post_async_jobs_1": "_handle_post_async_jobs",
    "post_db_query_1": "_handle_post_db_query",
    "post_telemetry_timeline_1": "_handle_post_telemetry_timeline",
    "post_git_status_1": "_handle_post_repository_analysis",
    "post_repo_state_1": "_handle_post_repository_analysis",
    "post_git_diff_1": "_handle_post_repository_analysis",
    "post_git_history_search_1": "_handle_post_repository_analysis",
    "post_hotspots_1": "_handle_post_repository_analysis",
    "post_test_matrix_1": "_handle_post_repository_analysis",
})


GET_ROUTE_HANDLER_BOUNDARIES: Mapping[str, str] = MappingProxyType({
    "/api/live": "_handle_get_live",
    "/api/live/status": "_handle_get_live_status",
})

# Exact, non-parameterized GET labels safe to retain in telemetry. Dynamic
# prefixes stay redacted; tests compare this set with source-discovered routes.
TELEMETRY_SAFE_GET_ROUTE_LABELS = frozenset({
    "/",
    "/api/adoption",
    "/api/agent-state/events",
    "/api/agent-state/events/stream",
    "/api/agent-state/swarm",
    "/api/audit/tail",
    "/api/benchmark/summary",
    "/api/capabilities",
    "/api/config",
    "/api/debug-traces",
    "/api/hardware/gpu",
    "/api/hardware/system",
    "/api/leases",
    "/api/logs/tail",
    "/api/metrics",
    "/api/mode",
    "/api/models",
    "/api/preprocess/status",
    "/api/project/config",
    "/api/rag/workspaces",
    "/api/status",
    "/api/telemetry/report",
    "/dashboard",
    "/favicon.ico",
    "/health",
    "/ready",
})


def select_get_handler(path: str) -> str | None:
    """Resolve T18-owned exact GET paths to named handlers."""
    return GET_ROUTE_HANDLER_BOUNDARIES.get(str(path))


def select_post_handler(route_ids: tuple[str, ...]) -> str | None:
    """Resolve extracted IDs to named handlers; unmigrated IDs stay on legacy dispatch."""
    for route_id in route_ids:
        handler_name = POST_ROUTE_HANDLER_BOUNDARIES.get(route_id)
        if handler_name is not None:
            return handler_name
    return None


def select_http_routes(method: str, path: str) -> tuple[str, ...]:
    """Return matching POST branch IDs in legacy source order. Caller supplies parsed URL path."""
    if str(method).upper() != "POST":
        return ()
    normalized_path = str(path)
    return tuple(
        rule.route_id
        for rule in POST_ROUTE_REGISTRY
        if normalized_path in rule.paths
    )
