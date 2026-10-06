# Generic Agent Update & Upgrade Prompt for Local AI Hub

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to upgrade an existing Local AI Hub installation from V3 to V4 from the canonical `master` branch, upgrade dependencies, restart services, and refresh the repository's instruction policies.

Preserve hardware-profile model routing when refreshing repository instructions. `[hardware].profile` defaults to `auto`; use the verified role-to-model map in the Local AI Hub Tool Policy below. Treat profile mappings as routing targets, not proof that a model is installed.

---

```markdown
# TASK: Upgrade Local AI Hub from V3 to V4 and Refresh Repository Instructions

You are an autonomous AI engineering agent. Your task is to upgrade **Local AI Hub** from V3 to V4 on this system using the canonical `master` branch, update dependencies, restart the background service, re-verify health, and refresh the Local AI Hub Tool Policy and Token Economy Policy in this repository.

Preserve privacy-safe adoption telemetry: it contains only normalized aggregate tool/action/intent/outcome, time, latency, and output-size buckets. Never migrate or expose prompts, source, secrets, absolute paths, or raw request records. Bypasses require an explicit client signal.

Follow these execution phases:

---

### PHASE 1: LOCATE INSTALLATION & FAST-FORWARD TO V4 MASTER

1. **Locate Installation Directory**:
   - Windows: `$HOME\.local-ai-hub` (or `%USERPROFILE%\.local-ai-hub`)
   - Linux / macOS: `~/.local-ai-hub`
2. **Protect Local Changes**:
   - Run `git status --short` before changing branches.
   - If the installation worktree is dirty, preserve the changes and stop for operator review. Never use `git reset --hard`, `git checkout -- .`, or discard local configuration/source changes.
3. **Fetch V4 from the Canonical Master Branch**:
   - V4 is published on `origin/master`. Do not use the old `codex/v4.0-hardening` feature branch for installations.
   - Fetch `master`, switch to local `master`, and fast-forward only:
     ```bash
     git -C "$HOME/.local-ai-hub" fetch --prune origin
     git -C "$HOME/.local-ai-hub" switch master
     git -C "$HOME/.local-ai-hub" pull --ff-only origin master
     ```
     *(On Windows PowerShell: `git -C "$HOME\.local-ai-hub" fetch --prune origin`, then `git -C "$HOME\.local-ai-hub" switch master`, then `git -C "$HOME\.local-ai-hub" pull --ff-only origin master`.)*
   - If local `master` does not exist, create it only as a tracking branch from `origin/master`; never overwrite an existing local branch.

---

### PHASE 2: RUN UPDATE / RE-SETUP

Run the platform installer with the active hardware profile to apply dependency updates, regenerate MCP schemas/manifests, and update skills. Inspect provider config first: Ollama is selected when `[ollama].enabled = true` and its install/model pulls still require the existing explicit opt-ins (`server.auto_start_ollama = true`, `llama_cpp.fallback_to_ollama = true`). If Ollama is disabled, `llama_cpp.mode = "on"` provisions the pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `"auto"` uses only a configured existing endpoint; `"off"` disables it. Never switch providers silently or start `ollama serve` as a fallback. Pull `models.vision` only for an explicitly enabled Ollama backend and `features.vision = true`:

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -Profile auto
  ```
- **Linux / macOS (Bash)**:
  ```bash
  bash "$HOME/.local-ai-hub/install.sh" --profile auto
  ```

---

### PHASE 3: RESTART SERVICE & VERIFY HEALTH

1. **Restart Hub Service**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\service.py" restart
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/service.py" restart
     ```
2. **Verify Health Endpoint**:
   ```bash
   curl -s http://127.0.0.1:11435/health
   ```
   Must return `{"status":"ok", ...}` with the updated package version.
3. **Run Doctor Diagnostic**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\doctor.py"
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/doctor.py"
     ```
