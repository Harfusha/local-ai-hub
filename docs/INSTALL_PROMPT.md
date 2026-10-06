# Generic Agent Installation & Integration Prompt for Local AI Hub

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to bootstrap Local AI Hub, configure background services and MCP, and integrate the tool and token economy policies into repository instructions.

T12 routing contract to preserve at integration: hardware profile selects role targets; user model overrides apply only to configured foreground tiers and may not lower the routed quality floor. This protection is not present in the current candidate's `router.apply_model_override`, which accepts any configured tier; do not claim it until T12 source is integrated and same-revision checks pass. Model names are routing targets, not evidence that they are installed; pulls remain opt-in. Semantic local tasks stay on-demand after deterministic/indexed evidence, and cloud reasoning/planning must never wait for a mandatory local handoff.

Local model routing starts from `[hardware].profile="auto"`; hardware detection or an explicit profile selects a role map, then user overrides apply. In order `background_code/fast_code/heavy_code/reasoning/general/vision`: integrated=`qwen2.5-coder:0.5b/qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen2.5-coder:1.5b/qwen3-vl:4b`; balanced=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3.5:9b`; high=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`; max=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`. Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`. These are routing targets, not proof that models are installed; model pulls remain opt-in. Run deterministic and indexed Hub actions first for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, exploration, reasoning, review, independent second opinions and compression.

Before changing model routing or claiming a model switch is safe, measure supported hardware/backend cohorts and attach revision-bound quality, latency, and VRAM evidence before and after. Model output is advisory, not verification.

---

```markdown
# TASK: Install, Verify, and Integrate Local AI Hub in Environment & Repository

You are an autonomous AI engineering agent. Your task is to install and configure **Local AI Hub** on this system (if not already installed or running), verify all components (service, configured local backends, token economy suite, code intelligence), ensure MCP integration, and inject the canonical tool and token economy policies into this repository's agent instructions. Ollama is disabled unless explicitly opted in.

Hub adoption telemetry is aggregate-only: retain normalized tool/action/intent/outcome plus time, latency, and output-size buckets. Never send prompts, source, secrets, absolute paths, or raw request records. Mark a bypass only when the client explicitly signals one; do not infer it from missing Hub calls.

Treat workspace memos and leases as trusted-local shared coordination state; tenant labels are caller-supplied provenance, not identity or authorization. Workspace memos are keyed by canonical workspace and key. Use `expected_version` from a memo read when `memo_put` must reject stale overwrites; a `version_conflict` returns the current generation, so reread and reconcile before retrying. Omission retains last-writer-wins; deletion advances the generation while expiration does not.

Execute the following phases deterministically:

---

### PHASE 1: ENVIRONMENT PROBE & CLONE

1. **Check Existing Installation**:
   - Standard path:
     - Windows: `%USERPROFILE%\.local-ai-hub` (or `$HOME\.local-ai-hub`)
     - Linux / macOS: `~/.local-ai-hub`
2. **Clone if Missing**:
   If the directory does not exist or lacks `tools/setup.py`, clone the repository:
   - Git command:
     ```bash
     git clone https://github.com/Harfusha/local-ai-hub.git "$HOME/.local-ai-hub"
     ```
     *(On Windows PowerShell: `git clone https://github.com/Harfusha/local-ai-hub.git "$HOME\.local-ai-hub"`)*

   After cloning, fetch origin, confirm the verified commit is reachable from `origin/master`, and check out that exact SHA in detached mode. On an existing checkout, preserve changes and stop if it is dirty. Verify `git rev-parse HEAD` equals the verified SHA and the complete porcelain status is empty before Phase 2.

---

### PHASE 2: RUN BOOTSTRAP INSTALLATION

Before running setup, obtain the exact 40-character verified commit SHA from the T20 release owner. A branch name or current `master` tip is not a release pin. Ensure the selected source checkout resolves to that SHA and `git status --porcelain=v1 --untracked-files=all` is empty; if it is dirty or mismatched, preserve its changes and stop. The installer repeats both checks before setup or copying files. Pass the same SHA as `--expected-revision` on every platform. Do not point setup at another checkout or overwrite the running installation from an unverified candidate.

