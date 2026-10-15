# Local AI Hub — contributor and agent guide

## Simplified development and integration process

Follow [`docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md`](docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md). It supersedes older instructions below that imply routine delegation, handoff packets, fingerprint manifests, or keeping work in stale branches. Main agent owns audits and integration; default to the current `master` checkout; use only necessary branches/worktrees; integrate bounded units promptly; preserve and classify every leftover before recoverable archival.

<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
Trigger map:
- bounded health/cache/telemetry inspection (never poll): `local_ai_status`
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- non-trivial multi-step, long-running, or acceptance-criteria work: `local_ai_coord` Agent OS task contracts, checkpoints, context, and verified completion
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`
- `local_ai_work`: only when the user explicitly requests closed delegation; routine work stays with the primary agent
- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`
- image understanding/frontend review via `qwen3-vl:4b`: `local_ai_task(action="vision")`
- audio transcription: `local_ai_task(action="transcribe")`
- local-model or device benchmarking: `local_ai_task` benchmark actions
- model/prompt evaluation and drift checks: `local_ai_task` evaluation actions
- model/prompt candidate and speculative-draft workflows: `local_ai_task` candidate actions
- durable asynchronous local jobs: `local_ai_task` submit/status/wait/result/cancel; wait once, never poll
- named read-only local advisory profiles: `local_ai_task(action="delegate", profile=...)`
- curated knowledge sets and document/diagram ingestion: `local_ai_rag` docset and ingest actions
- requested automated repair, affected-test selection, formatting, or lint fixes: `local_ai_command` specialized actions
- local mock, replay, and flaky-test workflows: `local_ai_command` specialized actions
- operator-facing live dashboard: `/dashboard` on the configured Hub server; use `local_ai_status` for bounded agent-side checks

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Semantic work: use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` for bounded semantic tasks after needed evidence; deterministic/indexed tools remain for exact facts, symbols, diff and tests.
- Recipe — Durable execution: create a task contract before substantial work, checkpoint phase changes, attach validation receipts, and complete only after `verify_completion` passes.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Direct ownership is the default. Do not delegate audits, inventory, status checks, or routine implementation. Use a subagent only for genuinely independent bounded implementation that materially shortens the critical path, or when the user explicitly asks; see the simplified workflow spec.

- Semantic delegation is on-demand and optional: after deterministic/indexed evidence, use `local_ai_task` selectively for bounded generation, review, independent second opinions, test-log compression, commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression. Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Preprocessing follows its configured provider; do not switch it silently. Pinned master `2458f72c` has no Gemini preprocessing provider implementation; Gemini agent manifests do not establish runtime preprocessing support. Routing targets do not prove installed-model availability; model pulls remain opt-in.
- Use native Codex subagents only for independent bounded implementation or an explicit user request. Never spawn them for audits or to relay results as a handoff.
- Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work; explicit user requests may also authorize bounded delegation. Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Keep write scopes disjoint. The primary agent reviews and integrates directly; no ZIPs, custom owner packets, or fingerprint/hash cascades.
- Do not duplicate tasks or chats. Check the existing plan first and update its existing item.

Routing hierarchy: the main agent plans, audits, implements, reviews, and integrates directly. Use Local AI Hub for bounded retrieval and commands when available; Hub tools do not create a requirement to hand off work. On a bounded Hub failure, use the permitted direct local fallback and continue without retry loops.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- If an explicitly authorized independent subagent is used, Codex controls its permissions and write scope; the main agent remains integrator. Do not delegate audit-only work.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

Background preprocessing may inspect and index project files, but project-derived `validation_commands` execute repository code. Keep `preprocessing.idle_diagnostics_enabled=false` by default; set it to `true` only with explicit operator approval for those commands. On Windows, `.cmd` and `.bat` validation executables are rejected; do not route them through a shell or interpreter.

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.
 Then call `local_ai_repo(action="context", mode="adaptive")` as the first useful operation; it is the quality-first retrieval gate and accepts the task/context directly.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. After one-time preprocess, the first useful Hub operation must be `local_ai_repo(action="context", mode="adaptive")`; use the command broker only for commands after grounded repository evidence exists. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Adaptive retrieval path: call `local_ai_repo(action="context", mode="adaptive")` first; it runs bounded deterministic/indexed, structural, lexical and RAG retrieval, fuses agreement and diversity, and degrades optional backends independently. Stop escalating when evidence is sufficient; reuse cached results and bounded evidence. Do not fan out duplicate native retrieval layers or translate the task into a long grep-term list. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
 do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, reuse supplied task memory; when more is needed, use permitted scoped `local_ai_coord(action="memory_find")`. Workspace `memo_*` actions are unavailable through tenant-scoped endpoints; on terminal 403 do not retry or bypass scope. For overlapping edits use `local_ai_coord` leases; record concise findings in permitted scoped Agent OS memory or the existing operator-approved coordination file.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression, `local_ai_work` only for closed delegation explicitly requested by the user, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases/memos and Agent OS task, memory, context, and verification workflows.

Local model policy: Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Preprocessing follows its configured provider; do not switch it silently. Pinned master `2458f72c` has no Gemini preprocessing provider implementation; Gemini agent manifests do not establish runtime preprocessing support. Routing targets do not prove installed-model availability; model pulls remain opt-in. Check installed-model inventory before live inference; do not infer runtime availability, output quality, or performance from a configured mapping.
## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls return a pointer, not missing data.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Fetch exact source, logs, or evidence only with `local_ai_artifact` slices. Never ask a broad tool for the same payload twice.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned. `artifact_id` may refer to a diagnostic preview or partial capture. `discarded_output_chars` counts characters omitted during capture or response compaction; a full artifact can retain characters omitted from the response. MCP trimming also sets `output_truncated=true`.
- CALL `local_ai_repo(action="context")` FIRST for every non-trivial repository task, before native reads, grep, planning, edit, review or test. Its adaptive orchestrator fuses deterministic and indexed evidence with Serena, the built-in code index, bounded lexical search and RAG when available; it deduplicates, rewards cross-backend agreement, preserves file diversity and degrades per backend. Send the task/context, not a handmade list of grep terms. Reuse existing evidence and reuse candidates first; require evidence IDs for every factual claim. Deterministic/indexed evidence is authoritative; local models may rank, select, or compress structured evidence only and must not invent repository facts. Guarded scope or drift overrides require an explicit `override_reason` and approval when requested. Omit raw model/debug fields unless explicitly requested through `extra_fields`; responses remain compact; aggregate response budget defaults to approximately 3200 tokens. Omitted mode selects adaptive retrieval; explicit `fast` and `full` modes retain their distinct retrieval paths. This is the default adaptive context pack.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.
<!-- END LOCAL AI HUB TOOL POLICY -->

<!-- BEGIN TOKEN ECONOMY POLICY -->
- Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.
- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action="code_index")` before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Route tests and builds through `local_ai_command`; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or stdin pipelines such as `git log | trim-run`. Use `jq` for JSON.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Local model routing follows the active hardware profile and user overrides; use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions and compression. Consult `docs/MODEL_CAPABILITIES.md`; configured routes do not prove models are installed. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests.
<!-- END TOKEN ECONOMY POLICY -->


