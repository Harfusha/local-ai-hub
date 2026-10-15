# Generic Agent Update & Upgrade Prompt for Local AI Hub

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to upgrade an existing Local AI Hub installation from V3 to V4 from the canonical `master` branch, upgrade dependencies, restart services, and refresh the repository's instruction policies.

## Current security and tool contract

Transport clients defer hardware inventory when `hardware.auto_tune=false`; servers still inventory devices, and automatic tuning preserves its hardware-derived overlay. On Windows, a newly started shared supervisor receives a retained Job Object handle so it survives adapter exit; failed startup uses the owned Job Object to clean up descendants.

Loopback connection establishment uses the smaller of `client.health_timeout_seconds` and the remaining request deadline. After connecting, response reads retain the remaining request deadline; an absent listener cannot consume that response budget before autostart.

Compact context responses retain exact evidence citations and original success/error decisions. Source excerpts in `evidence.raw` stay behind evidence IDs for `local_ai_artifact`; they do not consume the protected metadata budget.

Hugging Face embeddings and rerankers load cached model files offline by default. Set `models.allow_hf_downloads=true` only with explicit operator approval for missing model downloads; a cache error alone never authorizes a network retry. Existing cached CPU fallback models remain available without this opt-in.

Local AI Hub has no remote-access or remote-control mode. HTTP binds only to `127.0.0.1`; HubClient and supervisor probes always target `127.0.0.1`. The dashboard and stdio MCP adapter use loopback HTTP only as same-machine transport. Remote host, client-host, and origin overrides are rejected. Protected routes require credentials and route permissions. `security.api_token` uses coarse `api_token_permissions`; `security.supervisor_token` grants administrative read/write only; `security.action_tokens` map exact actions to credentials; `security.users` maps users to unique tokens, exact resource scopes, and optional tenants. Credential values must be unique and redacted from diagnostics. `client.startup_wait_seconds` defaults to `30.0`.

`local_ai_repo` validates actions against its supported registry. `skeletonize` transforms supplied source text only; it does not inspect a repository. `generate_tests_for_diff` returns manual, skipped test scaffolds; it is not test-pass evidence. `local_ai_status` telemetry, agent-state, and `traces` details avoid the live-status request; `traces` accepts bounded `min_duration_ms` and `trace_action` filters.

MCP aliases normalize before endpoint dispatch: `local_ai_command` accepts `root` for `cwd` and `changed_paths` or `files` for `paths`; `local_ai_repo` accepts `cwd` for `root`, `paths` or `files` for `changed_paths`, and `symbol` for `query`. Explicit canonical parameters take precedence, including empty lists. On `/api/context/pack`, presence of `changed_paths` or `focus` requests guarded handling, including an empty list; explicit `guarded` values must be boolean.

For `local_ai_command(action="flaky_detect")`, `runs` is an integer execution count with minimum `1` and default `5`; MCP clients validate the published schema, and the command endpoint receives the selected count.

## Development workflow (binding)

Follow [`docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md`](superpowers/specs/2026-10-07-simplified-worktree-integration.md). The primary agent owns audits, implementation, and integration; do not create audit handoffs, ZIPs, custom owner packets, or routine fingerprints/hash cascades. Work in current `master` by default. Create branches/worktrees only for necessary isolation or genuinely independent parallel implementation. Integrate small verified units into `master` promptly. Preserve all unmerged work; inspect and record every remaining change before recoverable archival. This rule supersedes older delegation and handoff wording below.

Operator maintenance: error resolution shares a bounded deadline and rolls back failed SQLite writes. Exhausted SQLite busy/locked errors at an HTTP request boundary return HTTP 503 with `success:false`, `degraded:true`, and `error:"database_locked"`. GET responses are retryable; POST responses set `outcome_unknown=true`, `terminal=true`, and `retryable=false` because a shared boundary cannot prove whether an action already took effect. Failed writes remain failures and never claim an in-memory substitute or SQLite commit. A rejected authorization audit blocks a mutating admin action; its failed result audit returns HTTP 503 with `outcome_unknown=true` and `retryable=false`, because the action may already have completed. Never replay it automatically. Authorized reads remain available with observability disabled. Scoped Agent OS status reports readiness only, not global task/memory counts. Ordinary agent responses must not include operator diagnostics by default.

Gaming unload uses GET `/api/ps` before and after POST `/api/generate` with `keep_alive=0`, sharing one cancellation/deadline budget. Empty verified inventory is not proof of physical VRAM reclamation. Task completion rejects malformed checkpoint generations, including boolean values that Python otherwise compares equal to integers.

Agent OS memory adoption must be verified through the actual MCP transport after installation:
new/resumed tasks receive a small relevant advisory bundle with memory IDs, origin, scope,
version and validity, without requiring an extra `memory_find` or `extra_fields` call.
Checkpoints cite used IDs or a non-empty reason for not using relevant items; volatile facts
must be checked against current source. `memory_context` is server-managed, never caller-editable.
An unavailable lookup returns a bounded warning and does not block the task. Verify the full
serialized memory/response budget, not content-only estimates. Automatic guard proposals stay
`CANDIDATE`; only explicitly approved guard decisions become `CONFIRMED`. Manual operator facts
remain supported. Never automatically retain chats, source/prompt/model-output fields, secrets
or personal data. Reconnect existing MCP adapters after upgrading; passing store/HTTP tests
alone does not prove that the agent received the bundle or used it.