Run the platform installer from the repository root. This automatically configures Python 3.11+, the virtual environment, Token Economy tools, backend-appropriate local model support, Serena in an isolated environment, global MCP configs, and the background supervisor. Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex `cwd=install_dir` is not the caller's project root, and setup injects no project-root environment. Current candidate maps missing or `.` roots to the MCP working directory for most repository/RAG actions; preprocessing alone rejects a missing absolute root. Always pass the caller's explicit project root. Release acceptance stays blocked until T03 rejects rootless repository-scoped actions or a tested adapter supplies caller root explicitly. T03/T04/T13 integration remains pending in this candidate; treat this as a release contract, not verified runtime behavior. `HubClient` autostart is bounded and guarded by a cross-process lock; an existing managed supervisor or listener blocks another daemon launch. Treat generated agent command, arguments, working directory and environment as authoritative; inspect the installer-generated MCP entry instead of inventing proxy arguments or environment. Project-local MCP manifests use `target_root` as `cwd`; global manifests use `install_dir`. For each global repository, task, or memory request, set the request's `root` to the caller's project root and preserve task context; never infer root from `install_dir` or process cwd. T13 defines server-derived principal/effective-tenant behavior; this T19 candidate does not include or validate the T13 implementation. Required T04 transport contract: `request_not_sent` means delivery did not begin; `outcome_unknown` means delivery may have occurred and must never be replayed automatically. The candidate client exposes `outcome_unknown`, but full T04 `request_not_sent` classification is not integrated or runtime-verified; treat both semantics as release acceptance, not current proof. The user service starts again after reboot when the user session starts. Ollama is installed or pulled only when `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. When Ollama is disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`, then supervises its loopback server; Intel Windows tries SYCL and falls back to CPU. `mode = "auto"` detects an existing endpoint only; `"off"` disables llama.cpp. Ollama wins provider selection whenever enabled. Setup must never switch providers silently or install Ollama as a fallback. Keep `[server].bind = "127.0.0.1"` and `[security].allow_remote = false` for loopback-only operation. Non-loopback binds require `[security].allow_remote = true` and `[security].api_token` with at least 16 characters. On loopback, empty `api_token` leaves HTTP data/control routes unauthenticated; configure a token to protect them. When configured, send the token in `X-LocalAI-Token` or `Authorization: Bearer`; `/health` and the dashboard shell are public. This candidate has no `api_token_permissions`, `allowed_roots` validation, principal-to-root HMAC tenant derivation, or tenant-label consistency enforcement. HTTP tenant scope uses caller-provided `X-LocalAI-Tenant`, then `X-Tenant-ID`, then `http-default`; tenant label is not an authorization boundary. For correct repository targeting, pass the caller project root explicitly. Most repo/RAG MCP actions currently map omitted or `.` roots to MCP `cwd`; preprocessing alone rejects a missing absolute root. Root targeting does not provide authorization or root-isolated tenant behavior. T13 auth/root isolation remains unintegrated and unverified. Set `features.vision = false` to remove vision capability and its model pull. The default install deploys the `token-economizer` skill and registers its CLI directory on the user's persistent PATH; verify both after setup, then open a new terminal. Do not pass `--skip-token-economy` or `--skip-companion-skills` for the standard install.

For an upgrade or rollback, stop the single per-user Hub service, record its platform service-manager identity and enabled state separately, then back up the installation, `config.toml`, complete configured `server.state_dir`, and every managed agent MCP config file together; include SQLite `-wal` and `-shm` files. Caches are disposable and do not contain durable tasks, receipts, jobs, memory, or leases. Restore only declared roots and preserve data outside the rollback write set. Restore matching daemon code, Hub config, state and proxy registrations together; do not point an older release at newer state. Service registration is external to the file snapshot; reconcile that same service once with the restored release before starting it. Never register per agent, chat, or worktree.

When `[ollama].enabled = false`, setup must honor the llama.cpp mode: managed install only for `on`, external health check only for `auto`, and no runtime for `off`. Never start `ollama serve` as an implicit fallback.

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -ExpectedRevision "<T20_VERIFIED_COMMIT_SHA>" -Profile auto
  ```
- **macOS / Linux (Bash)**:
  ```bash
  bash "$HOME/.local-ai-hub/install.sh" --expected-revision "<T20_VERIFIED_COMMIT_SHA>" --profile auto
  ```

*Note*: If an explicitly configured local backend or heavy model is unavailable, the installer still sets up deterministic tools and built-in indexers and reports the unavailable optional backend.

If this checkout includes `docs/PYTHON_SDK.md`, consult it for the Python package's `HubClient`, install extras, and replay/error contracts before writing Python integration code.

---

### DURABLE ASYNC JOBS AND CONVERSATIONS

The T13 lifecycle implementation remains candidate-only and untested; this contract text is not runtime acceptance evidence.

Keep the async contract aligned across MCP, HTTP, and `HubClient`. Supported `job_action` values are `batch`, `compress`, `delegate`, `reason`, `review`, `review_diff`, `route`, `second_opinion`, and `speculative_lint`. HTTP delivery maps `/api/delegate`, `/api/reason`, `/api/review`, `/api/review/diff`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` to these actions. `delivery="sync"` is default; `delivery="async"` submits immediately. `delivery="auto"` needs positive `latency_budget_ms` and at least ten endpoint observations whose p95 exceeds that budget; sparse history stays inline. For `/api/review/diff`, an exceeded positive `review.max_queue_age_ms` takes precedence. Otherwise, fewer than five telemetry samples plus a positive budget selects async with reason `cold_start_review_diff`. Conversations require sync delivery.