## Architecture rules

Agent scopes use exact enum values global/repository/clone/worktree/branch/task/session. Supplied aliases, case/whitespace variants and unknown/nonstring values reject instead of selecting default authority. Omitted scope retains its declared default; the HTTP memory filter retains empty/absent filter semantics.

Private tool-accounting events carry signed token evidence only; they do not fabricate USD costs with fixed rates. TelemetryStore owns configured channel pricing. Token-efficiency metadata uses canonical parent_task/activity/revision/reuse_state/cache_state fields; retired substitutes are not promoted. Trace metadata setters are set_metadata/reset_metadata only.

Telemetry prices use independent finite nonnegative numeric `cloud_input_token_cost_usd_per_million` and `cloud_output_token_cost_usd_per_million` rates (default 3.0 each; zero remains valid). The combined-rate fallback is removed. Missing channel coverage, inconsistent row accounting, or missing boundary history makes total USD cost unknown; known raw-row channel subtotals remain separate. Cost-bearing daily rollups without channel provenance cannot establish complete pricing. Writer lease identifiers reject scalar coercion; lease paths require a sequence of strings, and corrupt live path scopes fail closed.

Semantic MCP responses require an explicit boolean `success`; `answer` cannot substitute for `text`. Successful compiled task context requires explicit `success=true` and `complete=true` on both the response and nested `task_context`, whose `text` is a string. Top-level text cannot substitute for nested task context. Internal lexical `RepositoryTools.search` uses `limit`, never the retired `top_k` keyword; distinct RAG/context candidate parameters retain their own contracts. Blackboard CAS updates accept only nonnegative integer `expected_version` (or omission); the retired `expected_etag` keyword rejects. Sections with different identities cannot merge.