Routing source contract: hardware profile selects role targets; `router.apply_model_override` rejects overrides below the configured quality floor. Model names are routing targets, not proof of installed models; pulls remain opt-in. Semantic local tasks stay on-demand after deterministic/indexed evidence; cloud reasoning and planning never require a mandatory local handoff.

Local model routing starts from `[hardware].profile="auto"`; hardware detection or an explicit profile selects a role map, then user overrides apply. Model `qwen2.5-coder:1.5b` is preprocessing-only. In order `background_code/fast_code/heavy_code/reasoning/general/vision`: cpu=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3-vl:4b`; integrated=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3-vl:4b`; low=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3-vl:4b`; balanced=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3.5:9b`; high=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`; max=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`. Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`. These are routing targets, not proof that models are installed; model pulls remain opt-in. Run deterministic and indexed Hub actions first for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, exploration, reasoning, review, independent second opinions and compression.
Semantic local-model assistance is optional and on-demand. It does not authorize handing off audits or repository ownership.

Before changing model routing or claiming a model switch is safe, measure supported hardware/backend cohorts and attach revision-bound quality, latency, and VRAM evidence before and after. Model output is advisory, not verification.

Pinned-source limitation (master `2458f72c`, 2026-10-06): routing quality floors, operational modes, and client identity/transport safeguards are source contracts, not deployed runtime proof. HTTP root authorization and complete maintenance isolation remain separate acceptance gaps. Preserve the configured preprocessing provider. This pinned source has no Gemini preprocessing provider implementation; Gemini agent manifests do not prove such support. Do not invent, install, or infer a Gemini preprocessing implementation. Prior candidate instructions and receipts in `handoff/` and checkpoint history are historical, not current acceptance. Configuration and the returned response-budget envelope are authoritative; generated prose may retain an older budget value.

---

```markdown
# TASK: Upgrade Local AI Hub from V3 to V4 and Refresh Repository Instructions

You are an autonomous AI engineering agent. Your task is to upgrade **Local AI Hub** from V3 to V4 on this system using the canonical `master` branch, update dependencies, restart the background service, re-verify health, and refresh the Local AI Hub Tool Policy and Token Economy Policy in this repository.

Preserve privacy-safe adoption telemetry: it contains only normalized aggregate tool/action/intent/outcome, time, latency, and output-size buckets. Never migrate or expose prompts, source, secrets, absolute paths, or raw request records. Bypasses require an explicit client signal.

Registered HTTP endpoint labels remain readable in request history and error operations; strip query strings/fragments and normalize dynamic identifiers. Filesystem paths and unregistered path-like labels remain redacted. Historical `<path>` records cannot reconstruct their original endpoint.

Validate input/output JSON Schemas from the installed MCP `initialize`/`list_tools` exchange, not only the schema generator. Empty `allOf`/`anyOf`/`oneOf` arrays are invalid. Reconnect existing MCP clients after a catalog update.

Detailed execution traces are opt-in, dashboard-only, and stored locally. While enabled, preserve complete endpoint inputs and outputs, paths, and trace events while redacting credential values; do not truncate ordinary payload content. Page large content for retrieval. Keep storage bounded through retention and whole-trace eviction, never by trimming trace content. Leave detailed traces disabled by default and keep the default aggregate telemetry lightweight.

Follow these execution phases:

---

### PHASE 1: LOCATE INSTALLATION & CHECK OUT VERIFIED V4 COMMIT

Use only the exact 40-character verified commit SHA issued by the T20 release owner; do not substitute the moving `master` tip. First preserve and inspect the canonical installation checkout. If it is dirty, stop and preserve those changes. Fetch the canonical remote only after that check, confirm the verified SHA is available from `origin/master`, then check out that exact SHA (detached checkout is acceptable). Confirm `git rev-parse HEAD` equals the verified SHA and `git status --porcelain=v1 --untracked-files=all` is empty before running setup. The installer repeats both checks before it changes the install. Never copy another candidate checkout over the running root.

1. **Locate Installation Directory**:
   - Windows: `$HOME\.local-ai-hub` (or `%USERPROFILE%\.local-ai-hub`)
   - Linux / macOS: `~/.local-ai-hub`
2. **Protect Local Changes**:
   - Run `git status --short` before changing branches.
   - If the installation worktree is dirty, preserve the changes and stop for operator review. Never use `git reset --hard`, `git checkout -- .`, or discard local configuration/source changes.
