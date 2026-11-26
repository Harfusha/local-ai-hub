# Local AI Hub — contributor and agent guide

## Simplified development and integration process

Follow [`docs/WORKTREE_INTEGRATION.md`](docs/WORKTREE_INTEGRATION.md). It supersedes older instructions below that imply routine delegation, handoff packets, fingerprint manifests, or keeping work in stale branches. Main agent owns audits and integration; default to the current `master` checkout; use only necessary branches/worktrees; integrate bounded units promptly; preserve and classify every leftover before recoverable archival.

## Architecture and repository scope

Load the always-loaded `local-ai-orchestrator` skill for the complete Hub ownership, scope, MCP contract, lifecycle, memory, budget, GPU, and receipt rules. The skill contains the detailed architecture and Agent Operating System rules formerly listed here. Follow `docs/WORKTREE_INTEGRATION.md`; the repository-specific validation, contributor, and model rules below remain in force.

For any multi-step or non-trivial task, the active Hub plan is the mandatory first entrypoint before touching files or running discovery:
- Call `local_ai_coord(action="plan_list", root=ABS_ROOT)` or `local_ai_coord(action="plan_board_view", plan_id=..., root=ABS_ROOT)` on the first turn to inspect what is completed, in progress, or blocked.
- Maintain bidirectional references in `spec_refs` pointing to Superpowers specifications (`docs/superpowers/specs/...`) and implementation plans (`docs/superpowers/plans/...`).
- Keep task state strictly up to date: transition to `work_status="in_progress"` upon starting, and immediately to `work_status="completed"` upon passing verification. Do not leave completed tasks in `in_progress`.
- Edit tasks with `plan_task_edit` using the current `expected_revision`.

GPU release is fail-closed: `gpu_reservation_status` takes no root; `gpu_reservation_release` requires `consent=true`, a generation, and expiry or confirmed owner death. Use `gpu_reservation_release_authorized` only with explicit consent and audit reason. `gpu_capacity_lease_release` requires its exact lease identity and confirmed owner absence; malformed metadata remains fail-closed.

## Validation

Working-checkout release checks ignore generated Python/pytest caches covered by
`.gitignore`. Use `--allow-installed` for a live checkout with managed environments
and state. Use `--strict-tree` when validating a clean release tree; it cannot be
combined with `--post-test` or `--allow-installed`.

From the repository root:

```bash
python tools/release_check.py
python -m compileall -q src tools tests
# Targeted test validation (unconstrained bare pytest across 17,500+ tests is blocked):
python -m pytest tests/test_test_environment_isolation.py -q
# Or run by category: python -m pytest -m "critical" -q
# Full suite only when explicitly requested: python -m pytest --run-all -q
python tools/selftest.py
```

### Test categorization and execution policy

Running all 17,500+ tests without a selector is blocked in `tests/conftest.py` to prevent freezing development sessions.
Tests are multi-tagged dynamically in `pytest_collection_modifyitems`:
- **Domain topics:** `-m rag`, `-m preprocess`, `-m models`, `-m training`, `-m mcp`, `-m http`, `-m agent`, `-m repo`, `-m automation`, `-m security`, `-m artifacts`, `-m storage`, `-m token_economy`, `-m process`
- **Execution speed/layer:** `-m fast`, `-m slow`, `-m critical`, `-m unit`, `-m integration`, `-m acceptance`

Combine tags: `pytest -m "rag and fast"`, `pytest -m "agent and critical and not slow"`. Explicit file/directory targets (e.g. `pytest tests/unit/test_rag_*.py`) are always permitted directly. Use `pytest --run-all` or `RUN_ALL_TESTS=1` when an unconstrained run is explicitly required.

### Local test-result caching (explicit opt-in)

**Default is fresh test execution.** No test is skipped based on a previous success.
For interactive development, `pytest -m fast --test-result-cache` may reuse
previously passed outcomes, with conservative project-wide source and fixture
fingerprinting. Avoid this opt-in when checking regressions, coverage, security,
packaging or release readiness; it is automatically disabled under CI and
coverage.

For authoritative verification, use `pytest -m critical --no-cache` or
`pytest --run-all --no-cache` and preserve actual JUnit/coverage artifacts.
Set `NO_TEST_CACHE=1` to disable result caching regardless of flags.

For an installed instance:

```bash
python tools/doctor.py
python tools/hubctl.py status
```

## Agent Operating System

Follow the always-loaded `local-ai-orchestrator` skill for Agent OS task, plan, checkpoint, memory, GPU authorization, and receipt contracts. Use only actions advertised by the active MCP schema; preserve exact scope and never invent evidence.

Local model policy: Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Routing targets do not prove installed-model availability; model pulls remain opt-in.

- `qwen2.5-coder:3b` handles preprocessing and quick/simple tasks; `qwen2.5-coder:7b` handles ordinary and involved tasks; `qwen3.5:9b` handles the hardest reasoning.
- Resolve routes from active configuration and user overrides. Routing targets do not prove a model is installed; model pulls remain opt-in.

<!-- BEGIN LOCAL AI HUB PLANNER -->
## LOCAL AI HUB FILE-BACKED PROJECT PLANNER & AGENT WORKFLOW
- **Authoritative Plans**: All project goals, tasks, dependencies, and deliverables are stored in `.local-ai-hub/plans/<plan-id>.plan.json`.
- **Single Source of Truth**: NEVER create secondary or competing Markdown plans (e.g., `PLAN.md`, `TODO.md`, `tasks.md`) for repository work. Always use the file-backed planner via `local_ai_coord(action="plan_*")`.
- **Pre-execution Resolution**: Always resolve the repository root before starting work. Adopt or reuse an existing plan and task rather than duplicating goals.
- **Contract & Clarifications**: Create or update the specification through Superpowers. For changed requirements, record the clarification on the task and call `plan_reconcile_steering` with a stable steering ID, current plan revision, current spec revision, spec path/content, summary, and acceptance criteria before dependent edits when exposed by the active MCP schema. If unavailable, use the Hub's supported project-plan interface or report the precise blocker; never edit plan storage directly.
- **Agent OS Checkpoint Sync**: Checkpoint progress through `local_ai_coord(action="task_checkpoint")`. Bound tasks automatically synchronize progress, phase, next action, and blockers to the plan file.
- **Checkpoint Recovery**: If a checkpoint persisted but plan sync failed, resolve the error, reread the plan revision, and call `plan_bind_task` again with the same task and session. `checkpoint_sync="reconciled"` confirms the pending projection was applied; `not_pending` does not prove the task and plan agree. Do not overwrite conflicting plan edits or repeat the persisted task mutation.
- **Kanban & Briefings**: Board views (`board_summary`, `board_item_list`) and `session_briefing` reflect the authoritative plan files.
- **Authentic Verification**: Use `plan_validate` for plan validity; it does not replace authentic per-criterion command receipts. Complete bound tasks through the receipt-gated Agent OS workflow.
- **Interruption & Resumption**: On interruption, preserve explicit blockers and next actions in the checkpoint rather than restarting with a blank plan.
<!-- END LOCAL AI HUB PLANNER -->
