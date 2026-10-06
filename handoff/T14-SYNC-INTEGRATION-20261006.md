# T14 checkout reconciliation — 2026-10-06

## Scope and pinned identities

- Sole write checkout: `C:/Users/Adam/.codex/worktrees/t14-context-budget-recovery/.local-ai-hub`.
- Merge branch: `codex/sync-t14-context-budget-recovery-20261006` (reused).
- Start HEAD: `563f661e30838ca8126f62c9a93811cc8f57aa28`.
- Existing original dirty checkpoint preserved unchanged: `codex/checkpoint-t14-context-budget-recovery-dirty-20261006`, at start HEAD.
- Additional original HEAD ref: `codex/checkpoint-t14-context-budget-recovery-original-head-20261006`, at start HEAD.
- Complete premerge checkpoint: `codex/checkpoint-t14-context-budget-recovery-complete-20261006`, `dd07cfe0ecc2fd926115635aff51069c037b7dcf`.
- Master pinned once at start: `ca2f86237b1f8ac9ce4f576a308b65b94a24a69c`. Supplied earlier master IDs were already superseded. No subsequent moving-master reconciliation.
- This note belongs to the resolved merge commit. Final branch HEAD is reported in the chat handoff.

## Preservation and manual conflict decisions

The existing checkpoint already committed ten dirty source/test paths. Before merging, all 15 remaining handoff files and both untracked Python tests were committed in `dd07cfe0`. Historical T14 and T15 packets/receipts remain unchanged as provenance, not fresh acceptance evidence.

Eleven conflicted files were reviewed by competing hunks and surrounding behavior:

- `agent_context.py`: retain master canonical request identity, scoped history and full element/provenance hashing. The older additional scope digest/history tuple conflicts with master's history shape; its implementation remains recoverable in the checkpoint. Keep both sets of tests, including the currently failing older expectation.
- `services.py`: retain master adaptive retrieval, structured project hints, explicit exclusions, bounded optional backend lanes, memory-revision failure handling and RAG cache bypass. The older T14 string-hint/focus/no-recall implementation would replace those safety decisions. Preserve it in checkpoint and keep its unfinished tests.
- `repo_tools.py`: retain master whole-snippet ranking, directory hint controls and context-text budget contract. Serialized HTTP/MCP envelopes are enforced separately. The retained T14 snippet tests pass against this implementation.
- `http_server.py`: retain master `/api/context/pack` unchanged, including integer/range validation, matching budget aliases, server-resolved project digest and tenant/task/path handling. No route redesign.
- `response_budget.py`: retain master current-baseline validation, signed savings accounting, exact final counters, inline-source redaction and failure handling. Merge T14's first-complete-citation projection into oversized packs and rejection envelopes. Keep nested master outcome/approval fields when shrinking those packs.
- `mcp_server.py`: retain adaptive default and master dispatch/wire/accounting. Merge T14 citation-only context projection and normalization before final budgeting; protect task completeness, identity and override/approval decisions. Do not reintroduce the older post-routing counter update that bypassed final wire accounting.
- Conflicting tests: preserve both independent sets. For the E2E add/add conflict, keep master's operational-mode isolation.

`agent_context.py`, `services.py`, `repo_tools.py`, `http_server.py`, `preprocess.py`, `external_tools.py`, and all five master source files containing Gemini references are identical to pinned master (bounded `git diff --quiet`, exit 0). Gemini/preprocessing changes and CodeGraph backend removal were not reverted. No new runtime capability, model integration, feature, schema or policy was introduced; install/update prompts remain master versions.

## Actual targeted checks

Native fallback was explicitly authorized after prior terminal Hub failure; Hub was not retried or polled. Optional subagent review could not start because the agent thread limit was reached. Token-economizer setup script at the supplied `.agents` path was absent; no packages or PATH were changed.

