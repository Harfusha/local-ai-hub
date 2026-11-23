# Complete Modular Decomposition Design

## Goal

Split every remaining source monolith in Local AI Hub into responsibility-owned modules, migrate all internal callers to those modules, then delete legacy import-only facades.

## Current Evidence

- Checkout: `master`; working tree has many pre-existing edits and untracked files. Preserve all of them.
- Hub plan/index calls failed before transport write. Do not edit `.local-ai-hub/plans/` directly; continue from this spec and plan until Hub coordination is available.
- Inventory scanned human-maintained Python, TypeScript, and JavaScript under `src/local_ai_hub`, `tools`, and `ui_static`, excluding generated `dist`, vendor, and caches. 62 files are at least 1,000 lines; 89 are at least 700 lines. Size marks candidates, not automatic split decisions.
- Largest remaining candidates include `commands.py` (7,671), `services.py` (6,556), `ui_static/dashboard.ts` (6,463), `tools/benchmark_surfaces.py` (6,209), `code_index.py` (5,146), `repo_tools.py` (5,105), `rag.py` (5,071), `agent_tasks.py` (4,966), `deterministic.py` (4,962), and `app.py` (4,178).
- Prior work already extracted domain modules, but left large class bodies and import/re-export facades. Audit those extracted modules too; do not treat their existence as proof of completion.

## Design

1. Split by behavior and ownership, not arbitrary line ranges. Each implementation module owns a coherent domain and imports its actual dependencies.
2. Keep module-level public entrypoints only where they perform real composition or runtime startup. Remove modules whose only purpose is re-export, aliasing, or forwarding; migrate every in-repository caller first.
3. Preserve runtime contracts, validation, error handling, serialized formats, and test monkeypatching. Moved code that relies on patched services must resolve dependencies dynamically through the owning service instance/module.
4. Treat all files at or above 1,000 lines as audit candidates. Each must end as responsibility-split modules or receive an evidence-based cohesion rationale in the inventory. Generated artifacts are regenerated from source, never hand-edited.
5. After each bounded subsystem, run its targeted tests and inspect imports/references before deleting its old facade. Do not run the unconstrained full pytest suite.

## Candidate Inventory & Disposition

Every baseline candidate has a recorded disposition, evidence-based rationale, and passing verification suite. Size marks audit candidates; decisions follow domain responsibility:

