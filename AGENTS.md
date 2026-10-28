<!-- BEGIN LOCAL AI HUB ANTIGRAVITY SKILLS -->
## Antigravity automatic skill activation

At the start of each conversation, read `~/.gemini/skills/using-superpowers/SKILL.md` and follow the applicable Superpowers workflow. For coding and repository tasks, read `~/.gemini/skills/local-ai-orchestrator/SKILL.md` and use available Local AI Hub MCP tools. Read `~/.gemini/skills/caveman/SKILL.md` and use its ultra mode while preserving technical facts and clarity. If the user says `normal mode` or `stop caveman`, stop Caveman style for the rest of the conversation unless they explicitly re-enable it.
If any required skill or the Hub is unavailable, report the precise limitation and use the allowed fallback; do not claim activation from installation alone.
<!-- END LOCAL AI HUB ANTIGRAVITY SKILLS -->

# Local AI Hub — contributor and agent guide

## Simplified development and integration process

Follow [`docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md`](docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md). It supersedes older instructions below that imply routine delegation, handoff packets, fingerprint manifests, or keeping work in stale branches. Main agent owns audits and integration; default to the current `master` checkout; use only necessary branches/worktrees; integrate bounded units promptly; preserve and classify every leftover before recoverable archival.

## Architecture rules

Task memory adoption passes the same resolved repository coordination ID into compilation, record materialization and excluded-memory diagnostics; expiry checks retain the current repository and declared scope identity.

Consistency-guard repository memory writes and audit reads require the current server-derived project coordination ID and declared scope; missing required identity cannot fall back to a physical-root lookup. No tenant routing or synthetic tenant identity is permitted. Windows isolated-parser workers treat only WerGetFlags ERROR_NOT_FOUND as absent per-process flags before setting NO_UI; other HRESULT failures remain explicit.

Agent scopes use exact enum values global/repository/clone/worktree/branch/task/session. Supplied aliases, case/whitespace variants and unknown/nonstring values reject instead of selecting default authority. Omitted scope retains its declared default; the HTTP memory filter retains empty/absent filter semantics.

Private tool-accounting events carry signed token evidence only; they do not fabricate USD costs with fixed rates. TelemetryStore owns configured channel pricing. Token-efficiency metadata uses canonical parent_task/activity/revision/reuse_state/cache_state fields; retired substitutes are not promoted. Trace metadata setters are set_metadata/reset_metadata only.

Telemetry prices use independent finite nonnegative numeric `cloud_input_token_cost_usd_per_million` and `cloud_output_token_cost_usd_per_million` rates (default 3.0 each; zero remains valid). The combined-rate fallback is removed. Missing channel coverage, inconsistent row accounting, or missing boundary history makes total USD cost unknown; known raw-row channel subtotals remain separate. Cost-bearing daily rollups without channel provenance cannot establish complete pricing. Writer lease identifiers reject scalar coercion; lease paths require a sequence of strings, and corrupt live path scopes fail closed.

Compiled context delivery preserves exact task/root/session identity in a persisted task-context artifact. When a mandatory task goal exceeds the compiler budget, the artifact additionally contains omitted_task_goal; inline context stays explicitly incomplete. Recover the exact task_context_artifact_id using bounded local_ai_artifact get pages and next_offset until null. If the response cap cannot carry recovery metadata, request_larger_response_budget is an explicit rejection; the Hub never silently increases the requested limit.

Semantic MCP responses require an explicit boolean `success`; `answer` cannot substitute for `text`. Successful compiled task context requires explicit `success=true` and `complete=true` on both the response and nested `task_context`, whose `text` is a string. Top-level text cannot substitute for nested task context. Internal lexical `RepositoryTools.search` uses `limit`, never the retired `top_k` keyword; distinct RAG/context candidate parameters retain their own contracts. Blackboard CAS updates accept only nonnegative integer `expected_version` (or omission); the retired `expected_etag` keyword rejects. Sections with different identities cannot merge.