4. **Hardware Acceleration Check (iGPU / NPU)**:
   - On Windows Intel systems, managed llama.cpp setup tries SYCL0 and retries on CPU if GPU startup fails. `mode = "auto"` checks an existing endpoint only. Do not set `OLLAMA_VULKAN` for Intel llama.cpp inference.
   - Other supported platforms use the pinned CPU build for managed llama.cpp. NVIDIA/AMD GPU builds require an explicitly configured external endpoint.
   - If an NPU (Intel AI Boost / AMD XDNA) or Intel iGPU is present:
     Ensure OpenVINO dependencies are installed in the venv only when active hardware/configuration selects OpenVINO for embeddings or reranking. Do not install OpenVINO on NVIDIA-only systems merely because the feature permission is true:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\pip.exe" install -r "$HOME\.local-ai-hub\requirements-openvino.txt"
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\prefetch_openvino.py"
     ```

---

### PHASE 4: REFRESH INSTRUCTIONS IN CURRENT REPOSITORY

Locate active agent instruction files in this repository (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`, `GEMINI.md`, etc.):
- Replace or sync the Local AI Hub tool policy block with the latest policy from `~/.local-ai-hub/generated/agent-policy.md`.
- Replace or sync the token economy policy block with the latest policy from `~/.local-ai-hub/generated/token-economy-policy.md`.
- If no instruction file exists, ensure `AGENTS.md` is created with both policy blocks.
- Verify the default setup deploys the `token-economizer` skill and registers the token-tool CLI directory on the user's persistent PATH. Keep the generated policy trigger that requires agents to load this skill before every repository task.
- Ensure the refreshed policy retains this trigger verbatim:
  - Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Keep the `TOKEN ECONOMY POLICY` block identical in `AGENTS.md` and both canonical prompts; use only tooling and setup commands that the installed skill and repository actually provide.
- Use `local_ai_rag` for semantic retrieval only after deterministic and indexed repository evidence is insufficient.
- Preserve the `trim-run` safety boundary: only its bundled token tools and read-only search CLIs may be launched; use `local_ai_command` for tests/builds and arbitrary validation commands.
- For durable work, require one `local_ai_coord(action="task_create")` contract, phase changes through `local_ai_coord(action="task_checkpoint")`, and one bounded wait instead of status polling loops.
- For every non-trivial repository task, after one-time preprocess make `local_ai_repo(action="context", mode="adaptive")` the first useful operation. It accepts the task/context directly and fuses deterministic/indexed evidence, CodeIndex, Serena, bounded lexical search and RAG; it ranks cross-backend agreement, deduplicates, preserves file diversity and degrades optional backends independently. Do not send a hand-built grep-term list or start native search first.
- Keep routing boundaries explicit: repository navigation/symbols/impact=`local_ai_repo`; exact source/log slices=`local_ai_artifact`; test/lint/typecheck/build=`local_ai_command`; task contracts/ownership leases/checkpoints/receipts/receipt-gated completion=`local_ai_coord`; task-wide context=`local_ai_coord(action="context_compile", task_id=...)`; optional semantic generation/exploration/reasoning/review/second opinion/compression when useful=`local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress", task_id=...)`; deterministic/indexed tools remain for exact facts, symbols, diff and tests; `local_ai_repo(action="solve")` preserves one bounded local pass for explicit semantic wording; failure diagnosis disabled by default, enable `features.local_diagnostic_dispatch=true` only after low-confidence deterministic command parsing with artifact reference plus narrow preview, never raw logs, architecture, security, mutations, or open-ended coding; closed, verified handoff work=`local_ai_work`, never micro-edits or live discussion.
- Semantic delegation is on-demand: after deterministic/indexed evidence, use `local_ai_task` selectively for bounded generation, review, independent second opinions, test-log compression, commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Treat local output as advisory only; queued work, stale context, missing evidence or weak grounding remains visible with explicit metadata and must not be silently discarded. Preserve exceptions for architecture, security, mutations, open-ended coding, exact evidence and verification. Shared specialized prompt contracts and model capability limits live in `docs/MODEL_CAPABILITIES.md`.
- Preserve native fallback gate: only after Hub returns `terminal=true` and `retryable=false`. Mutations never cache or single-flight.
- Keep `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` enabled in the installed default profile, while preserving independent rollback switches. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Malformed values must remain disabled and disabled features must return structured unavailable before work starts. `local_diagnostic_dispatch=true` may retain only bounded failure-preview context for one local diagnosis; it never retains raw output and does not require `diagnostic_artifacts=true`.
- For `batch_replace`, require `features.batch_replacement=true`, then preview with explicit `dry_run=true`; `staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. Keep rollback behavior and never auto-commit replacements. Set `dry_run=false` only after review.

---

### PHASE 5: RE-TRIGGER REPOSITORY PREPROCESSING

Send an asynchronous preprocess request for the current workspace:
- Via MCP tool:
  `local_ai_repo(action="preprocess", root="<CURRENT_WORKSPACE_ROOT>")`
- Or via HTTP loopback:
  ```bash
  curl -s -X POST http://127.0.0.1:11435/api/repo/preprocess \
    -H "Content-Type: application/json" \
    -d "{\"root\": \"$(pwd)\"}"
  ```

---

### PHASE 6: REPORT STATUS

Confirm:
1. Updated Local AI Hub version.
2. Service status (`running`/`healthy`).
3. Summary of instruction files refreshed.
4. Preprocessing status for current repository.
```
### MCP response economy