Coordination verification uses an explicit `receipt` object; never synthesize `passed=true` or derive receipt identity from checkpoint/status fields. Completion and export use `task_id`; completion may pin `repository_revision` to the exact fresh snapshot fingerprint (empty means no caller pin). Question IDs/text/answers use their dedicated fields; optional task association remains supported. Task sync uses `sync_action`, `stream_id`, `after_seq`, `limit`, and `events`, with strict export/import field exclusivity.

Canonical repository inputs: `context` takes its task description in `query`; `solve` and `delegate` use `task`. No field fallback is supported. Cross-project graph/symbol/impact use `cross_project_*`; distinct backend/frontend analysis remains `cross_repo_contract`. `synthesize_commit` may use explicit `task_id`, never inferred from a task-name string. Test matrix evidence describes current supported files within a bounded iterator scope and lexical case detection, never runtime test collection or success.

- Python 3.11+; all runtime state belongs under the configured `server.state_dir` and must not be committed.
- The public MCP surface stays compact. Add capability behind one of the eight existing tools unless a separate schema clearly saves more tokens than it costs.
- For repository scanning, deterministic and indexed operations precede embeddings or model inference. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after any needed evidence; local LLM calls remain excluded from architecture, security, mutations and open-ended coding.
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
  - Tasks: `task_create`, `task_get`, `task_checkpoint`, `task_complete`, `task_fail`, `task_list`.
  - Memory: `memory_record`, `memory_get`, `memory_find` (scoped key/value storage with substring `query` search).
  - Context: `context_compile` (assembles bounded state, active task, memories, negative knowledge, and active leases).
  - Verification: `verify_receipt`, `verify_completion` (receipt-gated task completion).
  - Negative knowledge: `negative_knowledge_record`, `negative_knowledge_find` (prevents repeating failed approaches).
- `local_ai_command`:
  - Accepts optional `task_id` and `criterion` to auto-mint verification receipts on passing test/lint commands.

## Local model policy

- `qwen2.5-coder:1.5b` is preprocessing-only; `qwen2.5-coder:3b` handles quick or simple tasks; `qwen2.5-coder:7b` handles ordinary and involved tasks; `qwen3.5:9b` handles the hardest reasoning.
- Resolve routes from active configuration and user overrides. Routing targets do not prove a model is installed; model pulls remain opt-in.

Canonical coordination inputs: blackboard update uses content, author and optional expected_version; merge uses remote_sections. Board IDs retain the task_id-scoped default. Pubsub publish uses topic/message/publisher and preserves null or falsey JSON; poll uses after_seq, limit (1–1000, default 50) and optional after_ts, distinct from sequence. Swarm uses goal/target_paths/test_command/author, swarm_id/role/swarm_action/payload, and state for listing. Worktree actions use branch/worktree_path/worktree_id/delete_branch; omitted delete_branch remains true and explicit false is preserved. Simulated merge uses source_branch/target_branch. Dataset curation uses output_path/min_receipts/format (default jsonl); verification export defaults to markdown. Retired generic key/value/query/status aliases cannot substitute for these fields. Incident decision uses fingerprint/state_revision; negative-knowledge recording takes an explicit record object and finding takes query/limit (1–100, default 100). Incident records accept strict signed or unsigned 32-bit process exit codes, including Windows access violations. Root and tenant cannot be overridden inside the record. Generic SDK coordination follows these canonical verification and incident inputs. Source integration alone does not activate running processes or establish runtime acceptance.

Path fusion canonicalizes redundant dot/separator spellings before cross-backend agreement, preserving case, UNC prefixes and parent segments. limit and max_per_path require positive integers; coercive legacy values are rejected. Each optional backend is sampled up to a fixed 4096 entries independently of output limit; malformed groups or iterator failures leave other backends available. This is bounded candidate ranking, not a claim of exhaustive corpus coverage or measured relevance/performance.

Tiered cache nonempty batches require the current L2 set_many API. Providers without that callable batch method reject before L1/L2 writes or coordinator acquisition; there is no per-entry compatibility fallback. Empty batches remain no-ops. Existing supported SQLite batch transactions and coordinator failure recovery are retained; live correctness and performance still require final integrated validation.

Capability grants require canonical string identities, immutable internal capability sets and JSON-array allow/deny inputs; scalar coercions and invalid/nonfinite expiry reject. Explicit deny remains authoritative. Verification receipt passed flags are booleans, generations are nonnegative integers, and observed/expiry timestamps are finite numbers; invalid expiry never becomes unlimited validity. These source changes require integrated validation before acceptance.
