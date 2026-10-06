# T21 checkout synchronization — 2026-10-06

Status: committed integration candidate with known failing behavior/tests. Not release-ready.

## Ownership and pinned history

- Assigned worktree only: C:/Users/Adam/.codex/worktrees/t21-project-config/.local-ai-hub.
- Reused branch: codex/sync-t21-project-config-20261006.
- Master read once at start: 3c23c33d76c43043d839642c7b0d3e10ea444d67, merge of T13 b30a6dde. No chase of later master/T12 changes.
- Original pre-dirty-checkpoint HEAD: 824c9eb9, preserved at refs/heads/codex/checkpoint-t21-project-config-original-20261006.
- Existing dirty checkpoint: b568928b847b343db235e1a8368f10984855f5cb, refs/heads/codex/checkpoint-t21-project-config-dirty-20261006.
- All remaining ordinary untracked source/tests/docs/patch handoffs committed before merge: 7e578713, refs/heads/codex/checkpoint-t21-project-config-all-source-20261006.
- Pinned master ref: refs/heads/codex/checkpoint-t21-project-config-pinned-master-20261006.
- No stash, reset, clean, push, root checkout writes, master ref writes, new worktree or chat. Runtime/caches excluded. Historical handoff patches are archival source evidence, not instructions applied during this merge.
- Hub already failed terminally per user; native fallback explicitly authorized. No Hub retry/poll. Token-economizer setup script absent at configured skill paths; existing tools used. Native tests have normal import/test-fixture side effects; Python bytecode and pytest cache disabled.

## Conflict decisions

Reviewed 17 conflicted paths at hunk level, with independent read-only review of RAG/search.
Master project-config shared-worktree inheritance and scoped service search retained.
Master task owner, project-root, mutation generation, command/environment binding and fail-closed verification retained; core safety files match pinned master.
Master lazy RAG policy API, root identity, embedding-space isolation, uncertain reads and transactional pruning retained.
Removed auto-merged duplicate RAG prune-on-skip blocks, preventing mass deletion on disabled RAG.
Preserved T21 generation-aware RAG revision invalidation.
Combined master validated scoped search and directory hints with T21 policy resolution, invalid-policy/Git-inventory failure handling, inventory membership and candidate ordering; supplied settings to directory fallback.
Restored T21 MCP search-hint normalization before transport while retaining master timeout and forwarding contracts.
Kept T21 preprocess path/phase/config-digest hooks atop master preprocessing; no model-route redesign. Gemini/live preprocessing not exercised.
Removed remaining CodeGraph ignore references and duplicated TOML key.
Kept master /api/context/pack behavior; no T14 redesign.
Retained older T21-only test functions alongside master tests even where contracts disagree; their original bytes remain in checkpoint.

## Actual validation

First targeted command: ten files from final selection excluding tests/test_t11_rag_policy_consumer_rebased.py. Exit 1: 137 passed, 24 failed in 20.03s.
After merge fixes, final command:

```
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_path_hints.py tests/test_t21_project_config_preprocess.py tests/test_project_config_service_integration.py tests/test_client_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_verification_rules.py tests/test_t21_completion_root_binding.py tests/test_t19_codegraph_removal.py tests/test_t11_rag_policy_consumer_rebased.py
```

Exit 1: 143 passed, 25 failed in 16.74s. No full release suite.
git diff --check passed for merge-resolution edits. Staged comparison against pinned master passed for src/tests/docs and this note. An unrestricted staged check against pre-merge HEAD failed on inherited master artifact/log whitespace; those files were not rewritten. Core config/worktree/path-hint tests, completion-root binding and CodeGraph-removal selectors passed within this run.
No live Hub/model/Gemini, deployment or full release acceptance claimed.
Final ancestry, empty unmerged index and clean checkout are checked after committing this note.

## Outstanding behavior and contract conflicts