Coordination verification uses an explicit `receipt` object; never synthesize `passed=true` or derive receipt identity from checkpoint/status fields. Completion and export use `task_id`; completion may pin `repository_revision` to the exact fresh snapshot fingerprint (empty means no caller pin). Question IDs/text/answers use their dedicated fields; optional task association remains supported. Task sync uses `sync_action`, `stream_id`, `after_seq`, `limit`, and `events`, with strict export/import field exclusivity.

Canonical repository inputs: `context` takes its task description in `query`; `solve` and `delegate` use `task`. No field fallback is supported. Cross-project graph/symbol/impact use `cross_project_*`; distinct backend/frontend analysis remains `cross_repo_contract`. `synthesize_commit` may use explicit `task_id`, never inferred from a task-name string. Test matrix evidence describes current supported files within a bounded iterator scope and lexical case detection, never runtime test collection or success.

- Python 3.11+; all runtime state belongs under the configured `server.state_dir` and must not be committed.
- The public MCP surface stays compact. local_ai_work provides optional whole-task delegation. Add capability behind one of the seven existing tools unless a separate schema clearly saves more tokens than it costs.
- For repository scanning, deterministic and indexed operations precede embeddings or model inference. Preprocessing uses qwen2.5-coder:1.5b. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after any needed evidence; local LLM calls remain excluded from architecture, security, mutations and open-ended coding.
- Serena is an optional managed backend. Its absence, crash, timeout, or malformed response must degrade cleanly to built-in indexes rather than block the hub.
- Every subprocess and network wait must be bounded. Drain child stderr/stdout and terminate process trees on timeout.
- On Windows use helpers from `process_utils.py` so background subprocesses do not flash console windows.
- Treat client disconnects as normal cancellation/noise, not hub-fatal errors.
- Aggregate observability telemetry stays metadata-only. Detailed debug traces are opt-in and remain local; while enabled, retain complete endpoint payloads, paths, and trace events without redaction or truncation. Keep storage bounded with retention and whole-trace eviction, never by trimming content.
- Do not add migration shims or deprecated aliases to this initial-release branch. Derived SQLite state is disposable and may be rebuilt.
- Every release and update MUST publish and maintain matching agent prompts:
  - `docs/INSTALL_PROMPT.md`: canonical bootstrap prompt for any agent in any repository.
  - `docs/UPDATE_PROMPT.md`: canonical update prompt for any agent in any repository to upgrade hub components and refresh instructions.
  - Any changes to tool policies, schemas, flags, or default models must be synced into both prompt files.

Local model policy: Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Routing targets do not prove installed-model availability.

## Validation

Working-checkout release checks ignore generated Python/pytest caches covered by
`.gitignore`. Use `--allow-installed` for a live checkout with managed environments
and state. Use `--strict-tree` when validating a clean release tree; it cannot be
combined with `--post-test` or `--allow-installed`.

From the repository root:

```bash
python tools/release_check.py
python -m compileall -q src tools tests
python -m pytest -q
python tools/selftest.py
```

For an installed instance:

```bash
python tools/doctor.py
python tools/hubctl.py status
```

## Agent Operating System

Local AI Hub provides durable execution and memory primitives mapped into the standard tools:
- `local_ai_coord`:
  - Plans: `plan_init`, `plan_list`, `plan_get`, `plan_create`, `plan_update`, `plan_task_edit`, `plan_task_delete`, `plan_validate`, `plan_archive`, `plan_board_view`, `plan_adopt_legacy_board`, `plan_bind_task`, `plan_reconcile_steering`. Authoritative plans are stored in `.local-ai-hub/plans/<plan-id>.plan.json`. Single source of truth; never create secondary markdown plans.
  - Tasks: `task_create`, `task_get`, `task_checkpoint`, `task_complete`, `task_fail`, `task_list`, `task_resume`, `task_budget_increase`.
  - Memory: `memory_record`, `memory_get`, `memory_find` (scoped key/value storage with substring `query` search).
  - Context: `context_compile` (assembles bounded state, active task, memories, negative knowledge, and active leases).
  - Verification: `verify_receipt`, `verify_completion` (receipt-gated task completion).
  - Negative knowledge: `negative_knowledge_record`, `negative_knowledge_find` (prevents repeating failed approaches).
  - Accepts optional `task_id` and `criterion` to auto-mint verification receipts on passing test/lint commands.