After updating, verify the generated schemas under the installation's `generated/` directory expose `max_response_tokens`, `response_profile`, and `reuse_key` on the existing Hub tools. These are installation artifacts, not checked-in source files. Treat generator output and configuration as trusted repository inputs; never copy tool fields from untrusted model output. Keep aggregate response budgeting enabled, preserve artifact-backed exact detail, and verify telemetry reports raw/projected/saved response estimates without prompt or source retention.

## Embedded agent policy blocks

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
- closed whole-task delegation with verified handoff: `local_ai_work`
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

Delegation is the default for any task with useful bounded independent work.

- Semantic delegation is on-demand: after deterministic/indexed evidence, use `local_ai_task` selectively for bounded generation, review, independent second opinions, test-log compression, commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression. Use `qwen2.5-coder:1.5b` only for quick/simple requests, `qwen2.5-coder:3b` for ordinary tasks, `qwen2.5-coder:3b` for more involved work, and the configured hardest-reasoning tier for the hardest reasoning. Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace these semantic tasks.
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

Routing hierarchy: the main agent is the orchestrator, planner, integrator and final owner. Use Local AI Hub first for its own precise, bounded microtasks: deterministic facts, indexed/search retrieval, preprocess artifacts, targeted impact/review/security checks, safe commands, compression, local-model synthesis and second opinions. Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work or an explicit Codex-subagent request. It is not routed or managed by Local AI Hub.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.
 Then call `local_ai_repo(action="context", mode="adaptive")` as the first useful operation; it is the quality-first retrieval gate and accepts the task/context directly.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. After one-time preprocess, the first useful Hub operation must be `local_ai_repo(action="context", mode="adaptive")`; use the command broker only for commands after grounded repository evidence exists. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Adaptive retrieval path: call `local_ai_repo(action="context", mode="adaptive")` first; it runs bounded deterministic/indexed, structural, lexical and RAG retrieval, fuses agreement and diversity, and degrades optional backends independently. Stop escalating when evidence is sufficient; reuse cached results and bounded evidence. Do not fan out duplicate native retrieval layers or translate the task into a long grep-term list. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
 do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, search coordination memos for reusable findings. For overlapping multi-agent edits use `local_ai_coord` leases and store concise reusable discoveries as memos.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression, `local_ai_work` for a complete bounded repository task with planning, edits, validation and handoff, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases/memos and Agent OS task, memory, context, and verification workflows.

Local model policy: `qwen2.5-coder:0.5b` is preprocessing-only, `qwen2.5-coder:1.5b` handles quick/simple tasks, `qwen2.5-coder:3b` handles ordinary tasks, `qwen2.5-coder:3b` handles more involved work, and the configured hardest-reasoning tier handles the hardest or highest-risk reasoning. Treat profile/default model names as routing targets only. Check installed-model inventory before live inference; do not infer runtime availability, output quality, or performance from a configured mapping. Use deterministic and indexed Hub actions first for exact facts, symbols, diff and tests. For semantic generation, reasoning, review, independent second opinions and semantic compression, call `local_ai_task`.
## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens); explicit `max_response_tokens` below 128 are rejected, never silently raised.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls return a pointer, not missing data.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Fetch exact source, logs, or evidence only with `local_ai_artifact` slices. Never ask a broad tool for the same payload twice.
- Commands return status, summary, changed paths, and failures; full stdout/stderr stays artifact-backed.
- CALL `local_ai_repo(action="context")` FIRST for every non-trivial repository task, before native reads, grep, planning, edit, review or test. Its adaptive orchestrator fuses deterministic and indexed evidence with Serena, the built-in code index, bounded lexical search and RAG when available; it deduplicates, rewards cross-backend agreement, preserves file diversity and degrades per backend. Send the task/context, not a handmade list of grep terms. Reuse existing evidence and reuse candidates first; require evidence IDs for every factual claim. Deterministic/indexed evidence is authoritative; local models may rank, select, or compress structured evidence only and must not invent repository facts. Guarded scope or drift overrides require an explicit `override_reason` and approval when requested. Omit raw model/debug fields unless explicitly requested through `extra_fields`; responses remain compact; aggregate response budget defaults to approximately 3200 tokens. Omitting guarded fields preserves legacy `mode=fast|full` behavior. This is the default adaptive context pack.
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
- Local model delegation: Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions and compression; use `qwen2.5-coder:1.5b` only for quick/simple microtasks and configured higher tiers for ordinary, involved and hardest work. Deterministic/indexed tools remain for exact facts, symbols, diff and tests.
<!-- END TOKEN ECONOMY POLICY -->