- Python fallback old metric names and fixtures conflict with master bounded-search API (3 failures); retained master truncation/read-error protocol.
- run_affected summary/uncertainty expectations remain incomplete (2 failures).
- Older repo_search hint candidate-window/telemetry assumptions disagree with master scoped-search flow (4 failures).
- Service-level missing inventory/invalid policy remains reported as success in retained tests (3 failures). Low-level search_paths policy enforcement is retained; service behavior needs owner follow-up.
- Client master supports hints on command as well as search; old search-only expectation fails. Embedded payload sanitization expectation also fails (2 failures).
- HTTP search fixture does not observe expected forwarded kwargs (1 failure).
- Six older verification tests lack current API/task-store/journal/binding contracts. Master safety was preserved; no weakening to make tests green.
- Four older RAG tests use unbound policy-key signature or expect destructive prune-on-skip. Preserved safer master semantics.
- Other preserved T21 candidate namespace/search-chain tests were not run in this merge check.
- Historical docs/receipts predate merge; this note is the current receipt and does not claim all preserved work is finished.

Failed test identifiers:

```
FAILED tests/test_t21_project_config_preprocess.py::test_python_search_fallback_has_independent_file_cap_and_metric
FAILED tests/test_t21_project_config_preprocess.py::test_python_fallback_truncation_requires_omitted_candidate_sentinel[1-False]
FAILED tests/test_t21_project_config_preprocess.py::test_python_fallback_truncation_requires_omitted_candidate_sentinel[2-True]
FAILED tests/test_project_config_service_integration.py::test_run_affected_applies_project_mapping_and_path_hints_safely
FAILED tests/test_project_config_service_integration.py::test_run_affected_fails_closed_when_uncertain_and_test_matrix_missing
FAILED tests/test_project_config_service_integration.py::test_repo_search_prioritizes_verified_project_path_hint_without_narrowing
FAILED tests/test_project_config_service_integration.py::test_repo_search_uses_explicit_request_hint_for_unindexed_file
FAILED tests/test_project_config_service_integration.py::test_repo_search_keeps_full_original_candidate_window_when_adding_hints
FAILED tests/test_project_config_service_integration.py::test_repo_search_hint_hit_does_not_skip_broader_results
FAILED tests/test_project_config_service_integration.py::test_repo_search_propagates_unavailable_git_inventory
FAILED tests/test_project_config_service_integration.py::test_repo_search_fails_closed_when_project_policy_cannot_load
FAILED tests/test_project_config_service_integration.py::test_repo_search_fails_closed_for_invalid_policy_without_index_candidates
FAILED tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_only
FAILED tests/test_client_path_hints.py::test_post_sanitizes_embedded_path_hints_and_drops_unsupported_routes
FAILED tests/test_mcp_repo_path_hints.py::test_api_search_forwards_path_hints_to_repo_search
FAILED tests/test_verification_rules.py::test_evaluate_project_completion_passes_rules_and_configured_commands
FAILED tests/test_verification_rules.py::test_completion_handler_does_not_mutate_task_when_receipts_fail
FAILED tests/test_verification_rules.py::test_http_task_completion_uses_project_verification_rules
FAILED tests/test_verification_rules.py::test_mcp_task_completion_enforces_project_verification_rules
FAILED tests/test_verification_rules.py::test_invalid_project_configuration_blocks_completion
FAILED tests/test_verification_rules.py::test_completion_handler_uses_persisted_receipts_and_completes_task
FAILED tests/test_t11_rag_policy_consumer_rebased.py::test_explicit_rag_ingestion_removes_policy_rejected_source_paths
FAILED tests/test_t11_rag_policy_consumer_rebased.py::test_project_rag_phase_skip_is_reported_without_indexing
FAILED tests/test_t11_rag_policy_consumer_rebased.py::test_rag_policy_digest_prunes_excluded_chunks_and_invalidates_identity
FAILED tests/test_t11_rag_policy_consumer_rebased.py::test_rag_skip_phase_prunes_rows_and_advances_workspace_identity
```

## Changed paths versus pinned master