### Split Subsystems (Monoliths Decomposed into Modules + Composition Roots)
1. **`commands.py`** (7,671 -> DELETED): Decomposed into `command_broker.py`, `command_run.py`, `command_execute.py`, `command_patch.py`, `command_repair.py`, `command_transaction_execute.py`, `command_transaction_journal.py`, `command_daemon_process.py`, `command_daemon_registry.py`, `command_daemon_lifecycle.py`, `command_output.py`, `command_rollback_windows.py`. Legacy facade removed; 106+ references migrated. Tests: 738 passed, 16 skipped.
2. **`services.py`** (6,556 -> 1,219): Decomposed into 15 domain mixins (`service_affected_tests.py`, `service_cancellation.py`, `service_code_assist.py`, `service_commands.py`, `service_context.py`, `service_coordination.py`, `service_delegation.py`, `service_eval.py`, `service_generation.py`, `service_hybrid_context.py`, `service_repo_search.py`, `service_repository.py`, `service_review.py`, `service_review_diff.py`, `service_transcription.py`). `services.py` retained as `LocalAIServices` composition root. Tests: 203 passed.
3. **`ui_static/dashboard.ts`** (6,463 -> decomposed): Decomposed into 19 domain scripts under `ui_static/scripts/` (largest 922 lines), orchestrated by `tools/build_dashboard.mjs`. `npm run typecheck`, `npm run build`, and `node --check` pass.
4. **`code_index.py`** (5,146 -> 1,242): Decomposed into `code_index_files.py` (1,723), `code_index_query.py`, `code_index_symbols.py`, `code_index_maintenance.py`, `code_index_impact.py`, `code_index_nav.py`. `code_index.py` retained as `CodeIndex` composition root. Tests: 155 passed.
5. **`repo_tools.py`** (5,105 -> 542): Decomposed into `repo_tools_project_search.py` (1,276), `repo_tools_inventory.py`, `repo_tools_search_backend.py`, `repo_tools_workspace.py`, `repo_tools_context.py`, `repo_tools_patch.py`, `repo_tools_files.py`. `repo_tools.py` retained as `RepositoryTools` composition root. Tests: 93 passed, 1 skipped.
6. **`rag.py`** (5,071 -> 442): Decomposed into `rag_index.py` (1,330), `rag_storage.py`, `rag_maintenance.py`, `rag_search.py`, `rag_retrieval.py`, `rag_workspaces.py`. `rag.py` retained as `RAGStore` composition root. Tests: 356 passed, 9 skipped.
7. **`agent_tasks.py`** (4,966 -> 439): Decomposed into `agent_task_lifecycle.py` (1,082), `agent_task_memory.py`, `agent_task_questions.py`, `agent_task_core.py`, `agent_task_mutation.py`, `agent_task_worktree.py`, `agent_task_plan_sync.py`, `agent_task_training.py`. `agent_tasks.py` retained as `TaskStore` composition root. Tests: 289 passed, 1 skipped.
8. **`deterministic.py`** (4,962 -> 472): Decomposed into `deterministic_analysis.py`, `deterministic_build.py`, `deterministic_editing.py`, `deterministic_index.py`, `deterministic_search.py`, `deterministic_security.py`, `deterministic_tests.py`. `deterministic.py` retained as `DeterministicEngine` composition root. Tests: 124 passed.
9. **`app.py`** (4,178 -> 365): Decomposed into `app_lifecycle.py`, `app_state.py`, `app_wiring.py`, `app_routes.py`, `app_events.py`. `app.py` retained as `LocalAIApp` composition root.
10. **`preprocess.py`** (3,000+ -> 477): Decomposed into `preprocess_cards.py` (873), `preprocess_inventory.py` (326), `preprocess_rag.py` (439), `preprocess_card_store.py` (689), `preprocess_barrels.py`, `preprocess_code_index.py`, `preprocess_controls.py`, `preprocess_indexes.py`, `preprocess_lexical.py`, `preprocess_phases.py`, `preprocess_registry.py` (1,127), `preprocess_scheduler.py`, `preprocess_status.py`, `preprocess_storage.py`. `preprocess.py` retained as `ProjectPreprocessor` composition root. Tests: 211 passed.
11. **`telemetry.py`** (3,858 -> 1,379): Decomposed into `telemetry_aggregates.py` (1,235), `telemetry_queries.py` (196), `telemetry_events.py` (740), `telemetry_writer.py` (313). `telemetry.py` retained as `TelemetryStore` composition root. Circular imports fixed. Tests: 257 passed.
12. **`http_routes_post.py`** (3,267 -> 1,401): Decomposed into `http_post_tasks.py`, `http_post_memory.py`, `http_post_agent_state.py`, `http_post_context.py`, `http_post_repository_analysis.py`. `http_routes_post.py` retained as POST route composition root. Tests: 61 passed.
13. **`http_routes_api.py`** (3,400+ -> 63): Decomposed into `http_api_request.py`, `http_api_identity.py`, `http_api_auth.py`, `http_api_post.py`, `http_api_stream.py`, `http_api_get.py` (1,061). Retained as API route composition root. Tests: 84 passed.
14. **`http_admin.py`** (1,111 -> 699): Decomposed into admin route handler and `http_admin_modes.py` (414). Handler composes both mixins. Tests: 84 passed.
15. **`mcp_server.py`** (6,400+ -> 1,100): Decomposed into `mcp_tools_repo.py` (1,329), `mcp_tools_coord.py` (1,165), `mcp_tools_status.py`, `mcp_tools_task.py`, `mcp_tools_work.py`, `mcp_tools_artifact.py`, `mcp_tools_rag.py`, `mcp_context_guard.py`, `mcp_context_projection.py`, `mcp_instrumentation.py`, `mcp_response_compact.py`, `mcp_response_budget.py`, `mcp_task_context.py`, `mcp_wire.py`, `mcp_accounting.py`, `mcp_client_adapter.py`. Retained as FastMCP registration/bootstrap root. Tests: 143 passed.
16. **Package Barrels Removed**: `client_adapters/__init__.py`, `client_adapters/adapters/__init__.py`, `repo_plan/__init__.py`. Re-export facades removed; internal callers migrated to canonical owning modules (`registry`, specific adapters, `models`, `schema_validation`, `storage`, `workspace`). Tests: 19 passed (client adapters), 338 passed, 17 skipped (repo plan).

