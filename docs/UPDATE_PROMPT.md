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
- Keep routing boundaries explicit: repository navigation/symbols/impact=`local_ai_repo`; exact source/log slices=`local_ai_artifact`; test/lint/typecheck/build=`local_ai_command`; task contracts/ownership leases/checkpoints/receipts/receipt-gated completion=`local_ai_coord`; task-wide context=`local_ai_coord(action="context_compile", task_id=...)`; semantic generation/exploration/reasoning/review/second opinion/compression=`local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress", task_id=...)`; deterministic/indexed tools remain for exact facts, symbols, diff and tests; `local_ai_repo(action="solve")` preserves one bounded local pass for explicit semantic wording; failure diagnosis disabled by default, enable `features.local_diagnostic_dispatch=true` only after low-confidence deterministic command parsing with artifact reference plus narrow preview, never raw logs, architecture, security, mutations, or open-ended coding; closed, verified handoff work=`local_ai_work`, never micro-edits or live discussion.
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
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task`
- closed whole-task delegation with verified handoff: `local_ai_work`
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Delegation is the default for any task with useful bounded independent work.

- Model routing follows `[hardware].profile` (default `auto`) and user overrides; task routers select the role tier. Use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression after deterministic evidence; keep deterministic simple tasks enabled for exact facts, symbols, diff and tests.
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

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it. Then make `local_ai_repo(action="context", mode="adaptive")` the first useful repository operation: it is the quality-first retrieval orchestrator, not a thin grep wrapper.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. The first useful Hub operation must be `local_ai_repo(action="context", mode="adaptive")` after one-time preprocess. It accepts the task/context directly and boundedly combines deterministic/indexed evidence, CodeIndex, Serena, lexical search and RAG; it deduplicates, rewards cross-backend agreement, preserves path diversity and degrades optional backends independently. Do not send a hand-built term list or start native grep first. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after the grounded context and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Default guarded context flow: Before planning, editing, reviewing, testing, or handing off non-trivial repository work, call `local_ai_repo(action="context", mode="adaptive")` with the stable absolute root and the current phase (`plan`, `edit`, `review`, `test`, or `handoff`). Include `task_id`, focus, and `preload_profile` when known; cite returned `evidence_ids`. Reuse candidates before introducing new abstractions. Treat deterministic/indexed output as authoritative; Serena/RAG enrich and cross-check it; local-model output may rank or compose structured evidence but cannot override it or invent repository facts. If a preload, code-intelligence backend, local model, or Agent OS layer is unavailable, continue with the useful deterministic/indexed or stateless pack and its concise machine-readable warning. Preserve legacy fast/full behavior only for callers that explicitly request them.

Cheapest path for repository evidence: deterministic -> code_index/search -> semantic/graph -> context/solve -> RAG. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after any needed evidence; `local_ai_repo(action="solve")` also preserves one bounded local pass when its task text explicitly requests semantic work.
 Stop escalating as soon as a cheaper layer provides enough evidence. Do not fan out overlapping retrieval layers in parallel for the same question. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
 do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, search coordination memos for reusable findings. For overlapping multi-agent edits use `local_ai_coord` leases and store concise reusable discoveries as memos.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_status` for bounded health/cache/telemetry inspection and Agent OS state, `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and compression, `local_ai_work` for a complete bounded task with planning, edits, validation and handoff, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases, memory, context, and verification workflows.

Local model routing starts from `[hardware].profile="auto"`; hardware detection or an explicit profile selects a role map, then user overrides apply. In order `background_code/fast_code/heavy_code/reasoning/general/vision`: integrated=`qwen2.5-coder:0.5b/qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen2.5-coder:1.5b/qwen3-vl:4b`; balanced=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3.5:9b`; high=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`; max=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`. Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`. These are routing targets, not proof that models are installed; model pulls remain opt-in. Run deterministic and indexed Hub actions first for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, exploration, reasoning, review, independent second opinions and compression.
For model roles, `cpu` and `low` reuse the integrated model map; profile-specific scheduler settings still apply. Explicit model overrides and runtime fallbacks preserve the routed request's minimum tier; do not lower its quality floor for latency.
<!-- END LOCAL AI HUB TOOL POLICY -->

<!-- BEGIN TOKEN ECONOMY POLICY -->
- Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.
- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action="code_index")` before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Route tests and builds through `local_ai_command`; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or stdin pipelines such as `git log | trim-run`. Use `jq` for JSON.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- Local model delegation follows the active hardware profile and configured role tiers; do not assume a named model is installed. Use `local_ai_task` only for bounded semantic work after deterministic evidence.
<!-- END TOKEN ECONOMY POLICY -->