3. **Fetch the Verified Commit from Canonical Master**:
   - Confirm the T20 verified commit is reachable from `origin/master`. Do not use the old `codex/v4.0-hardening` feature branch for installations.
   - Fetch `master`, verify ancestry, then check out the exact commit:
     ```bash
     git -C "$HOME/.local-ai-hub" fetch --prune origin
     git -C "$HOME/.local-ai-hub" cat-file -e "<T20_VERIFIED_COMMIT_SHA>^{commit}"
     git -C "$HOME/.local-ai-hub" merge-base --is-ancestor "<T20_VERIFIED_COMMIT_SHA>" origin/master
     git -C "$HOME/.local-ai-hub" checkout --detach "<T20_VERIFIED_COMMIT_SHA>"
     ```
   - When synchronizing local `master` itself, use `git pull --ff-only origin master`; never create an implicit merge commit or rebase local work. Install only the separately verified commit after ancestry checks.
     *(On Windows PowerShell: fetch origin, verify the commit object and `git -C "$HOME\.local-ai-hub" merge-base --is-ancestor "<T20_VERIFIED_COMMIT_SHA>" origin/master`, then check out that SHA detached.)*

---

### PHASE 2: RUN UPDATE / RE-SETUP

Run only after Phase 1 confirms the exact verified commit and a clean checkout. Pass the same SHA to the platform installer; a missing, dirty, or mismatched revision is a hard stop. Keep the existing per-user service identity and shared HTTP Hub singleton; do not register another service for a chat, agent, repository, or worktree.

After setup, from the verified installation root install the complete declared non-Intel extra set into the active environment: `python -m pip install --upgrade ".[ast-index,local-nlp,token-economy,performance,profiling,dev]"`. This includes NLP and development/profiling dependencies and may require substantial disk/time. Keep `intel-accelerators` opt-in for an explicitly requested Intel host; CodeGraphContext is independent and is not a Hub dependency. Then fully stop the existing service, confirm it is stopped, start the same service, and verify `python tools/hubctl.py status` plus `python tools/doctor.py`. Preserve configuration and durable state; never create a second service or reset databases for an ordinary update.

On Windows, prefer Task Scheduler identity `LocalAIHubSupervisor`; if registration is denied, verify the per-user Run-key fallback (`windows-user-startup`). A detached Hub alone does not prove reboot-persistent service registration.

Run the platform installer with the active hardware profile to apply dependency updates, regenerate MCP schemas/manifests, and update skills. Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex `cwd=install_dir` is not the caller's project root, and setup injects no project-root environment. Repository-scoped repo/RAG MCP actions now reject missing or `.` roots at the adapter boundary; preprocessing likewise requires an explicit absolute root. Always pass the caller's explicit project root. This source-level guard still needs fresh installed-runtime and deployment proof. Pinned source includes operational modes and client transport safeguards. Rootless repository targeting and end-to-end HTTP identity isolation remain separate acceptance gaps; source integration is not deployed runtime proof. `HubClient` autostart is bounded and guarded by a cross-process lock; an existing managed supervisor or listener blocks another daemon launch. Treat generated agent command, arguments, working directory and environment as authoritative; inspect the installer-generated MCP entry instead of inventing proxy arguments or environment. Project-local MCP manifests use `target_root` as `cwd`; global manifests use `install_dir`. For each global repository, task, or memory request, set the request's `root` to the caller's project root and preserve task context; never infer root from `install_dir` or process cwd. `HubClient` preflights root-scoped task/memory identities with configured allowed roots, a principal, and an HMAC-derived tenant. HTTP `_tenant` still accepts caller labels outside token-bound browser routes; client validation does not establish server-enforced isolation. Required T04 transport contract: `request_not_sent` means delivery did not begin; `outcome_unknown` means delivery may have occurred and must never be replayed automatically. The source client distinguishes pre-send transport failures (`request_not_sent=true`) from uncertain delivery (`outcome_unknown=true`), supports cancellation, and preserves explicit request identity. Confirm behavior with same-revision targeted checks; installation and cross-process runtime acceptance remain separate. The HTTP server is loopback-only: keep `[server].bind = "127.0.0.1"`. There is no remote-access switch. `server.client_host`, `security.allow_remote`, `security.allowed_hosts`, and `security.allowed_origins` overrides are removed and rejected. On loopback, empty `api_token` leaves HTTP data/control routes unauthenticated; configure a token to protect them. When configured, send the token in `X-LocalAI-Token` or `Authorization: Bearer`; `/health` and the dashboard shell are public. The HTTP server does not expose `api_token_permissions` or a general principal-to-root authorization boundary. The client validates configured `allowed_roots` and root-derived task/memory tenant consistency; HTTP admin routes additionally support scoped `security.action_tokens`. HTTP tenant scope uses caller-provided `X-LocalAI-Tenant`, then `X-Tenant-ID`, then `http-default`; tenant label is not an authorization boundary. For correct repository targeting, pass the caller project root explicitly. Repo/RAG MCP actions reject omitted or `.` roots before transport; preprocessing likewise rejects a missing absolute root. Root targeting does not provide authorization or root-isolated tenant behavior. Server-enforced root isolation remains unverified; do not infer it from client preflight. Inspect provider config first: Ollama is selected when `[ollama].enabled = true` and its install/model pulls still require the existing explicit opt-ins (`server.auto_start_ollama = true`, `llama_cpp.fallback_to_ollama = true`). If Ollama is disabled, `llama_cpp.mode = "on"` provisions the pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `"auto"` uses only a configured existing endpoint; `"off"` disables it. Never switch providers silently or start `ollama serve` as a fallback. Pull `models.vision` only for an explicitly enabled Ollama backend and `features.vision = true`:
RAG index and search derive the existing canonical workspace ID from the caller's explicit root when `workspace` is empty or an absolute path; they preserve explicit workspace IDs and send both `root` and `workspace` to their endpoints.

