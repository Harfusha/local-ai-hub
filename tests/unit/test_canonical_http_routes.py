from __future__ import annotations

import pytest

from local_ai_hub.http_route_registry import POST_ROUTE_REGISTRY, select_http_routes


_CANONICAL_ROUTES_WITH_ALIASES = (
    ("post_command_speculative_lint_1", "/api/command/speculative-lint", ("/api/speculative-lint",)),
    ("post_repo_state_1", "/api/repo/state", ("/api/repo_state",)),
    ("post_hotspots_1", "/api/repo/hotspots", ("/api/hotspots",)),
    ("post_generate_tests_for_diff_1", "/api/repo/generate_tests_for_diff", ("/api/generate_tests_for_diff",)),
    ("post_cross_repo_contract_1", "/api/repo/cross_repo_contract", ("/api/cross_repo_contract",)),
    ("post_affected_tests_1", "/api/repo/affected_tests", ("/api/affected_tests",)),
    ("post_repo_topology_1", "/api/repo/topology", ("/api/topology",)),
    ("post_ast_rename_1", "/api/code/ast_rename", ("/api/ast_rename",)),
    ("post_code_generate_mocks_1", "/api/code/generate_mocks", ("/api/generate_mocks",)),
    ("post_code_batch_replace_1", "/api/code/batch_replace", ("/api/repo/batch_replace",)),
    ("post_dead_code_1", "/api/repo/dead_code", ("/api/dead_code",)),
    ("post_speculative_draft_1", "/api/task/speculative_draft", ("/api/speculative_draft",)),
    ("post_scaffold_1", "/api/task/scaffold", ("/api/scaffold",)),
    ("post_reachability_dead_code_1", "/api/repo/reachability_dead_code", ("/api/reachability_dead_code",)),
    ("post_mutation_test_1", "/api/repo/mutation_test", ("/api/mutation_test",)),
    ("post_repo_type_stubs_1", "/api/repo/type_stubs", ("/api/type_stubs",)),
    ("post_repo_skeletonize_1", "/api/repo/skeletonize", ("/api/skeletonize",)),
    ("post_repo_split_changes_1", "/api/repo/split_changes", ("/api/split_changes",)),
    ("post_repo_synthesize_rules_1", "/api/repo/synthesize_rules", ("/api/synthesize_rules",)),
    ("post_rag_docset_index_1", "/api/rag/docset/index", ("/api/rag/docset_index",)),
    ("post_rag_docset_search_1", "/api/rag/docset/search", ("/api/rag/docset_search",)),
    ("post_task_transcribe_1", "/api/task/transcribe", ("/api/transcribe",)),
    ("post_code_invariants_1", "/api/repo/code_invariants", ("/api/code_invariants",)),
    ("post_generate_dataset_1", "/api/repo/generate_dataset", ("/api/generate_dataset",)),
    ("post_profile_digest_1", "/api/repo/profile_digest", ("/api/profile_digest",)),
    ("post_coord_worktree_lease_1", "/api/coord/worktree_lease", ("/api/worktree_lease",)),
    ("post_coord_worktree_release_1", "/api/coord/worktree_release", ("/api/worktree_release",)),
    ("post_coord_worktrees_1", "/api/coord/worktrees", ("/api/worktrees",)),
    ("post_coord_worktree_prune_1", "/api/coord/worktree_prune", ("/api/worktree_prune",)),
    ("post_command_daemon_1", "/api/command/daemon", ("/api/daemon",)),
    ("post_command_lint_fix_1", "/api/command/lint_fix", ("/api/lint_fix",)),
    ("post_command_http_probe_1", "/api/command/http_probe", ("/api/http_probe",)),
    ("post_callers_1", "/api/repo/callers", ("/api/callers",)),
    ("post_callees_1", "/api/code/callees", ("/api/repo/callees", "/api/callees")),
    ("post_implementations_1", "/api/code/implementations", ("/api/repo/implementations", "/api/implementations")),
    ("post_declaration_1", "/api/code/declaration", ("/api/repo/declaration", "/api/declaration")),
    ("post_repo_secret_scan_1", "/api/repo/secret_scan", ("/api/secret_scan",)),
    ("post_repo_schema_inspect_1", "/api/repo/schema_inspect", ("/api/schema_inspect",)),
    ("post_explain_query_1", "/api/repo/explain_query", ("/api/explain_query",)),
    ("post_env_compat_1", "/api/repo/env_compat", ("/api/env_compat",)),
    ("post_coord_pubsub_publish_1", "/api/coord/pubsub_publish", ("/api/pubsub_publish",)),
    ("post_coord_pubsub_poll_1", "/api/coord/pubsub_poll", ("/api/pubsub_poll",)),
    ("post_coord_simulate_merge_1", "/api/coord/simulate_merge", ("/api/simulate_merge",)),
    ("post_eval_suite_1", "/api/task/eval_suite", ("/api/eval_suite",)),
    ("post_prompt_eval_1", "/api/task/prompt_eval", ("/api/prompt_eval",)),
    ("post_eval_drift_1", "/api/task/eval_drift", ("/api/eval_drift",)),
    ("post_circular_dependencies_1", "/api/repo/circular_dependencies", ("/api/circular_dependencies",)),
    ("post_generate_types_1", "/api/repo/generate_types", ("/api/generate_types",)),
    ("post_complexity_1", "/api/repo/complexity", ("/api/complexity",)),
    ("post_api_spec_1", "/api/repo/api_spec", ("/api/api_spec",)),
    ("post_dependency_slice_1", "/api/repo/dependency_slice", ("/api/dependency_slice",)),
    ("post_migration_drift_1", "/api/repo/migration_drift", ("/api/migration_drift",)),
    ("post_package_audit_1", "/api/repo/package_audit", ("/api/package_audit",)),
    ("post_repo_structural_search_1", "/api/repo/structural_search", ("/api/structural_search",)),
    ("post_context_budget_1", "/api/repo/context_budget", ("/api/context_budget",)),
    ("post_ingest_document_1", "/api/rag/ingest_document", ("/api/ingest_document",)),
    ("post_ingest_diagram_1", "/api/rag/ingest_diagram", ("/api/ingest_diagram",)),
    ("post_command_mock_server_1", "/api/command/mock_server", ("/api/mock_server",)),
    ("post_command_diff_hunk_stage_1", "/api/command/diff_hunk_stage", ("/api/diff_hunk_stage",)),
    ("post_command_flaky_detect_1", "/api/command/flaky_detect", ("/api/flaky_detect",)),
    ("post_command_webhook_replay_1", "/api/command/webhook_replay", ("/api/webhook_replay",)),
)


@pytest.mark.parametrize("route_id,canonical,aliases", _CANONICAL_ROUTES_WITH_ALIASES)
def test_only_canonical_endpoint_is_registered(
    route_id: str, canonical: str, aliases: tuple[str, ...]
) -> None:
    assert select_http_routes("POST", canonical) == (route_id,)
    for alias in aliases:
        assert select_http_routes("POST", alias) == ()


def test_remaining_multi_path_rules_are_distinct_operations() -> None:
    multi_path_rules = {rule.route_id for rule in POST_ROUTE_REGISTRY if len(rule.paths) > 1}

    assert multi_path_rules == {
        "post_browser_capture_abandon_1",
        "post_leases_claim_1",
        "post_task_vision_1",
        "post_chat_1",
    }
    for path in (
        "/api/browser/capture/stage",
        "/api/browser/capture/commit",
        "/api/browser/capture/abandon",
        "/api/leases/claim",
        "/api/leases/claim_batch",
        "/api/task/vision",
        "/api/vision",
        "/api/vision/review",
        "/api/generate",
        "/api/chat",
        "/api/embed",
    ):
        assert select_http_routes("POST", path)