Use `local_ai_task(action="submit", job_action=..., request_id=<stable body key>)` for durable submission. `POST /api/async-jobs` accepts `action="submit"`, `job_action`, and optional stable `request_id`; controls use `action="status"|"wait"|"result"|"cancel"`, `job_id`, and wait `timeout_seconds`. `HubClient.submit_async_job` and lifecycle helpers use the same endpoint. Preserve `job_id`, `state`, `artifact_id`, and `expires_at`. Result TTL defaults to 259,200 seconds (72 hours). Timed-out waits return `wait_timeout_seconds` and do not cancel jobs. Running cancellation reports `cancel_requested=true` before worker completion. Recovery replays only replay-safe actions with matching tenant, action, payload, stable `request_id`, and remaining attempts; other uncertain work becomes terminal `outcome_unknown`.

Start conversations synchronously with `POST /api/delegate` or `POST /api/reason`, `conversation=true`, and `delivery="sync"`. Continue through `/api/conversations/continue` with `conversation_id=..., task=..., context=...`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`. `HubClient.continue_conversation` maps its prompt to `task`. `HubClient has no dedicated start helper`; use `HubClient.post`. Conversations are scoped to the server-derived effective tenant, allow 12 user turns by default, and use a prompt limit of 56,000 by default. Idle TTL is 900 seconds; active TTL is 1,800 seconds. State and transcripts disappear on restart.

### PHASE 3: VERIFY SERVICE & HEALTH

Verify `hubctl.py service-status` and exactly one platform user-service entry: Windows Task Scheduler `LocalAIHubSupervisor`, macOS LaunchAgent `com.localai.hub`, or Linux systemd user unit `local-ai-hub.service`. Do not register a service per agent, chat, or worktree. A `detached-fallback` result does not prove reboot-persistent service acceptance. Setup exits nonzero if service registration fails or reports only a detached fallback; preserve its output, inspect the existing service-manager entry and logs, then repair or rerun against the same clean verified commit. Do not report install complete until one persistent service is confirmed.

1. **Check Service Endpoint**:
   Probe HTTP health (default port 11435):
   ```bash
   curl -s http://127.0.0.1:11435/health
   ```
   Must return `{"success":true,"hub_online":true,"version":"..."}`. `/health` is public liveness; this candidate has no `/ready` route. Run `python tools/doctor.py` and `python tools/hubctl.py service-status` to inspect health and the per-user supervisor, then `python tools/hubctl.py dashboard`; inspect the printed URL and confirm it is loopback-only. The dashboard shell is public; set the token in its toolbar for protected data. Check agent MCP configs contain the installer-generated stdio entry rather than a hand-written daemon launch.
2. **If Service Not Running**:
   Start it via python venv:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\service.py" start
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/service.py" start
     ```
3. **Run Doctor Diagnostic**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\doctor.py"
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/doctor.py"
     ```
4. **Hardware Acceleration Verification (iGPU / NPU)**:
   - On Windows Intel systems, managed llama.cpp setup tries SYCL0 and retries once on CPU if initialization fails; check `hubctl status` for the active device. `mode = "auto"` uses only a pre-existing endpoint. Do not set `OLLAMA_VULKAN` for Intel llama.cpp inference.
   - Other managed supported platforms use the pinned CPU runtime; GPU builds can be configured as external loopback endpoints. Do not claim Ollama is active when llama.cpp was selected.
   - If an NPU (Intel AI Boost / AMD XDNA) or Intel iGPU is present:
     Ensure OpenVINO dependencies are installed in the venv only when active hardware/configuration selects OpenVINO for embeddings or reranking. Do not install OpenVINO on NVIDIA-only systems merely because the feature permission is true:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\pip.exe" install -r "$HOME\.local-ai-hub\requirements-openvino.txt"
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\prefetch_openvino.py"
     ```

---

### PHASE 4: INJECT INSTRUCTIONS INTO CURRENT REPOSITORY