Before updating or rolling back, stop the single per-user Hub service, record its platform service-manager identity and enabled state separately, then back up the installation, `config.toml`, complete configured `server.state_dir`, and every managed agent MCP config file together; include SQLite `-wal` and `-shm` files. Caches are disposable and do not contain durable tasks, receipts, jobs, memory, or leases. Restore only declared roots and preserve data outside the rollback write set. Use matching daemon code, Hub config, state and proxy registrations as one rollback set; do not point an older release at newer state. Service registration is external to the file snapshot; reconcile that same service once with the restored release before starting it. Never register per agent, chat, or worktree.

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -ExpectedRevision "<T20_VERIFIED_COMMIT_SHA>" -Profile auto
  ```
- **Linux / macOS (Bash)**:
  ```bash
  bash "$HOME/.local-ai-hub/install.sh" --expected-revision "<T20_VERIFIED_COMMIT_SHA>" --profile auto
  ```

---

### DURABLE ASYNC JOBS AND CONVERSATIONS

Operational-mode and client lifecycle code are present in the pinned source. Source presence and old candidate receipts do not establish installed service, restart, clean-host, or maintenance-isolation acceptance.

Keep the async contract aligned across MCP, HTTP, and `HubClient`. Supported `job_action` values are `batch`, `compress`, `delegate`, `reason`, `review`, `review_diff`, `route`, `second_opinion`, and `speculative_lint`. HTTP delivery maps `/api/delegate`, `/api/reason`, `/api/review`, `/api/review/diff`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` to these actions. `delivery="sync"` is default; `delivery="async"` submits immediately. `delivery="auto"` needs positive `latency_budget_ms` and at least ten endpoint observations whose p95 exceeds that budget; sparse history stays inline. For `/api/review/diff`, an exceeded positive `review.max_queue_age_ms` takes precedence. Otherwise, fewer than five telemetry samples plus a positive budget selects async with reason `cold_start_review_diff`. Conversations require sync delivery.

Use `local_ai_task(action="submit", job_action=..., request_id=<stable body key>)` for durable submission. `POST /api/async-jobs` accepts `action="submit"`, `job_action`, and optional stable `request_id`; controls use `action="status"|"wait"|"result"|"cancel"`, `job_id`, and wait `timeout_seconds`. `HubClient.submit_async_job` and lifecycle helpers use the same endpoint. Preserve `job_id`, `state`, `artifact_id`, and `expires_at`. Result TTL defaults to 259,200 seconds (72 hours). Timed-out waits return `wait_timeout_seconds` and do not cancel jobs. Running cancellation reports `cancel_requested=true` before worker completion. Recovery replays only replay-safe actions with matching tenant, action, payload, stable `request_id`, and remaining attempts; other uncertain work becomes terminal `outcome_unknown`.

Start conversations synchronously with `POST /api/delegate` or `POST /api/reason`, `conversation=true`, and `delivery="sync"`. Continue through `/api/conversations/continue` with `conversation_id=..., task=..., context=...`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`. `HubClient.continue_conversation` maps its prompt to `task`. `HubClient has no dedicated start helper`; use `HubClient.post`. Conversations are scoped to the server-derived effective tenant, allow 12 user turns by default, and use a prompt limit of 56,000 by default. Idle TTL is 900 seconds; active TTL is 1,800 seconds. State and transcripts disappear on restart.

If this checkout includes `docs/PYTHON_SDK.md`, consult it for the Python package's `HubClient`, install extras, and replay/error contracts before writing Python integration code.

Working-checkout release checks ignore disposable Python/pytest caches already covered by `.gitignore`. Use `python tools/release_check.py --allow-installed` in a live installed checkout. Use `--strict-tree` for a clean release tree; never combine it with `--post-test` or `--allow-installed`. Do not delete caches merely to make an ordinary checkout check pass.

### PHASE 3: VERIFY SERVICE, MCP, AND HEALTH

Managed Ollama ownership is bound to its executable and creation identity, state directory, role, and (on Windows) a unique named Job Object. A separate service CLI may stop only that verified process tree. A numeric PID or occupied port never grants ownership. Already-running external Ollama endpoints are borrowed without takeover; their configured profile remains unverified. Preserve unknown ownership records and report stop failure rather than killing an unverified process.

`hubctl cleanup` calls `/api/agent-state/cleanup` with a 3-second timeout and `auto_start=False`; it never starts Hub. Port occupancy alone is not kill authority. Listeners without verified ownership are reported in `skipped_ports` with reason `ownership_unverified`, not terminated or reported as cleaned.

Verify `hubctl.py service-status` and exactly one platform user-service entry: Windows Task Scheduler `LocalAIHubSupervisor`, macOS LaunchAgent `com.localai.hub`, or Linux systemd user unit `local-ai-hub.service`. Reconcile the existing registration; do not register a service per agent, chat, or worktree. A `detached-fallback` result does not prove reboot-persistent service acceptance. Setup exits nonzero if registration fails or is only detached fallback. Preserve the installer output, inspect the same service-manager entry and logs, and recover or rerun using the same clean verified SHA; do not claim update complete until one persistent service is confirmed.

1. **Verify Health Endpoint**:
   ```bash
   curl -s http://127.0.0.1:11435/health
   ```
   Must return `{"success":true,"hub_online":true,"version":"..."}`. `/health` is public liveness; this candidate has no `/ready` route. Setup reconciles or restarts the service; do not issue a second unconditional restart. If health fails, capture installer output and service logs, stop, and report the failure. Run `python tools/hubctl.py service-status` and `python tools/hubctl.py dashboard`; inspect the URL and confirm it is loopback-only. Confirm each enabled agent uses the installer-generated stdio registration.
2. **Run Doctor Diagnostic**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\doctor.py"
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/doctor.py"
     ```