1. First targeted pytest batch: **65 passed, 5 failed, 35 setup errors**, 5.65s. A missing parent directory for nested `--basetemp` caused all setup errors. The local JUnit output subsequently created that parent; a distinct fresh basetemp was used for the next run. Two complete-citation failures were resolved during integration.
2. Corrected seven-module batch: **98 passed, 7 failed**, 46.01s. Modules: `test_response_budget`, `test_mcp_response_budget`, `test_context_pack_budget_e2e`, `test_context_pack_snippet_budget`, `test_agent_context`, `test_context_delivery`, `test_t19_codegraph_removal`.
3. After preserving nested outcome fields, final affected three-module batch: **26 passed, 2 failed**, 8.57s. Modules: `test_response_budget`, `test_mcp_response_budget`, `test_context_pack_budget_e2e`. Both live localhost HTTP/MCP E2E selectors pass.
4. AST parse of seven changed Python files: **AST_OK**. Final repetition before commit recorded in chat.
5. Whitespace check relative to pinned master for changed source/tests/ignore rule: **passed**. Broad staged-vs-old-HEAD check reports inherited master artifact/patch whitespace; historical handoff patches were deliberately preserved byte-for-byte.
6. Index has no unresolved entries after staging. Pinned-master ancestry, checkpoint ancestry and clean source handoff are checked after the merge commit.

Command shape: `python -B -m pytest -q -p no:cacheprovider --tb=line --basetemp=.t14-sync-runtime-20261006/<fresh-directory> --junitxml=.t14-sync-runtime-20261006/<receipt>.xml <targeted-modules>`.

No full release suite, install, build, deployment, model call, push or root-checkout edit. Runtime receipts/logs remain local and excluded; see the manifest.

## Outstanding behavior — committed intentionally unfinished

- `test_budget_rejection_preserves_bounded_error_and_retryability`: at 128 tokens, the error is shortened to `context ` instead of retaining `context backend unavailable`. Status/retryability/identity survive; full diagnostic fidelity remains incomplete.
- `test_command_rollback_rejects_non_run_action_before_dispatch`: returned envelope lacks `rollback_unsupported_action`. Command implementation remains master behavior; no command redesign in this reconciliation. No separate pristine-master baseline run was made.
- `test_context_etag_separates_request_scope_identity`: older test expects `unchanged=True`, but current canonical request identity returns false. Preserve master scoped-history semantics; investigate the obsolete fixture/identity assumption separately.
- Three old `test_context_delivery` path tests remain incompatible with master: string hints/force-include precedence, removed direct `focus` argument, and bounded no-index fallback expectation. Master project/exclusion/completeness behavior preserved; old implementation is in checkpoint.
- `test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry`: blanket substring assertion catches the `.codegraphcontext` ignored-directory name in unchanged master `repo_tools.py`. Backend removal remains intact; assertion still fails. No separate pristine-master baseline run was made.

This is a committed checkout synchronization handoff with explicitly failing checks, not a release acceptance claim. Old receipts are historical only.

## Exact changed paths relative to pinned master

- `.gitignore`
- `src/local_ai_hub/mcp_server.py`
- `src/local_ai_hub/response_budget.py`
- `tests/test_agent_context.py`
- `tests/test_context_delivery.py`
- `tests/test_context_pack_snippet_budget.py`
- `tests/test_mcp_response_budget.py`
- `tests/test_response_budget.py`
- `handoff/T14-SERIAL-20261002-B.receipt.json`
- `handoff/T14-SERIAL-20261002-F.receipt.json`
- `handoff/T14-SERIAL-20261002-H.receipt.json`
- `handoff/T14-context-budget-boundary-recovery-2026-10-02.md`
- `handoff/T14-context-budget-boundary-recovery-2026-10-02.patch`
- `handoff/T14-context-budget-candidate-2026-10-02.patch`
- `handoff/T14-continuation-2026-10-02.md`
- `handoff/T14-root-current-20261004.md`
- `handoff/T14-root-current-20261004.patch`
- `handoff/T14-root-current-context-budget-fix-20261004.md`
- `handoff/T14-root-current-context-budget-fix-20261004.patch`
- `handoff/T14-root-current-test-only-20261004.md`
- `handoff/T14-root-current-test-only-20261004.patch`
- `handoff/T15-project-config-root-current.md`
- `handoff/T15-project-config-root-current.patch`
- `handoff/T14-SYNC-INTEGRATION-20261006.md`
- `handoff/T14-SYNC-RUNTIME-EXCLUDED-20261006.json`
