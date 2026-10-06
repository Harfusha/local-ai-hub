# T14 path-scan manual synchronization — 2026-10-06

## Ownership and preserved history

- Only assigned checkout: `C:/Users/Adam/.codex/worktrees/t14-path-scan/.local-ai-hub`.
- Reused branch: `codex/sync-t14-path-scan-20261006`.
- Starting dirty checkpoint: `3b35d5d46e53b8b23a84a27c4e0aaa779290ec1d`; already committed all starting dirty source/test work in `services.py` and `test_context_delivery.py`. Checkout was clean at entry.
- Starting HEAD preserved by `refs/checkpoints/t14-path-scan-sync-original-20261006` at that checkpoint.
- Pre-checkpoint HEAD also preserved by `refs/checkpoints/t14-path-scan-sync-pre-dirty-20261006` at `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Master was read once and pinned by `refs/checkpoints/t14-path-scan-sync-master-20261006` at `896fbedba4a93a255cd02e88c3ec6293ac08ce85`. This includes the user-mentioned `fbc965f5` as an ancestor. No subsequent master chase, master-ref write, root-checkout edit, push, new worktree, stash, reset, clean, or artifact deletion.
- Entry inventory contained no nonignored untracked files. Existing ignored `.pytest_cache/` and source/test `__pycache__/` directories were retained, never staged. Validation runtime artifacts remain excluded.
- Hub failure/native fallback was explicitly authorized by the user; no Hub retry or polling. Native subagent delegation was attempted once but rejected by the agent-thread limit. Missing token-economizer `ensure-tools.ps1` prevented its PlanOnly check; no tool installation or PATH update occurred.

## Hunk decisions

The merge conflicted only in `src/local_ai_hub/services.py` and `tests/test_context_delivery.py`. Hunks were reconciled individually:

- Retain master's streaming cancellation/deadlines, scheduler/telemetry handling, and narrower Whisper CLI missing-executable handling. AST comparison confirms these methods match the pinned master.
- Retain current project-config hint grouping, pinned-context provenance, digest/weights cache identity, and transport budget validation tests.
- Keep T14 indexed path inventory, focus/changed-path ordering, per-root normalization, bounded filesystem fallback, and explicit degradation. Directory hints retain descendant recall without restricting all candidates to the hint.
- Request exclusions win over force-includes, consistent with `project_config.path_allowed` and current T10 `search_paths`. Updated obsolete tests that expected force to bypass exclusions.
- Reject escaping paths and symlink components before normalization. A force-include cannot launder a symlink alias into a normal candidate.
- Keep master's path-control keyword forwarding and sparse lexical completion. An available inventory suppresses the extra completeness search; targeted empty packs do not launch a full context scan. When inventory is absent/degraded and candidates are sparse, the retained lexical completion remains available.
- Directory candidates already represented by bounded inventory descendants are not expanded a second time.
- Rename the old path-inventory test helper to avoid an auto-merged duplicate helper overriding it. Test doubles accept current path-control keywords.

No `/api/context/pack` transport redesign. No changes to `preprocess.py`, `project_config.py`, `repo_tools.py`, `http_server.py`, or `mcp_server.py` relative to pinned master. Preprocessing/provider integration remains exactly the pinned master's version; no Gemini inference, installed configuration inspection, or provider switch was performed. CodeGraph backend removal remains inherited; no backend was restored.

## Actual checks

All commands ran in the assigned checkout. No full release suite, dependency installation, or live model/network validation was run.

1. `git diff --check`: passed after resolution and subsequent edits. Before commit, `git diff --cached --check` against the old branch HEAD reported extensive whitespace violations in incoming master files, including inherited `.handoff` overlays. Those unrelated upstream files were not rewritten; the individual exit status of that cached check was not retained. Final scoped check `git diff --check 896fbedba4a93a255cd02e88c3ec6293ac08ce85 HEAD -- src/local_ai_hub/services.py tests/test_context_delivery.py docs/integration/t14-path-scan-sync-20261006.md` passed with exit 0.
2. First targeted run:
   `python -m pytest -q --tb=short -p no:cacheprovider tests/test_context_delivery.py tests/test_context_path_hints_skip_unbounded_scan.py tests/test_repo_tools_path_hints.py tests/test_t10_repo_search_path_hints.py`
   Result: 47 passed, 10 failed (26.08 s). Eight failures were the duplicate test helper; two were old path-scan doubles/expectations. This first run used pytest's default temporary directory outside the checkout, a scope lapse. Subsequent runs explicitly placed temporary data inside the checkout; no external temporary data was deleted.
3. Second run set `PYTHONDONTWRITEBYTECODE=1` and used:
   `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest_cache/t14-sync-check-20261006-b tests/test_context_delivery.py tests/test_context_path_hints_skip_unbounded_scan.py tests/test_repo_tools_path_hints.py tests/test_t10_repo_search_path_hints.py tests/test_t19_codegraph_removal.py`
   Result: 58 passed, 4 failed (28.22 s). One remaining directory-candidate assertion was resolved. Two directory-expansion failures came from temp repositories discovering the enclosing checkout's Git repository; later runs set `GIT_CEILING_DIRECTORIES` to the assigned checkout. One CodeGraph absence assertion remains outstanding below.
4. Third run set `PYTHONDONTWRITEBYTECODE=1` and `GIT_CEILING_DIRECTORIES` to the assigned checkout:
   `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest_cache/t14-sync-check-20261006-c tests/test_context_delivery.py tests/test_context_path_hints_skip_unbounded_scan.py tests/test_repo_tools_path_hints.py tests/test_t10_repo_search_path_hints.py tests/test_project_config_service_integration.py tests/test_project_path_hints.py`
   Result: 85 passed, 2 failed (24.03 s). Both failures are in unchanged `run_affected` behavior; details below.
5. Final targeted run, same two environment variables, after the symlink guard/regression:
   `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest_cache/t14-sync-check-20261006-d tests/test_context_delivery.py tests/test_context_path_hints_skip_unbounded_scan.py tests/test_repo_tools_path_hints.py tests/test_t10_repo_search_path_hints.py tests/test_project_path_hints.py`
   Result: **83 passed (24.95 s)**.
6. Python AST comparison against `git show 896fbedba4a93a255cd02e88c3ec6293ac08ce85:src/local_ai_hub/services.py`: only `adaptive_context_pack`, `_hybrid_context`, and `_hybrid_context_uncached` differ. Every other `LocalAIServices` method is AST-identical to pinned master, including `run_affected` and master safety fixes. In-memory `compile(..., 'exec')` passed for both changed Python files, without bytecode writes.
7. Post-commit handoff checks passed: `git merge-base --is-ancestor` returned 0 for both pinned master and dirty checkpoint; `git ls-files -u`, `git status --short`, and `git ls-files --others --exclude-standard` were empty. Changed files relative to pinned master are exactly the two Python files and this note. The merge retains both original checkpoint and pinned master as its parents. The final commit ID is reported in chat to avoid a self-referential committed HEAD field.

## Remaining / incomplete

- `tests/test_project_config_service_integration.py::test_run_affected_applies_project_mapping_and_path_hints_safely` fails with `KeyError: 'affected_tests_summary'`.
- `tests/test_project_config_service_integration.py::test_run_affected_fails_closed_when_uncertain_and_test_matrix_missing` fails with `KeyError: 'selection_uncertain'`.
  `run_affected` is AST-identical to pinned master; no unrelated repair was attempted.
- `tests/test_t19_codegraph_removal.py::test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry` fails because pinned-master `repo_tools.py` still contains the ignored directory string `.codegraphcontext`. Confirmed with `git show` on pinned master. The string is a scan exclusion, not a restored backend; removing a safety exclusion solely to satisfy the textual test was not attempted.
- Inventory inspection is capped at 4096 indexed candidates and 512 fallback candidates (or the lower configured `context_fallback_scan_limit`). Recall beyond those bounds and physical filesystem traversal cost are not proven by these tests. Sparse degraded lookup can still use master's bounded lexical completion.
- The adaptive context reader's complete project-policy propagation beyond request path controls is not newly certified here. T10 scoped repository-search and current project path-hint tests pass; `repo_search`, `project_config`, and repository read-policy implementation remain the pinned-master versions. No project-policy redesign was added.
- Gemini runtime availability/quality, preprocessing execution, model inference, real-server deployment, full release acceptance, and end-to-end performance remain **NOT VERIFIED**.

The user explicitly requested a committed handoff even with unfinished behavior. The merge includes the preserved dirty checkpoint and outstanding issues above; it does not claim full release acceptance.