Inspect current repository root for existing agent instruction files:
- Universal: `AGENTS.md`
- Claude Code: `CLAUDE.md`
- Cursor: `.cursorrules` or `.cursor/rules/local-ai.mdc`
- Windsurf: `.windsurfrules`
- Gemini: `GEMINI.md`
- Copilot: `.github/copilot-instructions.md`

**Action**:
1. If no instruction file exists, create `AGENTS.md` at repository root.
2. In `AGENTS.md` (and any other active instruction files detected above), ensure the following two exact policy blocks are present. If older versions exist, update them between the markers; otherwise append them:

```markdown
<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
Trigger map:
- bounded health/cache/telemetry inspection (never poll): `local_ai_status`
- repository navigation/symbols/impact: `local_ai_repo`
- test/lint/typecheck/build commands: `local_ai_command`
- exact source/log/evidence slice: `local_ai_artifact`
- task contracts, ownership leases, checkpoints, verification receipts, and receipt-gated completion: `local_ai_coord`
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- semantic generation, exploration, reasoning, review, second opinion and compression: use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` after any needed evidence. Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace semantic local-model work. `local_ai_repo(action="solve")` preserves one bounded local pass when its task text explicitly requests explore/explain/why/compare/second-opinion semantics, even when exact evidence is strong. Failure diagnosis is not automatic: although `features.local_diagnostic_dispatch` is enabled in the installed default profile, use it for one local diagnosis only after low-confidence deterministic command parsing with an artifact reference and narrow preview; never raw logs. Automatic local inference never handles architecture, security, mutations, or open-ended coding.
- Semantic delegation is on-demand: after deterministic/indexed evidence, use `local_ai_task` selectively for bounded generation, review, independent second opinions, test-log compression, commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests.
- closed, verified handoff work: `local_ai_work`; skip micro-edits and live discussion
- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`
- image understanding/frontend review via the configured vision tier: `local_ai_task(action="vision")`
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

Use only tool names, actions, arguments, defaults, and feature-gated options present in the installed generated schema. The schema is authoritative for the installed version; do not infer support from internal APIs or another release.

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Semantic work: use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` for bounded semantic tasks after needed evidence; deterministic/indexed tools remain for exact facts, symbols, diff and tests.
- Recipe — Durable execution: create a task contract before substantial work, checkpoint phase changes, attach validation receipts, and complete only after `verify_completion` passes.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- For `local_ai_rag(action="ingest_document")`, non-empty `content` is required; `title` and `metadata` are optional. Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`. Embedding errors do not stop lexical publication. For `ingest_diagram`, `image_path` must resolve to an existing `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file; `caption` and `metadata` are optional. Success also returns `diagram_indexed` and the resolved image path.
- Contract notes: `local_ai_status.detail` uses `brief`, `cache`, `telemetry`, `full`, or `agent_state`; `action` also accepts `status`, `health`, `check`, and `info` aliases. `local_ai_repo(action="pipeline")` accepts closed step objects with a supported action and per-step `id`/`result`; run no more than four steps in parallel. Repository pipelines serialize preprocessing mutation actions with other mutating steps. `local_ai_artifact(action="list")` does not require `artifact_id`; `binary` is supported and binary payloads are never inlined. `local_ai_coord(action="pubsub_poll")` accepts `after_seq` from 0 through 2^63-1; `local_ai_coord` bounds `max_tokens` to 0 through 100000.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Semantic delegation is optional and on-demand; use it when bounded independent work would add value.

- Model routing follows `[hardware].profile` (default `auto`) and user overrides; task routers select the role tier. For bounded semantic generation, reasoning, review, independent second opinions, or compression, use `local_ai_task` selectively after deterministic evidence when it adds value. Cloud reasoning and planning may proceed directly without a local semantic handoff; keep deterministic simple tasks enabled for exact facts, symbols, diff and tests.
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

Routing hierarchy: the main agent is the orchestrator, planner, integrator and final owner. Use Local AI Hub first for its own precise, bounded microtasks: deterministic facts, indexed/search retrieval, preprocess artifacts, targeted impact/review/security checks, safe commands, compression, local-model synthesis and second opinions. Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work or an explicit Codex-subagent request. It is not routed or managed by Local AI Hub.

CodeGraphContext/KuzuDB was removed from Local AI Hub. Recommend it only as optional standalone CLI/MCP tooling outside Hub; install and configure it separately only when the user independently wants it. It is not a Hub dependency, runtime, backend, or MCP integration.

`disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs. It does not disable module/project cards: `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences, and either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold. Check active configuration and backend state before claiming synthesis is disabled.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Bounded native reads of a known path and required slice (such as `view_file`) are permitted after Hub context. Broad search, globs, trees and validation follow the native fallback gate.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.
 Then call `local_ai_repo(action="context", mode="adaptive")` as the first useful operation; it is the quality-first retrieval gate and accepts the task/context directly.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. After one-time preprocess, the first useful Hub operation must be `local_ai_repo(action="context", mode="adaptive")`; use the command broker only for commands after grounded repository evidence exists. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Default context contract: after one-time preprocessing call `local_ai_repo(action="context", mode="adaptive")` first with task/context and stable root; include the current `phase`, `task_id`, `focus`, and `preload_profile` when known. Use `local_ai_coord(action="context_compile", task_id=...)` for task-wide resume/state compilation; `local_ai_task(task_id=...)` consumes compiled context automatically before semantic work. Require evidence IDs and reuse candidates. Preserve revision, freshness, receipts, `context_id`, `etag`, omitted sections and `next_action` where returned; never treat partial/stale/mismatched-revision context as complete. Guarded fields include `changed_paths`, `since_hash`, `approval`, and `override_reason`, alongside task/budget/workspace and compact response controls. Scope or drift overrides require an explicit reason and approval when requested. Raw model/debug fields are omitted unless explicitly requested through `extra_fields`. Missing task compilation does not establish successful stateless task context.

Retrieval path for repository context: adaptive `context` first, with bounded deterministic/indexed, Serena, lexical and RAG backends fused by agreement and diversity; optional backends degrade independently. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after grounded evidence.
 Do not fan out duplicate native retrieval or translate the task into a long grep-term list. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
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
Keep generated contracts aligned: `local_ai_status.action` accepts feature-enabled status details plus `status`, `health`, `check`, and `info` aliases. `local_ai_repo(action="verify_receipt")` requires `receipt.task_id`, `receipt.criterion`, and boolean `receipt.passed`; `passed=true` also requires non-empty `receipt.evidence_id`. `/api/search` timeout must not exceed 120 seconds.

Operation argument validation rejects non-finite numbers, including nested values. Status bypass reports require `adoption_signal="bypassed"`, a supported `target_tool`, and a supported `target_action` for that tool. Preserve the shared MCP output envelope and action-scoped input constraints.
Rollout controls: `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` are enabled in the installed default profile. Code intelligence also defaults on through `features.code_intelligence`, `code_intelligence.enabled`, and `code_intelligence.serena_enabled`; all three gates must allow Serena use, and an unavailable Serena backend degrades to indexed retrieval. These switches remain independently configurable. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Disabled flags return structured unavailable before work starts; malformed values stay disabled. `local_diagnostic_dispatch=true` may retain only its bounded failure preview for one local diagnosis; never raw output and no `diagnostic_artifacts=true` dependency.

Batch edits require `features.batch_replacement=true`. Then use `local_ai_repo(action="batch_replace", edits=[...], dry_run=true)` for preview. `staged` is not batch dry-run and is never forwarded. Each edit needs exact target text that matches once. The engine preflights all edits, rolls back write failures, and never auto-commits. Set `dry_run=false` only after review.

For durable work, create one `local_ai_coord(action="task_create")` contract, record phase changes with `local_ai_coord(action="task_checkpoint")`, then use one bounded wait on the durable job. Do not poll status loops.