3. **Reinitialize and Verify MCP**: restart/reload the Codex MCP host after setup so its stdio adapter imports the updated package. Confirm MCP `tools/list` and one bounded `tools/call` succeed. Record the observed adapter/daemon version and executable/module path only when needed to diagnose a mismatch; do not build a routine fingerprint or hash-manifest process. Keep any `outcome_unknown` mutation gate closed; never replay it automatically.
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
- For `local_ai_rag(action="ingest_document")`, non-empty `content` is required; `title` and `metadata` are optional. Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`. Embedding errors do not stop lexical publication. For `ingest_diagram`, `image_path` must resolve to an existing `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file; `caption` and `metadata` are optional. Success also returns `diagram_indexed` and the resolved image path.
- Contract notes: `local_ai_status.detail` uses `brief`, `cache`, `telemetry`, `full`, `agent_state`, or `traces`; `traces` accepts bounded `min_duration_ms` and `trace_action` filters. `action` also accepts `status`, `health`, `check`, and `info` aliases. `local_ai_repo(action="pipeline")` accepts closed step objects with a supported action and per-step `id`/`result`; run no more than four steps in parallel. Repository pipelines serialize preprocessing mutation actions with other mutating steps. `local_ai_artifact(action="list")` does not require `artifact_id`; `binary` is supported and binary payloads are never inlined. `local_ai_artifact(action="slice", slices=[{"offset": 10, "max_chars": 40}, ...])` fetches up to 16 ordered text ranges in one `/api/artifact/get` call; offsets are zero-based, and combined requested characters stay within `compact_max_text_chars`. Multi-slice mode excludes sections, binary artifacts, and evidence IDs. `local_ai_coord(action="pubsub_poll")` accepts `after_seq` from 0 through 2^63-1; `local_ai_coord` bounds `max_tokens` to 0 through 100000.
- `local_ai_command` accepts optional `env` as a mapping from variable names to string values. MCP publishes string-valued entries, and the command broker applies overrides to the child process while preserving its existing name, count, and value validation. Keep values short and task-specific; do not put credentials in prompts or repository files.
- Preserve the `trim-run` safety boundary: only its bundled token tools and read-only search CLIs may be launched; use `local_ai_command` for tests/builds and arbitrary validation commands.
- For durable work, require one `local_ai_coord(action="task_create")` contract, phase changes through `local_ai_coord(action="task_checkpoint")`, and one bounded wait instead of status polling loops.
- Use `local_ai_coord(action="ask", root=..., session_id=..., question=...)` to persist a human question. Retrieve it with the returned `question_id` and same root/session; record operator response with `action="answer"` under the authenticated root and tenant. Do not include credentials.
- For every non-trivial repository task, after one-time preprocess make `local_ai_repo(action="context", mode="adaptive")` the first useful operation. It accepts the task/context directly and fuses deterministic/indexed evidence, CodeIndex, Serena, bounded lexical search and RAG; it ranks cross-backend agreement, deduplicates, preserves file diversity and degrades optional backends independently. Do not send a hand-built grep-term list or start native search first.
- Keep routing boundaries explicit: repository navigation/symbols/impact=`local_ai_repo`; exact source/log slices=`local_ai_artifact`; test/lint/typecheck/build=`local_ai_command`; task contracts/checkpoints/receipts and persistent human questions=`local_ai_coord`; task-wide context=`local_ai_coord(action="context_compile", task_id=...)`; optional semantic model assistance=`local_ai_task(...)`; deterministic/indexed tools remain authoritative for exact facts, symbols, diffs, and tests. Use `local_ai_work` only when the user explicitly requests a closed delegated task; audits and ordinary repository ownership stay with the primary agent.
- Bounded health/cache/telemetry/debug-trace inspection uses `local_ai_status`; never poll. Use only tool names, actions, arguments, defaults, and feature-gated options present in the installed generated schema. The schema is authoritative for the installed version; do not infer support from internal APIs or another release.
- Semantic delegation is on-demand: after deterministic/indexed evidence, use `local_ai_task` selectively for bounded generation, review, independent second opinions, test-log compression, commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Treat local output as advisory only; queued work, stale context, missing evidence or weak grounding remains visible with explicit metadata and must not be silently discarded. Preserve exceptions for architecture, security, mutations, open-ended coding, exact evidence and verification. Shared specialized prompt contracts and model capability limits live in `docs/MODEL_CAPABILITIES.md`.
- Treat workspace memos and leases as trusted-local shared coordination state; tenant labels are caller-supplied provenance, not identity or authorization. Workspace memos are keyed by canonical workspace and key. Use `expected_version` from a memo read when `memo_put` must reject stale overwrites; a `version_conflict` returns the current generation, so reread and reconcile before retrying. Omission retains last-writer-wins; deletion advances the generation while expiration does not.
- Preserve native fallback gate: only after Hub returns `terminal=true` and `retryable=false`. Mutations never cache or single-flight.
- Keep `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` enabled in the installed default profile, while preserving independent rollback switches. Code intelligence also defaults on through `features.code_intelligence`, `code_intelligence.enabled`, and `code_intelligence.serena_enabled`; all three gates must allow Serena use, and an unavailable Serena backend degrades to indexed retrieval. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Malformed values must remain disabled and disabled features must return structured unavailable before work starts. `local_diagnostic_dispatch=true` may retain only bounded failure-preview context for one local diagnosis; it never retains raw output and does not require `diagnostic_artifacts=true`.
- For `batch_replace`, require `features.batch_replacement=true`, then preview with explicit `dry_run=true`; `staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. Keep rollback behavior and never auto-commit replacements. Set `dry_run=false` only after review.
- Keep generated contracts aligned: `local_ai_status.action` accepts feature-enabled status details including `traces`, plus `status`, `health`, `check`, and `info` aliases. `traces` accepts `min_duration_ms` and `trace_action`. `local_ai_repo(action="verify_receipt")` requires `receipt.task_id`, `receipt.criterion`, and boolean `receipt.passed`; `passed=true` also requires non-empty `receipt.evidence_id`. `/api/search` timeout must not exceed 120 seconds.
- Repository search and code-index queries accept integer `offset` and `limit`; public defaults are `offset=0` and `limit=24`. `limit` is at most 200 and `offset + limit` is at most 2048. Successful responses include exact integer `total_matches`, boolean `has_more`, `offset`, and the effective `limit`; code-index may apply its configured result cap. MCP returns the full requested page or an explicit response-budget error. HTTP pages over 4 MiB return 413 with pagination metadata. Exact repository search streams at most 8,000 eligible files per request and fails explicitly if the scan cannot complete; never return a prefix count as complete metadata.
- Operation argument validation rejects non-finite numbers, including nested values. Status bypass reports require `adoption_signal="bypassed"`, a supported `target_tool`, and a supported `target_action` for that tool. Preserve the shared MCP output envelope and action-scoped input constraints.

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

After updating, verify the generated schemas under the installation's `generated/` directory expose `max_response_tokens`, `response_profile` (default `"compact"`), and `reuse_key` on the existing Hub tools. These are installation artifacts, not checked-in source files. Treat generator output and configuration as trusted repository inputs; never copy tool fields from untrusted model output. Keep aggregate response budgeting enabled, preserve artifact-backed exact detail, and verify telemetry reports raw/projected/saved response estimates without prompt or source retention.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

Use only actions and arguments present in the installed generated schema. Schema presence is not authorization: process-lifecycle actions such as `spawn_daemon` require an explicit policy capability grant. Do not infer support for extra fields from similarly named APIs.

### Async lifecycle and conversations

`submit` accepts a stable body `request_id` for idempotent replay; `X-LocalAI-Request-ID` remains a separate journal identifier. `status`, `wait`, `result`, and `cancel` must remain usable when model execution is disabled. Cap wait duration by `async_jobs.wait_max_seconds` and by `max_request_timeout` after reserving a bounded transport margin. Compact lifecycle responses must retain `job_id`, `state`, and `artifact_id`. `HubClient.submit_async_job`, `HubClient.async_job_status`, `HubClient.wait_async_job`, `HubClient.async_job_result`, and `HubClient.cancel_async_job` expose the lifecycle; default wait transport timeout is the requested duration plus 30 seconds, capped by `max_request_timeout`.

Direct HTTP lifecycle requests use `POST /api/async-jobs`: submit sends `action="submit"`, `job_action`, and optional stable `request_id`; controls send `action="status"|"wait"|"result"|"cancel"` with `job_id`, and wait also sends `timeout_seconds`. MCP uses `local_ai_task(action=submit|status|wait|result|cancel, ...)`. The `HubClient` methods above use the same HTTP path. Recovery may replay only explicitly replay-safe actions with a stable `request_id`, matching tenant/action/payload identity, and remaining attempts; command-backed or unclassified actions become terminal `outcome_unknown`.

Start synchronously with HTTP `POST /api/delegate` or `POST /api/reason`, setting `conversation=true` and `delivery="sync"`, or MCP `local_ai_task(action="delegate"|"explore"|"reason", conversation=true, delivery="sync")`. HubClient has no dedicated start helper; use `HubClient.post("/api/delegate", payload)` or `HubClient.post("/api/reason", payload)`. Continue with HTTP POST `/api/conversations/continue` using `conversation_id`, `task`, and optional `context`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`; `HubClient.continue_conversation(conversation_id, prompt, context=...)` maps `prompt` to HTTP `task`. Conversations are tenant-scoped; their model, system prompt, output limit, temperature, and route are pinned at start. Only one turn may run at once; a concurrent call reports retryable in-progress.

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

