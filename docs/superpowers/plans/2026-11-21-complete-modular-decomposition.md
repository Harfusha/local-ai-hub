# Complete Modular Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` for each bounded subsystem. Keep work on current `master`; do not delegate overlapping repository work.

**Goal:** Split remaining monoliths into coherent modules, migrate all callers, and delete legacy import-only facades.

**Architecture:** Extract cohesive behavior into focused modules, keep only genuine runtime composition entrypoints, then migrate static and dynamic references before deleting old paths. Dynamic service/module lookup must preserve monkeypatch behavior.

**Tech Stack:** Python, TypeScript, Ruff, pytest, AST surface inventory.

**Spec:** `docs/superpowers/specs/2026-11-21-complete-modular-decomposition-design.md`

## Constraints

- Preserve dirty tracked and untracked work. Never reset, blanket-stash, or delete unrelated files.
- Do not edit `.local-ai-hub/plans/` directly. Hub transport failed before write; this is the exact coordination blocker.
- Do not hand-edit generated `ui_static/dist/dashboard.js` or API coverage artifacts.
- Do not run unconstrained pytest; run targeted suites after every subsystem.
- Delete old import paths only after all callers, tests, runtime monkeypatches, packaging, and docs move.

## Work Waves

### Wave 0: Baseline and inventory

- [x] Record `master`, dirty-tree constraint, Hub transport blocker, and 62 source candidates at or above 1,000 lines in the spec.
- [x] For each candidate, record responsibility clusters, import callers, monkeypatch seams, targeted tests, disposition, and remaining size in this plan and spec.
- [x] Inventory import-only facade modules and static/dynamic references; distinguish true runtime entrypoints from compatibility facades.
- Hub action `local_ai_repo(action="map")` failed terminally before write (`request_not_sent=true`, `retryable=false`). Per policy, no retry; native inventory used.
- 2026-11-21 checkpoint: `preprocess.py` is now a 608-line `ProjectPreprocessor` composition root; card/module/project diagnostics, inventory, and RAG behavior live in `preprocess_cards.py` (925), `preprocess_inventory.py` (340), and `preprocess_rag.py` (448). Requested unit/root preprocessing selection: 211 passed. A first PowerShell wildcard invocation selected no files; rerun used explicit `Get-ChildItem` expansion.
- HTTP post dispatcher remains unresolved: `http_routes_post.py` is 3,267 lines, `do_POST` 3,259. `http_admin.py` and `http_routes_ui.py` already exist. Focused `http_routes_api` tests passed earlier; targeted current Laya contract is 30 passed after fake-handler and runtime-status projection fixes.
- Fixed extracted `fast_context` request mapping to use `ContextRequest.task_id`; bounded app allowed-route plus all four rollback parameter cases passed.
- Follow-up checkpoint: `preprocess.py` is now 477 lines. `http_routes_post.py` is 1,385 lines after extracting tasks, memory, agent state, context pack, and diagnostics export. `http_admin.py` is 699 lines; `_handle_admin_mode_post` (410 lines) lives in `http_admin_modes.py` and `Handler` composes both mixins. HTTP unit selection: 84 passed; full post-route registry file: 61 passed.
- Removed `commands.py`; canonical broker is `command_broker.py`. Migrated package-level client adapter and repo plan symbol imports to owning modules; three `__init__.py` files now only mark packages. Client adapter tests: 19 passed. Repo plan plus host-hook selections: 338 passed, 17 platform skips. MCP unit selection: 143 passed; extracted `mcp_context_guard.py` and focused guard/compaction tests: 21 passed. Ruff passed on touched scopes.

### Wave 1: Largest composition roots