- docs/PROJECT_CONFIGURATION.md
- docs/superpowers/specs/2026-09-25-t21-adapter-handoff.md
- handoff/T07-journal-observation-test-r1.patch
- handoff/T07-journal-observation-uncertainty-20261001.md
- handoff/T14-context-fixture-contract-repair-from-failing-preimage.patch
- handoff/T14-context-fixture-default.patch
- handoff/T21-api-search-path-hint-e2e-test-root-current-20261004.patch
- handoff/T21-completion-root-binding-20261001.md
- handoff/T21-completion-root-binding-test.patch
- handoff/T21-coordination-identity-20261001.md
- handoff/T21-coordination-identity-root-current.patch
- handoff/T21-mcp-path-hint-test-instrumentation-20261005.md
- handoff/T21-mcp-path-hint-test-instrumentation-root-current-20261005.patch
- handoff/T21-namespace-wrapper-tests-AE847F92E0F5.patch
- handoff/T21-path-hint-partial-metadata-root-current.patch
- handoff/T21-path-hint-search-owner-manifest-20261004.md
- handoff/T21-path-hints-public-search-20261001.patch
- handoff/T21-path-hints-t21-owned-root-current-20261004.patch
- handoff/T21-policy-identity-root-preflight-20261005.md
- handoff/T21-project-config-core-integration-20261002.md
- handoff/T21-project-config-module-20261002.patch
- handoff/T21-project-config-preprocess-tests-root-current-20261005.md
- handoff/T21-project-config-preprocess-tests-root-current-20261005.patch
- handoff/T21-project-config-resolver-t11-20261005.md
- handoff/T21-project-config-resolver-t11-20261005.patch
- handoff/T21-project-worktree-config-20261001.patch
- handoff/T21-project-worktree-config-20261002.patch
- handoff/T21-python-search-fallback-truncation-root-current-20261004.patch
- handoff/T21-real-worktree-identity-test.patch
- handoff/T21-root-current-20261002.patch
- handoff/T21-root-current-core-minimal.patch
- handoff/T21-root-current-core-patch-20261003.patch
- handoff/T21-root-current-core-project-config-20261005.md
- handoff/T21-root-current-core-project-config-20261005.patch
- handoff/T21-root-current-core-project-config-followup-20261005.md
- handoff/T21-root-current-core-project-config-followup-20261005.patch
- handoff/T21-root-current-handoff.md
- handoff/T21-root-current-mcp-search-hints.patch
- handoff/T21-root-current-owner-packet-20261004.md
- handoff/T21-root-current-path-config-search-only.patch
- handoff/T21-root-current-path-hints-packet-20261004.md
- handoff/T21-root-current-project-path-search.patch
- handoff/T21-root-current-search-recall-test.patch
- handoff/T21-root-equivalent-snapshot-receipt-20261005.md
- handoff/T21-root-hint-accepted-e2e-test-root98a9-20261001.patch
- handoff/T21-root-hint-candidates.patch
- handoff/T21-root-imports-fix.patch
- handoff/T21-root-journal-fixture.patch
- handoff/T21-root-search-scope.patch
- handoff/T21-root.patch
- handoff/T21-search-only-client-root-current.patch
- handoff/T21-search-policy-consumers-r1.md
- handoff/T21-search-recall-2026-10-01.md
- handoff/T21-stash0-core-reconcile.patch
- handoff/T21-stash0-orchestrator-preserve.snapshot.patch
- handoff/T21-verification-rules-ProjectSettings-root98a9-20261001.patch
- handoff/T21-worktree-precedence-root-current-tests.patch
- handoff/T21-worktree-search-preprocess-consumer-root-current.patch
- handoff/T21_root_current_verification_rules_annotation_test.py
- handoff/t21-path-hints-consumer.patch
- handoff/test_t21_root_search_recall.py
- handoff/validate_t21_root_verification_patch.py
- src/local_ai_hub/mcp_server.py
- src/local_ai_hub/preprocess.py
- src/local_ai_hub/project_policy_adapter.py
- src/local_ai_hub/rag.py
- src/local_ai_hub/repo_tools.py
- tests/test_agent_consistency.py
- tests/test_client_path_hints.py
- tests/test_client_transport.py
- tests/test_mcp_repo_path_hints.py
- tests/test_project_config.py
- tests/test_project_config_service_integration.py
- tests/test_project_path_hints.py
- tests/test_t11_rag_policy_consumer_rebased.py
- tests/test_t21_candidate_path_hint_worktree_e2e.py
- tests/test_t21_coordination_namespace_bridge.py
- tests/test_t21_project_config_preprocess.py
- tests/test_t21_search_policy_consumers.py
- tests/test_verification_rules.py
- handoff/T21-sync-integration-20261006.md (this note)