### Required plan workflow

- At session start, resolve the exact repository/worktree root, read its scoped briefing, and list plans. Reuse the matching active plan; create one only when none covers the requested work. Filter the project Kanban by the chosen `plan_id`.
- Before implementation, bind the Agent OS task and current session to its plan task. Keep title, description, acceptance criteria, owner, active status, next action, blockers, and integration target current through `plan_task_edit` and task checkpoints. Re-read on revision conflicts; never create a duplicate task to bypass a conflict or lost session.
- Persist every operator clarification from chat before continuing: update the relevant Git specification or create one if none applies, reconcile the plan and Agent OS contract revision, and retain the clarification as durable steering. A failed reconciliation must remain visible and be retried from its persisted task/retry state.
- Mark source complete only with authentic broker-backed verification receipts. Mark delivery done only after the required branch/worktree changes are integrated and verified in the target repository. A plan status, successful file write, test output pasted by a caller, or merge claim alone is not completion evidence.
- Before handoff or session end, checkpoint the next action and blockers, verify the plan shows the same state, and leave ownership explicit. On resume, inspect the existing binding and active plan before starting work.
- If a checkpoint reports that the task persisted but plan synchronization failed, do not repeat the task mutation. Resolve the error, reread the plan revision, and call `plan_bind_task` again with the same task and session. Check `checkpoint_sync`: `reconciled` means the pending projection was applied; `not_pending` does not prove task and plan agree. A conflicting plan edit remains visible and must not be overwritten.

## Local model policy

- `qwen2.5-coder:1.5b` is preprocessing-only; `qwen2.5-coder:3b` handles quick or simple tasks; `qwen2.5-coder:7b` handles ordinary and involved tasks; `qwen3.5:9b` handles the hardest reasoning.
- Resolve routes from active configuration and user overrides. Routing targets do not prove a model is installed; model pulls remain opt-in.

Canonical coordination inputs: blackboard update uses content, author and optional expected_version; merge uses remote_sections. Board IDs retain the task_id-scoped default. Pubsub publish uses topic/message/publisher and preserves null or falsey JSON; poll uses after_seq, limit (1–1000, default 50) and optional after_ts, distinct from sequence. Swarm uses goal/target_paths/test_command/author, swarm_id/role/swarm_action/payload, and state for listing. Worktree actions use branch/worktree_path/worktree_id/delete_branch; omitted delete_branch remains true and explicit false is preserved. Simulated merge uses source_branch/target_branch. Dataset curation uses output_path/min_receipts/format (default jsonl); verification export defaults to markdown. Retired generic key/value/query/status aliases cannot substitute for these fields. Incident decision uses fingerprint/state_revision; negative-knowledge recording takes an explicit record object and finding takes query/limit (1–100, default 100). Incident records accept strict signed or unsigned 32-bit process exit codes, including Windows access violations. Root and tenant cannot be overridden inside the record. Generic SDK coordination follows these canonical verification and incident inputs. Source integration alone does not activate running processes or establish runtime acceptance.

Path fusion canonicalizes redundant dot/separator spellings before cross-backend agreement, preserving case, UNC prefixes and parent segments. limit and max_per_path require positive integers; coercive legacy values are rejected. Each optional backend is sampled up to a fixed 4096 entries independently of output limit; malformed groups or iterator failures leave other backends available. This is bounded candidate ranking, not a claim of exhaustive corpus coverage or measured relevance/performance.

Tiered cache nonempty batches require the current L2 set_many API. Providers without that callable batch method reject before L1/L2 writes or coordinator acquisition; there is no per-entry compatibility fallback. Empty batches remain no-ops. Existing supported SQLite batch transactions and coordinator failure recovery are retained; live correctness and performance still require final integrated validation.

Capability grants require canonical string identities, immutable internal capability sets and JSON-array allow/deny inputs; scalar coercions and invalid/nonfinite expiry reject. Explicit deny remains authoritative. Verification receipt passed flags are booleans, generations are nonnegative integers, and observed/expiry timestamps are finite numbers; invalid expiry never becomes unlimited validity. These source changes require integrated validation before acceptance.