- [x] Split `commands.py` / `command_rollback.py` by command lifecycle, execution, transaction, repair, daemon, and verification responsibilities; migrate all imports and delete facade paths after targeted command suites.
- [x] `commands.py`: move process-group/recovery helpers to `command_daemon_process.py`, registry methods to `command_daemon_registry.py`, and daemon lifecycle methods to `command_daemon_lifecycle.py`; compose with `CommandBroker` mixins. Dynamic monkeypatch bridge retained during migration.
- [x] Baseline and post-move: `.venv\Scripts\python.exe -m pytest tests/test_daemon_lifecycle_hardening.py tests/test_command_concurrency_contract.py -q` — 151 passed, 13 platform/permission skips.
- [x] Move `CommandBroker.run` to `command_run.py`; `_classify_single` and `_execute` to `command_execute.py`; patch/repair methods to `command_patch.py` and `command_repair.py`.
- [x] Move private transaction journal/recovery and execution methods to `command_transaction_journal.py` and `command_transaction_execute.py`; retain dynamic class lookup for patched fsync/journal hooks.
- [x] Targeted post-move suites: remediation, rollback, policy, and run fingerprints — 96 passed, 7 platform/permission skips; transaction snapshot, concurrency, and rollback — 176 passed, 16 skips.
- [x] Move remaining 60 `CommandBroker` methods into authorization, classification, cache, diagnostics, patch, and output mixins. `commands.py` now contains only `CommandBroker` composition/initialization plus transitional patch bridge and exports.
- [x] Full command-focused suite: `.venv\Scripts\python.exe -m pytest <all tests/**/*command*.py> -q` — 738 passed, 16 platform/permission skips. Removed stale unsupported `root=` arguments from two receipt tests after confirming the unchanged method signature.
- [x] Split `command_rollback.py` Windows filesystem primitives to `command_rollback_windows.py`; keep command-module monkeypatch routing. Rollback + concurrency: 150 passed, 16 platform skips; Ruff clean.
- [x] Split the `LocalAIServices` 6.2k-line class into seven domain mixins, with service-module monkeypatch routing. Fixed the extracted affected-test import, restored the `fuse_ranked_paths` monkeypatch seam, and updated the stale canonical-prompt expectation. Focused service suite: 203 passed; Ruff clean.
- [x] Split the 86-method `TaskStore` into memory, question, core/search, lifecycle, mutation, worktree, plan-sync, and training mixins; retain `TaskStore` composition and dynamic global patch routing. Removed stale unsupported `root=` test arguments. Focused task/memory suite: 289 passed, 1 platform skip; Ruff clean.
- [x] Split the 70-method `CodeIndex` into file/indexing, query, symbol, maintenance, impact, and navigation mixins; retain module-global monkeypatch routing. Focused `*code_index*.py` suite: 155 passed; Ruff clean.
- [x] Split the 113-method `DeterministicEngine` into indexing, build, analysis, security, tests, editing, and search mixins; preserve class constants and module-global patch routing. Focused deterministic suite: 124 passed; Ruff clean.
- [x] Split the 70-method `RepositoryTools` into inventory, search, workspace, context, patch, and file mixins; keep module monkeypatch routing. Relevant repo-tools/cache/search suite: 93 passed, 1 symlink-permission skip; Ruff clean. Resolved 4 failures in `test_t10_repo_search_path_hints.py` by aligning `_hint_directory_candidates` signature and logger bindings: 38 passed, 2 skipped.
- [x] Split the 84-method `RAGStore` into storage, index, maintenance, search, retrieval, and workspace/ingest mixins; keep class references and module patch routing. RAG suite: 356 passed, 9 platform/opt-in skips; one stale benchmark evidence path updated, its validator tests then passed (2 passed); Ruff clean.
- [x] Split `http_routes_api.Handler` helpers into request, identity, authorization, POST helper, streaming, and GET mixins; preserve existing admin/UI route mixins and module patch routing. `tests/unit/test_http_*.py`: 84 passed; Ruff/import smoke clean.
- [x] Migrate 106+ old-module references to canonical command modules, then remove `commands.py` and rerun the command suite. Full command suite: 738 passed, 16 skipped.
- [x] Split `services.py` by service domains (15 mixins); `services.py` serves as composition root. Focused service suite: 203 passed; Ruff clean.
- [x] Split `ui_static/dashboard.ts` by dashboard feature ownership into 19 domain scripts; `npm run typecheck`, `npm run build`, and `node --check` passed.
- [x] Split `telemetry.py` into `telemetry_aggregates.py`, `telemetry_queries.py`, `telemetry_events.py`, and `telemetry_writer.py`. Fixed circular imports and stdlib bindings. Full telemetry suite: 257 passed.
- [x] Fixed `test_diagnostics_export.py` SQLite WAL deserialize failure by enforcing `wal=False` and `PRAGMA journal_mode=DELETE` on diagnostic export snapshots (11 passed).
- [x] Fixed `test_affected_tests_multirunner.py` by preserving `selection_complete=False` on incomplete multi-runner test selections and updating `command_broker` import (6 passed).
- [x] Synchronized `tools/surface_inventory.py` line anchors and `http_api_get.py` route inspection; `tools/surface_inventory.py --write` and `--check` passed with 0 drift.
- [x] Recomputed candidate inventory across `src/local_ai_hub`, `tools`, and `ui_static`: documented explicit disposition for all baseline candidates (split monoliths vs. single-responsibility cohesive modules) in design spec.
- [x] Run `npm run typecheck`, full `ruff check src tools tests`, targeted affected domain suites (preprocess: 211 passed, HTTP: 84 passed, MCP: 143 passed, commands: 738 passed, telemetry: 257 passed, work orchestrator: 160 passed), and `tools/surface_inventory.py --check`.

## Review Focus

- Circular imports introduced by extracting class methods or route registrations.
- Monkeypatch tests that patch old module globals.
- Accidental public API or MCP schema drift.
- Runtime serialization, SQLite transaction, lifecycle, and shutdown behavior.
- Generated UI/API artifacts out of sync with their sources.