Local model policy: resolve role routes from `[hardware].profile` and user overrides; see `docs/MODEL_CAPABILITIES.md` for the exact role matrix. Routes do not prove that models are installed; model pulls remain opt-in. The shared operation-specific prompt contract supplies capability limits, evidence IDs, acceptance criteria and no-invention rules. Every semantic result is advisory; unrelated paths, queued/empty/malformed/error output remains visible with `advisory_only=true`, `semantic_quality` and a bounded `quality_warning`/`bypass_reason`, never silently rejected. Deterministic and indexed Hub actions run first for exact facts, symbols, diff and tests; semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` only after evidence. See `docs/MODEL_CAPABILITIES.md`.
<!-- END LOCAL AI HUB TOOL POLICY -->

<!-- BEGIN TOKEN ECONOMY POLICY -->
- Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.
- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action="code_index")` before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Route tests and builds through `local_ai_command`; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or stdin pipelines such as `git log | trim-run`. Use `jq` for JSON.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- Local model delegation: use `local_ai_task` selectively for bounded semantic work after deterministic evidence. Follow `[hardware].profile` and user overrides; consult `docs/MODEL_CAPABILITIES.md` for role routes. Routing targets do not prove model availability; keep model pulls opt-in and hard and extreme reasoning distinct.
<!-- END TOKEN ECONOMY POLICY -->
```

---

### PHASE 5: REPOSITORY / WORKSPACE MCP REGISTRATION (IF APPLICABLE)

If this workspace uses repository-scoped MCP (e.g., `.cursor/mcp.json` or `.vscode/mcp.json`), ensure the `local-ai` server entry is defined:

```json
{
  "mcpServers": {
    "local-ai": {
      "command": "<HOME>/.local-ai-hub/.venv/bin/python",
      "args": ["-m", "local_ai_hub.mcp_server"],
      "cwd": "<HOME>/.local-ai-hub",
      "env": {
        "LOCAL_AI_AGENT": "generic",
        "LOCAL_AI_AGENT_PROFILE": "generic",
        "LOCAL_AI_CONFIG": "<HOME>/.local-ai-hub/config.toml",
        "PYTHONPATH": "<HOME>/.local-ai-hub/src"
      }
    }
  }
}
```
*(On Windows, replace paths with Windows equivalents: `...\\Scripts\\python.exe`, backslashes, etc.)*

Use only actions and arguments present in the installed generated schema. Schema presence is not authorization: process-lifecycle actions such as `spawn_daemon` require an explicit policy capability grant. Do not infer support for extra fields from similarly named APIs.

---

### PHASE 6: INITIAL REPO INDEXING & HANDSHAKE

Trigger one-time asynchronous preprocessing on the current repository root:
- If `local_ai_repo` MCP tool is available in your active session:
  Execute `local_ai_repo(action="preprocess", root="<ABSOLUTE_CURRENT_REPO_PATH>")`.
- Or trigger via HTTP loopback:
  ```bash
  curl -s -X POST http://127.0.0.1:11435/api/repo/preprocess \
    -H "Content-Type: application/json" \
    -d "{\"root\": \"$(pwd)\"}"
  ```

---

### PHASE 7: STATUS REPORT

Output concise confirmation with:
1. Local AI Hub version and service status (`online` / `offline`).
2. Tools verified (`rg`, `fd`, `ast-grep`, `repomix`, `tokcount`, `trim-run`).
3. Configured local backend and model status (Ollama must be reported as disabled unless explicitly opted in).
4. Instruction files created/modified in this repo.
5. Readiness confirmation.
```
### MCP response economy

Keep the generated MCP response contract enabled. Hub responses are aggregate-bounded by default; preserve `max_response_tokens`, `response_profile` (default `"compact"`), and `reuse_key`. Agents should prefer `response_profile="minimal"` or `"compact"`, pass a stable `reuse_key` for repeated logical queries, reuse cache-hit/pointer responses, and fetch exact detail only through `local_ai_artifact` slices. Do not weaken the budget to expose broad command output or repository text.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

### Adaptive context and supported capabilities

Call `local_ai_repo(action="context", mode="adaptive")` first after one-time asynchronous preprocessing. Send the task/context directly with the stable absolute root; reuse candidates and evidence IDs before new abstractions. Supply the current phase (`plan`, `discover`, `edit`, `implementation`, `review`, `test`, or `handoff`), plus `task_id`, `focus`, and `preload_profile` when known. Deterministic/indexed evidence remains authoritative; optional Serena/RAG backends enrich it and degrade independently. Models may rank or compress grounded evidence; they cannot invent repository facts.

`/api/context/pack` defaults to `adaptive`; explicit `fast` and `full` remain supported. HTTP guarded requests activate through `guarded=true`, `task_id`, `phase`, or `session_id`; MCP guard-only fields require `guarded=true`, `task_id`, or `phase`. `focus` and `changed_paths` are lists; `approval` is boolean or string and `override_reason` is a string. MCP `max_tokens` and `token_budget` must agree when both are nonzero. Scope/drift overrides need a reason and approval when requested. Raw model/debug detail remains opt-in through `extra_fields`.

Repository-only context can use the available bounded retrieval result when optional backends degrade. A pack requested with `task_id` requires a complete task-context receipt: missing/unavailable compilation returns `context_task_context_unavailable`; missing, stale, or incomplete provenance returns `context_task_context_incomplete`. Do not present either as successful task context or repeat/poll the same operation. Consume `task_context`, `context_id`/`task_context_id`, `etag`, revision, freshness, omitted sections and `next_action` where returned; keep partial/stale context explicit.

Feature-specific schemas expose only enabled tools/actions and applicable fields. Use installed `tools/list` input/output schemas and the generated schema for that configuration: `dry_run` and `edits` require `features.batch_replacement`; `local_ai_task` requires tasks plus a configured model. Internal adapters do not establish public MCP fields. CodeGraph remains optional external standalone tooling outside Hub setup/runtime; Hub does not install, configure, preprocess, invoke, or report it. Cloud reasoning and planning are never blocked by mandatory local handoffs. Source contracts do not establish physical GPU execution, model quality, or completed release acceptance.