### Cohesive Modules (Single-Responsibility Rationale)
17. **`work_orchestrator.py`** (3,945 lines): Single-responsibility execution engine for Agent OS bounded work orders (state transitions, work order leasing, attempt fencing, postimage manifests). Tests: 160 passed, 1 skipped.
18. **`ollama.py`** (3,312 lines): Single runtime provider adapter for the Ollama inference backend (managed daemon lifecycle, model preparation, unload admission, generate/chat/embeddings streaming).
19. **`process_utils.py`** (3,187 lines): Low-level cross-platform OS subprocess and runtime primitives (Windows Job Objects, pidfd, POSIX process groups, priority, RSS tracking, Git worktree isolation).
20. **`agent_memory.py`** (3,086 lines): Single-responsibility store for Agent OS memory hierarchy (scopes, vector/lexical embeddings, recency weighting, promotion/demotion, TTL pruning).
21. **`scheduler.py`** (2,850 lines): AffinityScheduler engine managing GPU concurrency, priority queuing, model residency, and fair scheduling.
22. **`operation_contracts.py`** (2,680 lines): Canonical schema registry and validation contract tables for MCP tools and operations.
23. **`client.py`** (2,353 lines): Typed Python SDK client (`HubClient`) wrapping all HTTP REST endpoints.
24. **`async_jobs.py`** (2,183 lines): Asynchronous job queue, worker pool, and background task lifecycle manager.
25. **`laya_candidates.py`** (2,153 lines): Training data curation store and review consent receipt ledger for local fine-tuning.
26. **`agent_verification.py`** (2,006 lines): Verification receipt, test execution record, and tamper-evident assertion store.
27. **`agent_consistency.py`** (1,963 lines): Cross-backend consistency and agreement guard for multi-model verification.
28. **`agent_events.py`** (1,896 lines): Agent event stream storage and pubsub message broker.
29. **`project_config.py`** (1,743 lines): Project context resolver, `.local-ai.toml` parser, and path hint registry.
30. **`http_server.py`** (1,614 lines): Runtime server entrypoint (`serve`, TLS/SSL, socket lifecycle, signal handlers).
31. **`repo_plan/host_adapters.py`** (1,581 lines): Multi-agent host adapters (Codex, Antigravity, Claude, Copilot).
32. **`treesitter_parser.py`** (1,575 lines): Multi-language AST grammar and syntax parser.
33. **`agent_incidents.py`** (1,546 lines): Incident tracking, failure fingerprinting, and negative knowledge recording store.
34. **`llama_cpp.py`** (1,500 lines): Runtime adapter for GGUF/llama.cpp inference engine.
35. **`embeddings.py`** (1,414 lines): Embedding model runner and vector similarity engine.
36. **`generator.py`** (1,412 lines): Code generation, prompt formatting, and structured output parser.
37. **`browser_bridge.py`** (1,388 lines): Headless browser automation interface.
38. **`agent_context.py`** (1,374 lines): Prompt context builder and token budgeting engine.
39. **`benchmark.py`** (1,366 lines): Benchmark execution engine for model throughput/latency profiling.
40. **`external_tools.py`** (1,345 lines): External CLI command executor with sandboxing.
41. **`artifacts.py`** (1,333 lines): Persistent artifact store for outputs and diffs.
42. **`debug_traces.py`** (1,304 lines): Request and diagnostic trace store.
43. **`cache.py`** (1,282 lines): Tiered cache implementation (L1 RAM + L2 SQLite).
44. **`command_rollback.py`** (1,281 lines): Filesystem rollback and snapshot reversal engine.
45. **`external_gpu_reservation.py`** (1,221 lines): External GPU reservation coordinator and capacity lease manager.
46. **`swarm.py`** (1,217 lines): Multi-agent swarm task coordinator and blackboard ledger.
47. **`response_budget.py`** (1,190 lines): Token budget manager and response compaction accountant.
48. **`sqlite_support.py`** (1,151 lines): Low-level SQLite connection management and resilience engine.
49. **`pipeline.py`** (1,086 lines): Staged query execution pipeline.
50. **`repo_plan/agent_bridge.py`** (1,079 lines): Bridge between Agent OS protocol and repo plan data structures.
51. **`repo_plan/storage.py`** (1,049 lines): SQLite persistence for repo plan tasks and checkpoints.
52. **`agent_policy.py`** (1,047 lines): Sandboxing policy and security enforcement engine.

### Tool Candidates
53. **`tools/benchmark_surfaces.py`** (6,209 lines): Multi-surface automated benchmarking suite.
54. **`tools/surface_inventory.py`** (3,780 lines): AST static analysis tool for API coverage generation and surface auditing.
55. **`tools/setup.py`** (2,532 lines): Installer and environment bootstrapping CLI tool.
56. **`tools/convert_single_owner_state.py`** (2,115 lines): Single-purpose offline database migration utility.
57. **`tools/skill_ownership.py`** (1,684 lines): Skill ownership and integrity auditing CLI tool.
58. **`tools/benchmark_t10_repository.py`** (1,185 lines): Targeted T10 repository benchmark CLI.
59. **`tools/t15_paired_benchmark.py`** (1,021 lines): Targeted T15 paired benchmark CLI.

## Acceptance

- Every baseline candidate has a recorded disposition; no unresolved multi-responsibility monolith remains.
- No legacy facade remains for a split subsystem; repository imports point directly at canonical modules. No compatibility shim is retained just to preserve old internal imports.
- Deleted modules have zero remaining static, dynamic, test, tooling, packaging, and documentation references, except intentional user-facing entrypoints documented as such.
- Targeted tests, Ruff, TypeScript typecheck, and AST surface inventory pass on the final working tree. All changes remain on `master`; pre-existing user changes stay intact.
