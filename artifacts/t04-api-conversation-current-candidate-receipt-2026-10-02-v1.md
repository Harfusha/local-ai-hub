# T04 current-candidate API and conversation receipt

Date: 2026-10-02 (Europe/Prague)
Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Branch: `codex/t04-integration-2b33602`

## Exact command

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_public_api_contracts.py tests/test_conversations.py tests/test_conversation_continue_route_contract.py::test_hub_client_continues_through_production_route_and_preserves_transcript tests/test_conversation_continue_route_contract.py::test_expired_conversation_is_terminal_through_production_route tests/test_conversation_continue_route_contract.py::test_competing_continuation_is_retryable_in_progress_through_production_route tests/test_mcp_agent_routing.py::test_local_ai_task_forwards_continue_with_opaque_conversation_id tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code tests/test_mcp_agent_routing.py::test_repo_review_diff_returns_foreground_result_by_default tests/test_agent_tasks.py::test_task_query_bounds_rows_scanned tests/test_agent_tasks.py::test_task_query_scan_window_is_bounded_before_stale_filter tests/test_agent_tasks.py::test_task_query_skips_stale_candidate_before_page_limit tests/test_surface_inventory.py::test_inventory_extracts_surfaces_and_resolves_dynamic_route_registry
```

Result: **40 passed in 49.27s**, exit 0. This includes resolve-imports defaults, unsupported chat completions, bounded tenant-isolated artifact listing, include-code forwarding, semantic diff routing, RAG/work controls, conversation continuation/expiry/concurrency, task-query bounds, review delivery, and API inventory.

The current candidate source/test pins match the existing full assigned-suite receipt: **133 passed in 27.74s**, log SHA-256 `46B51D4C7733C8E335EF885DC5F0B1F8709A818068219A7CE0AC9B4C3A0DABFF`. Core pins checked on this candidate include `client.py` `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`, `mcp_server.py` `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`, and `test_t04_public_api_contracts.py` `AAFA9BF5713002C32EFDDE7D0CA77CFD7CD11CA9D38220F95B40BC8BF226ADFB`.

## Boundary

This is candidate-worktree evidence. It does not claim root integration acceptance. The T04 candidate still lacks the T03-owned public MCP `path_hints` wrapper hunk; T20 owns root verification of that current-root chain. No production source changed in this test turn.