### Project configuration, verification, and PathHints

Project configuration and PathHint core are integrated in current source. `resolve_project_context(root, state_dir)` returns immutable effective settings and a `config_digest`. Overlay order is defaults, primary-worktree `.local-ai.toml` when linked, current-project `.local-ai.toml`, Git-common `info/local-ai.toml`, then `.local-ai.worktree.toml`; invalid overlays select safe defaults with error codes. Project configuration stays in the project or Git common directory, while `state_dir` stores bounded, evidence-bound hints. Maps merge by key, lists replace as a whole, and explicit excludes and hard boundaries take precedence over force includes. Overrides cannot bypass root containment, binary policy, configured size limits, or preprocessing exclusions; request hints remain subordinate to root containment and hard exclusions.

`verification_rules` maps exact task acceptance-criterion names to receipt requirements: `true` requires configured `lint` and `test` receipts, and an array names exact configured command aliases. `required_commands` is not a global switch; it applies only when the task criterion has that exact name. The HTTP completion wrapper rejects invalid configuration or incomplete verification before checkpointing and completion. Source integration does not verify the full owner, tenant, revision, criterion, and memory-audit runtime matrix.

`shared_namespace` exposes a server-derived coordination identity and shares bounded path hints across linked worktrees under one Git common directory. It does not replace the physical repository root. Cross-worktree Agent OS memory sharing remains HOLD; memory and lease consumers must not be assumed to use this hint namespace.

`ProjectContext.prioritize_paths(...)` ranks the complete candidate list in this order: literal `entry_points`, request-scoped `path_hints`, then saved hints matching scope, repository revision, and config digest. It preserves every candidate and returns `PathHintUsage`; `hint_helped` stays unknown until measured. When a hint does not help, consumers use their broader fallback. Telemetry exposes usage flags without candidate paths. Save only verified hints.