`HubClient.post` accepts optional `request_id`, `path_hints`, `tenant`, and `cancel_event`. It bounds typed hints and forwards them to `/api/search` and `/api/command`; an explicit `path` removes those hints. HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` in `adaptive` mode and validates lists. T14 owns that contract. Inspect installed generated schemas before using public wire fields.

Hints are repository-relative paths beneath the trusted project root; reject absolute, traversal, glob, missing, and symlink or junction escape paths. Request hints may omit evidence metadata. Learned hints require evidence ID, provenance, matching repository revision, and config digest. Revalidate saved paths when reading them, and never write raw paths or hint contents to telemetry.

### Runtime schemas, offline mode, and Agent OS memory

Use the installed `tools/list` input/output schema; action-specific fields and result shapes are not interchangeable. Schema presence is not authorization.

`src/local_ai_hub/operational_mode.py` and its persisted gate are present in this source tree. Pause/resume source contracts can be checked locally; deployment and complete maintenance isolation require separate runtime evidence.

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

Ordinary MCP agent responses omit telemetry, diagnostics, raw command streams, timing,
and automatic routing advice. Request specific details with `extra_fields` or an explicit
`response_profile="debug"`; use artifacts for complete logs. Outcome, safety, context
identity, and evidence fields remain available. Explicit status reports remain supported.

SSE replay uses numeric Last-Event-ID with an explicit stream filter. Consume replay
events/gaps in cursor order; replay_page advances the cursor only after safe delivery,
including filtered pages. Reset the cursor when changing the stream or kind filter.
Supervisor health reason codes belong to operator diagnostics, not normal agent output.
Full status requires success, hub_online and version; diagnostic fields are optional.

`disable_llm_card_synthesis` applies to fallback synthesis for unparsed file cards only. Module and project cards use separate `prefer_deterministic_modules` and `prefer_deterministic_project` settings; background LLM synthesis may still run when deterministic card generation does not satisfy its acceptance conditions.

CodeGraphContext/KuzuDB was removed from Local AI Hub. Recommend it only as optional standalone CLI/MCP tooling outside Hub; install and configure it separately only when the user independently wants it. It is not a Hub dependency, runtime, backend, or MCP integration.

`disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs. It does not disable module/project cards: `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences, and either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold. Check active configuration and backend state before claiming synthesis is disabled.

<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
Trigger map:
- bounded health/cache/telemetry/debug-trace inspection (never poll): `local_ai_status`
- GPU pressure status uses cached telemetry without waiting for hardware probes. A pending single-flight refresh returns conservative, explicitly stale pressure/budget metadata. Explicit benchmark sampling still requests a bounded fresh sample; stale status is not benchmark evidence.
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- non-trivial multi-step, long-running, or acceptance-criteria work: `local_ai_coord` Agent OS task contracts, checkpoints, context, and verified completion
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`
- `local_ai_work`: only when the user explicitly requests closed delegation; routine work stays with the primary agent
- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available
- indexed skeletons: `local_ai_repo(action="skeletonize", root=ABS_ROOT, path=FILE)` without inline source returns a bounded symbol/signature outline with mtime/size freshness checks and no source-body reads. Imports, decorators, docstrings and bodies are explicitly omitted; missing/stale indexes require indexing or explicit source. Supplying source in `query` retains the inline transformation mode, where `path` selects a target symbol.
- AST rename accepts explicit `old_symbol` and `new_symbol`: `local_ai_repo(action="ast_refactor", root=ABS_ROOT, path=FILE, old_symbol="before", new_symbol="after")`. Explicit names take precedence over the existing query/task and diff mappings; `staged=False` (the default) keeps the dry run.
- SQLite navigation caches observe cross-process commits through `PRAGMA data_version`; deterministic source-table mutations advance project generations and invalidate persistent query results. Cache freshness does not establish whole-repository coverage or release acceptance.
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`
- image understanding/frontend review via `qwen3-vl:4b`: `local_ai_task(action="vision")`
- screenshot comparison uses `local_ai_task(action="vision", baseline_screenshot_artifact_id=..., screenshot_artifact_id=...)`. Both PNG artifacts must belong to the current tenant and have equal viewport dimensions (at most 16 megapixels each). The existing image-byte limits and configured local vision model apply; model availability/cancellation errors stay visible. The `comparison` result identifies both source hashes and byte equality; semantic findings remain model observations requiring review. Cloud fallback is disabled for comparison.
- headless DOM and screenshot capture: `local_ai_task(action="browser", url="http://localhost:3000")`. The shared daemon runs at most two captures, using installed Chrome/Chromium (`LOCAL_AI_CHROME` may select its executable). A controlled proxy restricts HTTP(S) destinations, redirects, and subresources to literal loopback addresses; HTTP inspection permits GET/HEAD/OPTIONS without request bodies. Each capture has a 20-second browser timeout, a 1 MB DOM cap, and an 8 MiB PNG cap. The response contains a bounded DOM preview, `dom_artifact_id`, and `screenshot_artifact_id`; retrieve complete stored payloads with `local_ai_artifact`. Optional `viewport` dimensions are bounded to 320–3840 by 240–2160. No browser installation or model pull occurs automatically.
- mock server start uses an ephemeral loopback port when omitted or zero (`local_ai_command(action="mock_server_start", command="0")`); retain the returned `port` for status/stop. Explicit nonzero ports remain supported. Recorded mock cassettes retain only safe response headers; authorization and cookie headers are excluded.
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

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, search coordination memos for reusable findings. For overlapping multi-agent edits use `local_ai_coord` leases and store concise reusable discoveries as memos.
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
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned. `artifact_id` may refer to a diagnostic preview or partial capture. `discarded_output_chars` counts characters omitted during capture or response compaction; capture obeys both `max_output_chars` and `max_output_bytes`. A full artifact can retain characters omitted from the response. MCP trimming also sets `output_truncated=true`.
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
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Local model routing follows the active hardware profile and user overrides; use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions and compression. Consult `docs/MODEL_CAPABILITIES.md`; configured routes do not prove models are installed. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests.
<!-- END TOKEN ECONOMY POLICY -->

Explicit `extra_fields` retains requested empty values (for example `records=[]`); absence of a field does not prove an empty result. Aggregate response budgets still apply.

Status metadata may reuse a successful dependency snapshot for up to five seconds after its probe completes. `dependency_cached` and `dependency_age_ms` identify reuse in dependency diagnostics. Live/full and process/window snapshots remain separate; expired data and failed probes do not become healthy results. Status probe deadlines and active worker limits remain unchanged.

Transport clients defer physical hardware inventory and automatic tuning to the shared server, including when `hardware.auto_tune=true`. Explicit user/runtime overrides remain intact; the server owns hardware-aware model selection and retains its full hardware probe. Client route declarations do not prove detected hardware or installed models.

MCP cancellation closes the current request's HTTP connection. For direct command `run`, disconnect cancels that request's execution; a coalesced waiter cannot cancel the execution owner. Embedded requests follow the same request lifetime rule. The shared Hub remains independent. A sent request with no final response remains `outcome_unknown`; do not retry it automatically.

## Durable task checkpoints and bounded waits

For non-trivial multi-step work, create a durable Agent OS task with `local_ai_coord(action="task_create")` before edits. Record phase changes with `local_ai_coord(action="task_checkpoint")`, then complete only after verification receipts satisfy the acceptance criteria. For asynchronous work, perform one bounded wait; never poll.

## Current public contract notes

- `local_ai_rag(action="ingest_document")`
- non-empty `content` is required; `title` and `metadata` are optional.
- Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`.
- Embedding errors do not stop lexical publication.
- `image_path` must resolve to an existing `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file; `caption` and `metadata` are optional.
- Success also returns `diagram_indexed` and the resolved image path.
- `local_ai_repo(action="pipeline")` accepts closed step objects.
- `local_ai_artifact(action="list")` does not require `artifact_id`.
- `local_ai_coord(action="pubsub_poll")` accepts `after_seq`.
- `local_ai_coord` bounds `max_tokens` to 0 through 100000.
- Repository pipelines serialize preprocessing mutation actions with other mutating steps.
- Optional repository-analysis tools are installed and configured separately; they are not part of the Hub.
- `disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs.
- It does not disable module/project cards:
- `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences.
- either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold.
- Check active configuration and backend state before claiming synthesis is disabled.

## Repository symbol navigation

For indexed symbol lookup, use `local_ai_repo(action="code_index", root=ABS_ROOT, query="symbol")`. For managed Serena navigation when available, use `action="semantic", relation="find_symbol"` with the same tool.

Follow the published typed action/detail enums. Optional `speculative_lint` and Agent OS actions are exposed only when their modules are enabled.

## Local telemetry

Basic aggregate telemetry remains enabled locally. Detailed request traces are disabled by default and can be toggled live in the dashboard. When enabled, they retain complete endpoint input/output locally, including sensitive values, within configured size and retention limits. Local telemetry and trace details stay on this device; only normal agent responses requested by cloud agents leave it.