`HubClient.post` forwards typed hints to `/api/search` only and strips them from `/api/command`; it accepts generic `path`, `payload`, and `timeout` parameters plus optional `request_id`, not hint-specific keyword arguments. HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` only in `adaptive` mode and validates them as lists. Current internal MCP adapters accept path controls, while generated public schema support must be checked in the installed `tools/list`; do not infer public wire support from internal methods.

Hints are repository-relative paths beneath the trusted project root; reject absolute, traversal, glob, missing, and symlink or junction escape paths. Request hints may omit evidence metadata. Learned hints require evidence ID, provenance, matching repository revision, and config digest. Revalidate saved paths when reading them, and never write raw paths or hint contents to telemetry.

### Runtime schemas, offline mode, and Agent OS memory

Use the installed `tools/list` input/output schema; action-specific fields and result shapes are not interchangeable. Schema presence is not authorization.

The operational-mode statements below describe the T13 target contract, not this T19 candidate's current runtime: `src/local_ai_hub/operational_mode.py` and its persisted gate are absent from this source tree. Do not rely on pause/resume or maintenance isolation as runtime enforcement until T13 is integrated and verified.

Operational modes are `active`, `gaming`, and `maintenance`: missing persisted state defaults to `active`; invalid/unreadable state degrades to `maintenance`. For gated actions, `gaming` permits non-heavy work and safe job actions `status`, `wait`, `result`, `cancel`, and `evaluation_report`. The required safety contract is stricter for maintenance: `maintenance` must reject every agent MCP/API action before Agent OS database access; operator-only mode, health, and dashboard controls remain available. The current maintenance safe-job exception fix remains pending integration and verification; do not interpret the existing exception as the required maintenance policy or claim maintenance isolation is accepted. Other gated work returns `terminal=false`, `retryable=true`, and `retry_after_seconds=5`; back off, do independent work, and avoid polling. `HubClient.ensure_server` does not auto-start an offline server in non-active or degraded mode.

`hubctl pause` sets `gaming` and `hubctl resume` sets `active`. When Hub is offline, `pause` and `resume` update persisted mode without starting the server; offline `mode` and `status` read that persisted state. An offline pause reports no available runtime unload backend; it is not physical GPU/VRAM evidence.

For durable work, create and checkpoint one Agent OS task contract before edits. On restart, resume the existing task with the same `task_id`. Record memory with scope-appropriate provenance; repository-scoped memory requires provenance tied to the trusted project root.

`local_ai_task(task_id=...)` automatically compiles task context before a semantic model call and attaches `task_context_id`, `task_context_etag`, and `task_context_evidence_ids` on successful consumption. Memory selection filters scope/root/task/tenant/clone/worktree/branch before its bounded limit; only normal-sensitivity, unexpired `active`/`confirmed` memory becomes a candidate, then token budgeting selects what fits. Use IDs are selected `memory_record` elements' `element_id` values in compiled context. Non-use IDs are bounded diagnostics when `include_diagnostics=true`: `stale_ids`, `quarantined_ids`, `rejected_ids`, `superseded_ids`, and `legacy_unscoped_ids` (up to eight per category, subject to context budget). IDs show selection or exclusion, not proof that a model followed memory. Do not invent an exhaustive adoption/non-use receipt for every budget-omitted candidate.

Changed paths plus repository revision stale matching records. When optional memory is absent or excluded, fall through to fresh bounded repository evidence; never reuse stale memory as authoritative or label an incomplete task-context receipt successful. Keep use/non-use IDs in scoped context/evidence, not broad telemetry. `/api/adoption` stores low-cardinality aggregates, not memory bodies or per-record adoption receipts; never send prompts, source, model output, secrets, or raw/full project paths to telemetry.

If Hub is unavailable, make one bounded health/retry attempt, then use one native fallback. Native validation still requires `terminal=true` and `retryable=false`; never poll or repeat an identical operation.

### Memory adoption checkpoints

Agents must consider supplied relevant memory as advisory context and verify volatile facts against current source before relying on them. Before completion, checkpoint `state_data.memory_audit` through `local_ai_coord(action="task_checkpoint", task_id=..., checkpoint=...)`. `used_ids` must be a list of IDs from server-managed `memory_context.items[].id`; cite only findings actually used. `not_used_reason` must be nonempty when `used_ids` is empty, including when supplied memory was irrelevant or unavailable. Completion validates the audit when server memory items or warnings exist.

Normal `memory_record` elements use the raw record ID as `element_id`; TaskStore supplies the same ID in its memory items. Check the current server item allowlist before citing IDs. Do not invent IDs or copy `preload_memory_*` IDs into the audit. Do not replace or modify server-managed `memory_context`. Selection diagnostics alone do not establish use, and excluded IDs are not the checkpoint audit's used-ID allowlist.

For used volatile items, provide `source_checks` keyed by each used volatile record ID; each check needs nonempty `source` or an `evidence_ids` list containing a nonempty string. Record a real current-source check, not placeholder evidence. The completion gate checks audit shape and supplied-ID membership; it does not prove that a model followed memory or that a source reference is true.

Checkpoint payload examples below go in the `checkpoint` argument. Replace example IDs with exact currently supplied item IDs and source/evidence placeholders with verified current facts. Example use of a non-volatile supplied finding:

```json
{"state_data":{"memory_audit":{"used_ids":["supplied-record-id"]}}}
```

Example use of a volatile supplied finding, checked against current source:

```json
{"state_data":{"memory_audit":{"used_ids":["supplied-volatile-id"],"source_checks":{"supplied-volatile-id":{"source":"verified-current-source-reference","evidence_ids":["verified-current-evidence-id"]}}}}}
```

Example non-use:

```json
{"state_data":{"memory_audit":{"used_ids":[],"not_used_reason":"Supplied memory was reviewed but did not support this task."}}}
```

Save only confirmed reusable findings with scope-appropriate provenance and evidence. Never store chat history, prompts, source text, model output, secrets, or personal data. Use existing installed-schema memory actions: inspect the scoped prior record with `memory_get`, record a confirmed correction through `memory_record`, and use `memory_delete` only with the verified explicit scope identity when removal is appropriate. For corrections, preserve original source, provenance, evidence and prior-record linkage in the existing record/provenance workflow; no new memory store or invented correction alias. Keep unavailable/stale memory explicit, use fresh bounded source evidence, and record a truthful non-use reason rather than inventing use.

### Document and diagram ingestion

Document ingestion requires nonempty `content`; `title` and `metadata` are optional. On success it returns `success: true`, `workspace`, `document_title`, `chunks_ingested`, and `embedded` (`true` when at least one chunk has an embedding). Embedding failures do not stop lexical publication; chunks without embeddings remain searchable lexically. These methods do not return `embedding_status`, `ingest_publish_failed`, or a `retryable` flag.

Diagram ingestion requires an existing `image_path` with a supported image extension (`.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp`); `caption` and `metadata` are optional. Success adds `diagram_indexed` and the resolved `image_path` to the document result.

### LLM card synthesis scope

`disable_llm_card_synthesis` applies to fallback synthesis for unparsed file cards only. Module and project cards use separate `prefer_deterministic_modules` and `prefer_deterministic_project` settings; background LLM synthesis may still run when deterministic card generation does not satisfy its acceptance conditions.
