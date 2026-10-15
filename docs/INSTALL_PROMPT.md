# Generic Agent Installation & Integration Prompt for Local AI Hub

HTTP identity comes from authenticated/configured server state or its stable tokenless principal. `X-LocalAI-Tenant` is only a claim; obsolete `X-Tenant-ID` is rejected after host/origin validation and before authorization. Reauthorization clears cached principal/root identity. Agent State client sandbox activation matches the server; enabled sandboxes keep configured-principal, derivation-secret and nonempty allowlist requirements. Repository memory lookup uses server-resolved project identity, never a caller's replacement repository ID. Updating these contracts does not rewrite operator configuration.

Omitted retrieval mode selects `adaptive` consistently in MCP, HTTP context packs, Agent OS context compile, and client/service entry points. Explicit `fast` and `full` select current distinct strategies; invalid modes reject before retrieval. Query, focus, changed paths, or omitted guarded fields never silently select an older mode. Pubsub adapters use the current full poll signature, preserving both sequence and timestamp cursors without adapting old providers or coercing client cursor values.

Event and incident storage accepts only current durable schemas. Older event layouts, payload-version override tables, incident ID fabrication and automatic column upgrades are rejected rather than converted. Current producer definitions govern schema validation; prior fingerprints are not compatibility alternatives. Existing durable data is retained for explicit recovery.

Agent State uses `agent_state.sqlite`; old standalone filenames are never copied or merged automatically. Old-only state or an invalid canonical target hiding an old history is rejected while retaining the files. Archived old files alongside readable canonical state remain untouched. Unsupported durable schemas require explicit operator recovery; disposable derived metadata may rebuild.

Task contracts require a nonempty string `goal`. Persisted title-only or missing-goal contracts are rejected without rewriting their contents. HTTP creation accepts a current contract object or the advertised goal/task shorthand; old intent/title/query coercions are removed. Completion requires the current full verification contract and rejects obsolete evaluator signatures.

Persistent Biome lint uses only the reviewed Windows Biome 2.5.15 foreground-server protocol. The Hub verifies named-pipe ownership against its retained process, bounds source reads and IPC, and retains ownership when cleanup is unconfirmed. Unsupported versions/platforms return explicit unsupported results; they never adopt or stop a shared daemon. Installed behavior and performance require separate validation.

`secret_scan` history coverage is bounded to textual changed lines in the requested reachable `HEAD` commits (default 20, integer depth 1..100). It is not a scan of all refs or every historical tree. Shared time, byte, line and finding limits, omitted merge/binary patches, malformed provenance or incomplete process capture prevent a complete/clean claim. History findings retain commit, path, added/removed status and exact hunk line; credential values stay masked.

Use only canonical advertised actions and fields. Short action aliases and the `local_ai_status.action` selector are rejected; status uses `detail`. Each HTTP operation has one canonical route, with distinct operations retaining their own routes. For MCP `secret_scan`, `staged=true` requests history; omit `path` for the whole repository or supply a literal path filter. `query`/`task` are not path aliases or history controls. HTTP accepts only the boolean `scan_git_history` field and validates supplied history depth without coercion. Capability grants cannot authorize after expiration or with malformed expiry; delegation preserves denials and cannot exceed remaining parent depth. Do not add legacy behavior, migration shims or backward-compatibility fallbacks.

Agent OS POST action selectors must be strings in exact lowercase underscore syntax; whitespace, hyphens, case normalization and string coercion are rejected before dispatch. HTTP blackboard actions are `update`, `get`, `list`, `merge`, `delete`; public MCP `blackboard_*` actions map to these once. HTTP task cleanup, reaping and dataset selectors are `cleanup_worktree`, `reap_expired`, `curate_dataset`; verification export uses `export`. Alternate HTTP action names are rejected. Current scope and mutation-policy denials still apply, including the `reap_expired` denial without a scoped mutation contract. Omitted selectors retain only documented endpoint defaults.

Task create/checkpoint/fail/transition/complete forward their actual MCP response budget to server-side full-memory preflight. Automatic worktree creation prepares and binds exact response metadata before Git mutation; preparation failure does not silently create an ordinary task. Completion preflights the final checkpoint and records `cleanup_pending`/`cleanup_scheduled`; maintenance later removes only eligible clean owned worktrees. A Git creation followed by failed SQLite persistence is an applied/unknown cross-store outcome, never a verified rollback or `operation_not_started=true`. Supervisor locks require current structured ownership proof; model unloading requires a complete canonical inventory with endpoint receipts. A coherent empty inventory does not prove physical VRAM reclamation.

VRAM pressure policy requires coherent measured usage and capacity for the same memory pool. Unavailable, malformed or inventory-only samples yield conservative unknown pressure. Raw reported usage remains separate from `policy_pressure_pct`, `policy_headroom_mb`, `policy_measurement_basis` and `policy_pressure_is_derived`; zero reported usage cannot cancel a higher measured pressure bound. RuntimeTuner rejects invalid measurements before updating profiles and uses the configured state directory (a private process fallback for partial configuration).

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to bootstrap Local AI Hub, configure background services and MCP, and integrate the tool and token economy policies into repository instructions.

## Current security and tool contract

Static `security_audit` reports findings, HIGH release blockers, triage status and scan coverage separately. A test path alone never dismisses a credential-like value; such findings remain untriaged. MEDIUM findings prevent an `is_clean=true` verdict. Limits, unreadable/oversized sources, parse failures and time/byte bounds make the scan incomplete. Counts describe visited project-filtered inventory entries; unknown total eligibility is explicit. Source credential values are omitted from ordinary finding snippets. Coverage and decision fields survive response compaction; this static report is not live exploit or whole-repository release proof.

Artifact text reads use one snapshot and incremental SQLite reads of at most 64 KiB per block, retaining only bounded requested spans. Unicode and NUL remain intact; reads do not write paging metadata. A shared five-second read deadline covers section discovery and retrieval. Section names are capped at 50 / 512 characters, with explicit omission metadata; JSON section parsing admits at most 1,000,000 source bytes and rejects duplicate keys. Derived sidecar metadata is capped before materialization; startup indexing admits at most 128 bodies of at most 1,000,000 bytes each. Core IDs, tenant bindings and binary contents remain durable. Text offsets and lengths require strict integers; section windows stop at their own boundaries. Runtime memory/latency acceptance remains separately required.

Whisper CLI transcription requires approved cached checkpoint bytes by default. `transcription.allow_model_downloads=true` is an explicit operator opt-in for missing/corrupt weights; truthy non-boolean values do not authorize downloads. The optional `transcription.cache_dir` overrides the upstream XDG/home cache. Cached official checkpoints are verified with cancellation, a 30-second hash deadline and a 5-GiB size cap; aliases use canonical filenames. The CLI receives a verified local path and explicit `--device cpu`; non-CPU device requests are rejected until a separate admission path exists. Existing process timeout and tree cleanup remain in force. Native Whisper/WER, device resource use and real cache behavior still require separate validation.

On Windows, command strings use native Unicode `CommandLineToArgvW` parsing with matching `LocalFree` cleanup. Inline values such as `--junitxml="C:/path with spaces/report.xml"` reach the child without literal wrapping quotes. Internal structured invocations retain argv boundaries and serialize with Windows quoting; literal arguments should use structured argv rather than shell syntax. Native argument parsing does not grant execution authorization.

`generate_types` returns stub text only; it never writes `.pyi` files, and nonempty `diff` or `write_stub=true` is rejected. Resolved source paths stay inside the selected repository root and reads are bounded. Batch delegation accepts at most 16 tasks and rejects a larger batch before routing or execution, with exact counts and bounded rejection details. SQLite maintenance reports attempted/succeeded/failed stores and partial failures; it performs checkpoints and `PRAGMA optimize`, without promising VACUUM.

Use `local_ai_artifact(action="source", path="src/example.py", line_start=1, line_end=5)` for exact workspace source lines. Relative and absolute paths must resolve inside the adapter workspace. This read-only action caps each file at 4 MiB, each range at 200 lines, and returned text at `max_chars` (512–12000); it returns the source SHA-256 and actual returned line range. `line_end=0` selects up to 80 lines from `line_start`. Text truncation is explicit; aggregate response compaction must return the exact selected text or an error. Artifact `get`/`slice` remain artifact-ID operations; undocumented `start_line`/`end_line` source aliases are not published. Malformed output-envelope fields produce a typed, nonretryable contract error naming the field; unknown boolean values are never silently converted to false.

Command execution is fail-closed: `allowed=false` is always rejected before cache reuse or process creation, including legacy `policy_blocking=false`. Unknown commands default to denied; explicit `commands.allow_unknown=true` does not authorize host execution. They also require mutation permission, a task-owned worktree, declared paths, a current work-attempt fence, and the private transaction boundary. Operator configuration is not rewritten when updating packaged defaults.

Transport clients defer hardware inventory when `hardware.auto_tune=false`; servers still inventory devices, and automatic tuning preserves its hardware-derived overlay. On Windows, a newly started shared supervisor receives a retained Job Object handle so it survives adapter exit; failed startup uses the owned Job Object to clean up descendants.

Loopback connection establishment uses the smaller of `client.health_timeout_seconds` and the remaining request deadline. After connecting, response reads retain the remaining request deadline; an absent listener cannot consume that response budget before autostart.

Compact context responses retain exact evidence citations and original success/error decisions.

Archived source copies under docs/integration/archive are excluded from current-source indexing; ordinary documentation remains searchable. Code-index pages may return fewer complete symbols than requested to fit the wire budget; follow next_offset when has_more is true. Unknown optional stale flags are omitted; consult freshness status instead of assuming current data. Complexity and secret scans report their bounded scope and incomplete coverage; success alone is not whole-repository acceptance. Source excerpts in `evidence.raw` stay behind evidence IDs for `local_ai_artifact`; they do not consume the protected metadata budget.

Hugging Face embeddings and rerankers load cached model files offline by default. Set `models.allow_hf_downloads=true` only with explicit operator approval for missing model downloads; a cache error alone never authorizes a network retry. Existing cached CPU fallback models remain available without this opt-in.

Local AI Hub has no remote-access or remote-control mode. HTTP binds only to `127.0.0.1`; HubClient and supervisor probes always target `127.0.0.1`. The dashboard and stdio MCP adapter use loopback HTTP only as same-machine transport. Remote host, client-host, and origin overrides are rejected. Protected routes require credentials and route permissions. `security.api_token` uses coarse `api_token_permissions`; `security.supervisor_token` grants administrative read/write only; `security.action_tokens` map exact actions to credentials; `security.users` maps users to unique tokens, exact resource scopes, and optional tenants. Credential values must be unique and redacted from diagnostics. `client.startup_wait_seconds` defaults to `30.0`.

`local_ai_repo` validates actions against its supported registry. `skeletonize` transforms supplied source text only; it does not inspect a repository. `generate_tests_for_diff` returns manual, skipped test scaffolds; it is not test-pass evidence. `local_ai_status` telemetry, agent-state, and `traces` details avoid the live-status request; `traces` accepts bounded `min_duration_ms` and `trace_action` filters.

MCP aliases normalize before endpoint dispatch: `local_ai_command` accepts `root` for `cwd` and `changed_paths` or `files` for `paths`; `local_ai_repo` accepts `cwd` for `root`, `paths` or `files` for `changed_paths`, and `symbol` for `query`. Explicit canonical parameters take precedence, including empty lists. On `/api/context/pack`, presence of `changed_paths` or `focus` requests guarded handling, including an empty list; explicit `guarded` values must be boolean.

`local_ai_command` accepts optional `env` as a mapping from variable names to string values. MCP publishes string-valued entries, and the command broker applies overrides to the child process while preserving its existing name, count, and value validation. Keep values short and task-specific; do not put credentials in prompts or repository files.

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

Before changing model routing or claiming a model switch is safe, measure supported hardware/backend cohorts and attach revision-bound quality, latency, and VRAM evidence before and after. Model output is advisory, not verification.


Pinned-source limitation (master `2458f72c`, 2026-10-06): routing quality floors, operational modes, and client identity/transport safeguards are source contracts, not deployed runtime proof. HTTP root authorization and complete maintenance isolation remain separate acceptance gaps. Preserve the configured preprocessing provider. This pinned source has no Gemini preprocessing provider implementation; Gemini agent manifests do not prove such support. Do not invent, install, or infer a Gemini preprocessing implementation. Prior candidate instructions and receipts in `handoff/` and checkpoint history are historical, not current acceptance. Configuration and the returned response-budget envelope are authoritative; generated prose may retain an older budget value.
---

```markdown
# TASK: Install, Verify, and Integrate Local AI Hub in Environment & Repository

You are an autonomous AI engineering agent. Your task is to install and configure **Local AI Hub** on this system (if not already installed or running), verify all components (service, configured local backends, token economy suite, code intelligence), ensure MCP integration, and inject the canonical tool and token economy policies into this repository's agent instructions. Ollama is disabled unless explicitly opted in.

Hub adoption telemetry is aggregate-only: retain normalized tool/action/intent/outcome plus time, latency, and output-size buckets. Never send prompts, source, secrets, absolute paths, or raw request records. Mark a bypass only when the client explicitly signals one; do not infer it from missing Hub calls.

Registered HTTP endpoint labels remain readable in request history and error operations; strip query strings/fragments and normalize dynamic identifiers. Filesystem paths and unregistered path-like labels remain redacted. Historical `<path>` records cannot reconstruct their original endpoint.

Validate input/output JSON Schemas from the installed MCP `initialize`/`list_tools` exchange, not only the schema generator. Empty `allOf`/`anyOf`/`oneOf` arrays are invalid. Reconnect existing MCP clients after a catalog update.

Detailed execution traces are opt-in, dashboard-only, and stored locally. While enabled, preserve complete endpoint inputs and outputs, paths, and trace events while redacting credential values; do not truncate ordinary payload content. Page large content for retrieval. Keep storage bounded through retention and whole-trace eviction, never by trimming trace content. Leave detailed traces disabled by default and keep the default aggregate telemetry lightweight.

Treat workspace memos and leases as trusted-local shared coordination state; tenant labels are caller-supplied provenance, not identity or authorization. Workspace memo endpoints require an authorized unscoped operator; tenant-scoped agents use supplied task memory or permitted Agent OS memory_find/memory_record. Workspace memos are keyed by canonical workspace and key. Use `expected_version` from a memo read when `memo_put` must reject stale overwrites; a `version_conflict` returns the current generation, so reread and reconcile before retrying. Omission retains last-writer-wins; deletion advances the generation while expiration does not.

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

Run the platform installer from the repository root. This automatically configures Python 3.11+, the virtual environment, Token Economy tools, backend-appropriate local model support, Serena in an isolated environment, global MCP configs, and the background supervisor. Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex `cwd=install_dir` is not the caller's project root, and setup injects no project-root environment. Repository-scoped repo/RAG MCP actions now reject missing or `.` roots at the adapter boundary; preprocessing likewise requires an explicit absolute root. Always pass the caller's explicit project root. This source-level guard still needs fresh installed-runtime and deployment proof. Pinned source includes operational modes and client transport safeguards. Rootless repository targeting and end-to-end HTTP identity isolation remain separate acceptance gaps; source integration is not deployed runtime proof. `HubClient` autostart is bounded and guarded by a cross-process lock; an existing managed supervisor or listener blocks another daemon launch. Treat generated agent command, arguments, working directory and environment as authoritative; inspect the installer-generated MCP entry instead of inventing proxy arguments or environment. Project-local MCP manifests use `target_root` as `cwd`; global manifests use `install_dir`. For each global repository, task, or memory request, set the request's `root` to the caller's project root and preserve task context; never infer root from `install_dir` or process cwd. `HubClient` preflights root-scoped task/memory identities with configured allowed roots, a principal, and an HMAC-derived tenant. HTTP `_tenant` still accepts caller labels outside token-bound browser routes; client validation does not establish server-enforced isolation. Required T04 transport contract: `request_not_sent` means delivery did not begin; `outcome_unknown` means delivery may have occurred and must never be replayed automatically. The source client distinguishes pre-send transport failures (`request_not_sent=true`) from uncertain delivery (`outcome_unknown=true`), supports cancellation, and preserves explicit request identity. Confirm behavior with same-revision targeted checks; installation and cross-process runtime acceptance remain separate. The user service starts again after reboot when the user session starts. Ollama is installed or pulled only when `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. When Ollama is disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`, then supervises its loopback server; Intel Windows tries SYCL and falls back to CPU. `mode = "auto"` detects an existing endpoint only; `"off"` disables llama.cpp. Ollama wins provider selection whenever enabled. Setup must never switch providers silently or install Ollama as a fallback. The HTTP server is loopback-only: keep `[server].bind = "127.0.0.1"`. There is no remote-access switch. `server.client_host`, `security.allow_remote`, `security.allowed_hosts`, and `security.allowed_origins` overrides are removed and rejected. On loopback, empty `api_token` leaves HTTP data/control routes unauthenticated; configure a token to protect them. When configured, send the token in `X-LocalAI-Token` or `Authorization: Bearer`; `/health` and the dashboard shell are public. The HTTP server does not expose `api_token_permissions` or a general principal-to-root authorization boundary. The client validates configured `allowed_roots` and root-derived task/memory tenant consistency; HTTP admin routes additionally support scoped `security.action_tokens`. HTTP tenant scope uses caller-provided `X-LocalAI-Tenant`, then `X-Tenant-ID`, then `http-default`; tenant label is not an authorization boundary. For correct repository targeting, pass the caller project root explicitly. Repo/RAG MCP actions reject omitted or `.` roots before transport; preprocessing likewise rejects a missing absolute root. Root targeting does not provide authorization or root-isolated tenant behavior. Server-enforced root isolation remains unverified; do not infer it from client preflight. Set `features.vision = false` to remove vision capability and its model pull. The default install deploys the `token-economizer` skill and registers its CLI directory on the user's persistent PATH; verify both after setup, then open a new terminal. Do not pass `--skip-token-economy` or `--skip-companion-skills` for the standard install.
RAG index and search derive the existing canonical workspace ID from the caller's explicit root when `workspace` is empty or an absolute path; they preserve explicit workspace IDs and send both `root` and `workspace` to their endpoints.

After bootstrap, install all declared non-Intel Python extras in the active environment with `python -m pip install --upgrade ".[ast-index,local-nlp,token-economy,performance,profiling,dev]"` from the verified installation root. Do not install `intel-accelerators` unless the operator explicitly requests Intel acceleration; CodeGraphContext is independent and must not be installed as part of the Hub. Once setup and dependency installation finish, fully stop the existing per-user service, confirm it is stopped, start that same service, then verify with `python tools/hubctl.py status` and `python tools/doctor.py`. Preserve configuration and durable `server.state_dir`; do not register another service or reset data during a normal restart.

CodeGraphContext/KuzuDB was removed from Local AI Hub. Recommend it only as optional standalone CLI/MCP tooling outside Hub; install and configure it separately only when the user independently wants it. It is not a Hub dependency, runtime, backend, or MCP integration.

On Windows, prefer the persistent `LocalAIHubSupervisor` scheduled task. If task registration is denied, accept and verify the documented per-user Run-key fallback (`windows-user-startup`); do not report a detached process as reboot-persistent.

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

Working-checkout release checks ignore disposable Python/pytest caches already covered by `.gitignore`. Use `python tools/release_check.py --allow-installed` in a live installed checkout. Use `--strict-tree` for a clean release tree; never combine it with `--post-test` or `--allow-installed`. Do not delete caches merely to make an ordinary checkout check pass.

---

### DURABLE ASYNC JOBS AND CONVERSATIONS

Operational-mode and client lifecycle code are present in the pinned source. Source presence and old candidate receipts do not establish installed service, restart, clean-host, or maintenance-isolation acceptance.

Keep the async contract aligned across MCP, HTTP, and `HubClient`. Supported `job_action` values are `batch`, `compress`, `delegate`, `reason`, `review`, `review_diff`, `route`, `second_opinion`, and `speculative_lint`. HTTP delivery maps `/api/delegate`, `/api/reason`, `/api/review`, `/api/review/diff`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` to these actions. `delivery="sync"` is default; `delivery="async"` submits immediately. `delivery="auto"` needs positive `latency_budget_ms` and at least ten endpoint observations whose p95 exceeds that budget; sparse history stays inline. For `/api/review/diff`, an exceeded positive `review.max_queue_age_ms` takes precedence. Otherwise, fewer than five telemetry samples plus a positive budget selects async with reason `cold_start_review_diff`. Conversations require sync delivery.

Use `local_ai_task(action="submit", job_action=..., request_id=<stable body key>)` for durable submission. `POST /api/async-jobs` accepts `action="submit"`, `job_action`, and optional stable `request_id`; controls use `action="status"|"wait"|"result"|"cancel"`, `job_id`, and wait `timeout_seconds`. `HubClient.submit_async_job` and lifecycle helpers use the same endpoint. Preserve `job_id`, `state`, `artifact_id`, and `expires_at`. Result TTL defaults to 259,200 seconds (72 hours). Timed-out waits return `wait_timeout_seconds` and do not cancel jobs. Running cancellation reports `cancel_requested=true` before worker completion. Recovery replays only replay-safe actions with matching tenant, action, payload, stable `request_id`, and remaining attempts; other uncertain work becomes terminal `outcome_unknown`.

Start conversations synchronously with `POST /api/delegate` or `POST /api/reason`, `conversation=true`, and `delivery="sync"`. Continue through `/api/conversations/continue` with `conversation_id=..., task=..., context=...`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`. `HubClient.continue_conversation` maps its prompt to `task`. `HubClient has no dedicated start helper`; use `HubClient.post`. Conversations are scoped to the server-derived effective tenant, allow 12 user turns by default, and use a prompt limit of 56,000 by default. Idle TTL is 900 seconds; active TTL is 1,800 seconds. State and transcripts disappear on restart.

### PHASE 3: VERIFY SERVICE & HEALTH

Managed Ollama ownership is bound to its executable and creation identity, state directory, role, and (on Windows) a unique named Job Object. A separate service CLI may stop only that verified process tree. A numeric PID or occupied port never grants ownership. Already-running external Ollama endpoints are borrowed without takeover; their configured profile remains unverified. Preserve unknown ownership records and report stop failure rather than killing an unverified process.

`hubctl cleanup` calls `/api/agent-state/cleanup` with a 3-second timeout and `auto_start=False`; it never starts Hub. Port occupancy alone is not kill authority. Listeners without verified ownership are reported in `skipped_ports` with reason `ownership_unverified`, not terminated or reported as cleaned.

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
- Python structural comparison: `local_ai_repo(action="semantic_diff", root=ABS_ROOT, old_code=..., new_code=...)` classifies definition renames/moves/reordering and AST edits, returning a qualified-scope change tree and a full-result `artifact_id`. Ambiguous correspondences remain explicit; structural candidates do not prove equivalent behavior. Each source is limited to 1 MiB UTF-8 with bounded AST depth/node/definition counts. HTTP previews are bounded; retrieve full results through `local_ai_artifact`. Omitting the source pair preserves the existing call-graph diff mode.
- SQLite navigation caches observe cross-process commits through `PRAGMA data_version`; deterministic source-table mutations advance project generations and invalidate persistent query results. Cache freshness does not establish whole-repository coverage or release acceptance.
- Symbol queries recheck indexed mtime/size even on cache hits; `stat_current_candidates` does not prove content hashes. Explicit content verification remains stronger. Stale results carry `stale=true`, reduced confidence and coalesced notifications to the registered project's existing background reindexer; paused/background-disabled projects remain under operator control.
- Affected-test selection filters candidates by the detected runner's language, reports `excluded_incompatible_tests`, and quotes selected paths. Unknown or incompatible-only selections do not silently run unrelated files through pytest or count excluded files as executed tests.
- `local_ai_repo(action="git_diff", root=ABS_ROOT, rev1="HEAD~3", rev2="HEAD")` compares the merge base of the two pinned commits to rev2 (`rev1...rev2`). Supply both revisions, without `staged`; optional `path` is literal. Results include resolved commit IDs and `stats_complete`; truncated previews do not prove complete statistics. Omit both revisions for the existing working-tree/index behavior.
- `resolve_imports` suggests imports only from bounded, current indexed candidates with static named-export checks. Missing, stale, nested or unproven exports remain unresolved with rejection reasons. This does not execute modules or prove runtime import success; dynamic/re-export forms requiring additional target proof remain explicit. Requests accept at most 64 symbol names of at most 512 characters.
- `local_ai_status(detail="guide")` (or `action="guide"`) returns compact feature-aware tool cards locally, without a health/model request. Required fields refer to each card's example action; full schemas remain authoritative for other actions. Examples contain placeholders and are not executed. Schema-token savings require a current baseline measurement.
- Mock `spec_path` supports JSON `routes` with `path_regex` and string `query_matchers` (`*`/`?`), or OpenAPI operation extensions `x-local-ai-path-regex` / `x-local-ai-query-matchers`. Regex grammar excludes groups, alternatives/backreferences and more than one repetition; invalid or oversized specs fail before bind. Literal route text is escaped, and template parameters occupy whole segments. This matcher format is separate from recorded response cassettes.
- Async job status/wait includes durable `progress_percent`, `current_stage` and `progress_available`. Running progress is reported work, capped at 99; 100 requires a done job with available result artifact. Reports are tenant/attempt/lease scoped and throttled; progress does not prove success or justify polling an in-progress job.
- On selected Ollama memory-allocation errors, generation may halve `num_ctx` once within the existing attempts/deadline, with `context_recovery` metadata. A smaller window that cannot retain the input is refused; prompts/evidence and configured device are not silently changed. Partial output/thinking prevents replay. This does not establish llama.cpp/SYCL recovery or live VRAM proof.
- `scheduler.idle_timeout_seconds` defaults to 300 (0 disables). The existing dispatcher releases only its idle owned active model, with no queued/inflight work or GPU reservation. This scheduler residency limit is independent of provider keep_alive. Release requests have a five-second deadline; unconfirmed release clears affinity for fresh preparation, without a retry loop. `request_accepted` is not physical VRAM proof.
- Task creation with criteria or `paths` may schedule bounded adaptive-context warmup in active mode. It predicts the task goal, task/session/root/tenant and 4,000-token request; cache reuse requires matching request identity and current source/memory state. `preprocessing.task_context_warmup=false` disables it. Queue admission is not context proof, receipt validation or a guaranteed cache hit.
- `tokcount --json` and `context_budget` distinguish offline exact named-encoding counts from uncalibrated estimates in `token_count_provenance`. Existing cl100k/o200k cache data must pass its hash check; missing/corrupt data never triggers an implicit download. Exactness is for the reported encoding and decoded input, not every local/cloud model. Aggregate `estimated_tokens` wire-budget units remain unchanged; heuristic slice recommendations are marked separately.
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`
- durable agent questions and operator answers: `local_ai_coord(action="ask"|"answer")`; pass explicit `root` and `session_id`; server binds tenant; retrieve with same scope and `question_id`
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

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, reuse supplied task memory; when more is needed, use permitted scoped `local_ai_coord(action="memory_find")`. Workspace `memo_*` actions are unavailable through tenant-scoped endpoints; on terminal 403 do not retry or bypass scope. For overlapping edits use `local_ai_coord` leases; record concise findings in permitted scoped Agent OS memory or the existing operator-approved coordination file.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression, `local_ai_work` only for closed delegation explicitly requested by the user, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases/memos and Agent OS task, memory, context, and verification workflows.

`local_ai_artifact(action="slice", artifact_id=..., slices=[{"offset": 10, "max_chars": 40}, ...])` returns up to 16 ordered text ranges in one call. Offsets are zero-based and ranges end at `offset + max_chars`; combined requested characters stay within `compact_max_text_chars`. Multi-slice reads support text artifacts only; use the regular single-page request for sections, and use the existing binary or evidence retrieval path for those payloads.

Local model policy: Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Preprocessing follows its configured provider; do not switch it silently. Pinned master `2458f72c` has no Gemini preprocessing provider implementation; Gemini agent manifests do not establish runtime preprocessing support. Routing targets do not prove installed-model availability; model pulls remain opt-in. Check installed-model inventory before live inference; do not infer runtime availability, output quality, or performance from a configured mapping.
## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, context identity and lifecycle identity (operation/job/request IDs, accepted/completed/in_progress, delivery outcome); keep exact detail artifact-backed. Acceptance does not prove completion. A budget error does not authorize replay of a side effect.
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
- Preserve protected status, error, evidence, context identity and lifecycle identity (operation/job/request IDs, accepted/completed/in_progress, delivery outcome); keep exact detail artifact-backed. Acceptance does not prove completion. A budget error does not authorize replay of a side effect.
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
- Preserve protected status, error, evidence, context identity and lifecycle identity (operation/job/request IDs, accepted/completed/in_progress, delivery outcome); keep exact detail artifact-backed. Acceptance does not prove completion. A budget error does not authorize replay of a side effect.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

### Async lifecycle and conversations

The body `request_id` is the job idempotency key; `X-LocalAI-Request-ID` is a separate HTTP journal identifier. MCP `status`, `wait`, `result`, and `cancel` controls work even when model execution is disabled. A wait is capped by `async_jobs.wait_max_seconds` and the client's `max_request_timeout` after reserving the configured quick-timeout margin. Preserve `job_id`, `state`, and `artifact_id` from compact status results. `HubClient` exposes `submit_async_job`, `async_job_status`, `wait_async_job`, `async_job_result`, and `cancel_async_job`; wait transport timeout defaults to the requested wait plus 30 seconds, capped by `max_request_timeout`.

Direct HTTP lifecycle requests use `POST /api/async-jobs`: submit sends `action="submit"`, `job_action`, and optional stable `request_id`; controls send `action="status"|"wait"|"result"|"cancel"` with `job_id`, and wait also sends `timeout_seconds`. MCP uses `local_ai_task(action=submit|status|wait|result|cancel, ...)`. `HubClient.submit_async_job`, `HubClient.async_job_status`, `HubClient.wait_async_job`, `HubClient.async_job_result`, and `HubClient.cancel_async_job` use the same HTTP path. Recovery may replay only explicitly replay-safe actions with a stable `request_id`, matching tenant/action/payload identity, and remaining attempts; command-backed or unclassified actions become terminal `outcome_unknown`.

Start synchronously with HTTP `POST /api/delegate` or `POST /api/reason`, setting `conversation=true` and `delivery="sync"`, or MCP `local_ai_task(action="delegate"|"explore"|"reason", conversation=true, delivery="sync")`. HubClient has no dedicated start helper; use `HubClient.post("/api/delegate", payload)` or `HubClient.post("/api/reason", payload)`. Continue through HTTP POST `/api/conversations/continue` with `conversation_id`, `task`, and optional `context`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`; `HubClient.continue_conversation(conversation_id, prompt, context=...)` maps `prompt` to HTTP `task`. The conversation ID is opaque and tenant-scoped. Model, system prompt, output limit, temperature, and route are pinned when it starts; only one turn may run at once, and a concurrent continuation returns retryable in-progress status.

Keep `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` enabled in the installed default profile, while preserving independent rollback switches. Code intelligence also defaults on through `features.code_intelligence`, `code_intelligence.enabled`, and `code_intelligence.serena_enabled`; all three gates must allow Serena use, and an unavailable Serena backend degrades to indexed retrieval. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Malformed values must remain disabled and disabled features must return structured unavailable before work starts. `local_diagnostic_dispatch=true` may retain only bounded failure-preview context for one local diagnosis; it never retains raw output and does not require `diagnostic_artifacts=true`.

Keep generated contracts aligned: update both canonical prompts when public schemas, feature flags, endpoint limits, or default behavior change.

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
Repository search and code-index queries accept integer `offset` and `limit`; public defaults are `offset=0` and `limit=24`. `limit` is at most 200 and `offset + limit` is at most 2048. Successful responses include exact integer `total_matches`, boolean `has_more`, `offset`, and the effective `limit`; code-index may apply its configured result cap. MCP returns the full requested page or an explicit response-budget error. HTTP pages over 4 MiB return 413 with pagination metadata. Exact repository search streams at most 8,000 eligible files per request and fails explicitly if the scan cannot complete; never return a prefix count as complete metadata.

Hints are repository-relative paths beneath the trusted project root; reject absolute, traversal, glob, missing, and symlink or junction escape paths. Request hints may omit evidence metadata. Learned hints require evidence ID, provenance, matching repository revision, and config digest. Revalidate saved paths when reading them, and never write raw paths or hint contents to telemetry.

### Runtime schemas, offline mode, and Agent OS memory

Use the installed `tools/list` input/output schema; action-specific fields and result shapes are not interchangeable. Schema presence is not authorization.

`src/local_ai_hub/operational_mode.py` and its persisted gate are present in this source tree. Pause/resume source contracts can be checked locally; deployment and complete maintenance isolation require separate runtime evidence.

Operational modes are `active`, `gaming`, and `maintenance`: missing persisted state defaults to `active`; invalid/unreadable state degrades to `maintenance`. For gated actions, `gaming` permits non-heavy work and safe job actions `status`, `wait`, `result`, `cancel`, and `evaluation_report`. The required safety contract is stricter for maintenance: `maintenance` must reject every agent MCP/API action before Agent OS database access; operator-only mode, health, and dashboard controls remain available. The current maintenance safe-job exception fix remains pending integration and verification; do not interpret the existing exception as the required maintenance policy or claim maintenance isolation is accepted. Other gated work returns `terminal=false`, `retryable=true`, and `retry_after_seconds=5`; back off, do independent work, and avoid polling. `HubClient.ensure_server` does not auto-start an offline server in non-active or degraded mode.

`hubctl pause` sets `gaming` and `hubctl resume` sets `active`. When Hub is offline, `pause` and `resume` update persisted mode without starting the server; offline `mode` and `status` read that persisted state. An offline pause reports no available runtime unload backend; it is not physical GPU/VRAM evidence.

For durable work, create and checkpoint one Agent OS task contract before edits. On restart, resume the existing task with the same `task_id`. Record memory with scope-appropriate provenance; repository-scoped memory requires provenance tied to the trusted project root.

`local_ai_task(task_id=...)` automatically compiles task context before a semantic model call and attaches `task_context_id`, `task_context_etag`, and `task_context_evidence_ids` on successful consumption. Memory selection filters scope/root/task/tenant/clone/worktree/branch before its bounded limit; only normal-sensitivity, unexpired `active`/`confirmed` memory becomes a candidate, then token budgeting selects what fits. Use IDs are selected `memory_record` elements' `element_id` values in compiled context. Non-use IDs are bounded diagnostics when `include_diagnostics=true`: `stale_ids`, `quarantined_ids`, `rejected_ids`, and `superseded_ids` (up to eight per category, subject to context budget). IDs show selection or exclusion, not proof that a model followed memory. Do not invent an exhaustive adoption/non-use receipt for every budget-omitted candidate.

Changed paths plus repository revision stale matching records. When optional memory is absent or excluded, fall through to fresh bounded repository evidence; never reuse stale memory as authoritative or label an incomplete task-context receipt successful. Keep use/non-use IDs in scoped context/evidence, not broad telemetry. `/api/adoption` stores low-cardinality aggregates, not memory bodies or per-record adoption receipts; never send prompts, source, model output, secrets, or raw/full project paths to telemetry.

If Hub is unavailable, make one bounded health/retry attempt, then use one native fallback. Native validation still requires `terminal=true` and `retryable=false`; never poll or repeat an identical operation.

### Memory adoption checkpoints

Agents must consider supplied relevant memory as advisory context and verify volatile facts against current source before relying on them. Before completion, checkpoint `state_data.memory_audit` through `local_ai_coord(action="task_checkpoint", task_id=..., checkpoint=...)`. `used_ids` must be a list of IDs from server-managed `memory_context.items[].id`; cite only findings actually used. `not_used_reason` must be nonempty when `used_ids` is empty, including when supplied memory was irrelevant or unavailable. Every task_checkpoint and completion validates this nested audit when server memory items or warnings exist. Putting not_used_reason directly in state_data does not satisfy the contract.

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

For telemetry diagnostics, `local_ai_status(detail="telemetry")` preserves bounded writer counts and an explicit current-process interval in `summary.writer`, independently of the history window. Distinguish attempted, accepted, overflow-rejected, lost-after-acceptance and pending records; denominator rates remain null without observations. Missing activity, accounting imbalance and stale aggregates do not establish zero failures or complete data.

MCP task checkpoints preflight the complete adoption response before checkpoint persistence, including the watchdog failure path. An insufficient response budget returns `mutation_applied=false` and `operation_not_started=true`; it does not mean the HTTP request was unsent. Task-memory `original_tokens` measures the canonical complete adoption payload without optional delta/reuse/debug wrappers; `returned_tokens` measures the actual emitted MCP envelope. This checkpoint guard does not establish equivalent preflight for every other mutation.

For indexed symbol lookup, use `local_ai_repo(action="code_index", root=ABS_ROOT, query="symbol")`. For managed Serena navigation when available, use `action="semantic", relation="find_symbol"` with the same tool.

Follow the published typed action/detail enums. Optional `speculative_lint` and Agent OS actions are exposed only when their modules are enabled.

Speculative lint remains opt-in (`speculative_lint.enabled=false`). With `daemon_mode=true`, default Python lint uses the installed Ruff native server over persistent read-only LSP pipes, isolated by tenant and absolute project root. `max_daemon_sessions=4` caps sessions; `daemon_idle_ttl_seconds=300` permits idle retirement on subsequent admission. No model or linter installation is implicit. Custom commands retain explicit `transport="one_shot"`. For supported JavaScript, TypeScript and JSON paths, an installed Biome reports `unsupported_shared_daemon_ownership` with `daemon_mode=true`; explicitly setting `daemon_mode=false` selects read-only `biome ci` with `transport="one_shot"`. Biome's shared version-named Windows daemon pipe does not establish ownership by Hub, so persistent Biome remains unsupported. Cancellation or transport failure terminates the owned process generation; unconfirmed cleanup blocks replacement and reports `outcome_unknown`. Source integration does not establish installed capability or performance.

Managed llama.cpp preset generation carries each configured route's positive `context_length` into `ctx-size`; zero keeps the provider default and invalid values fail before replacing the preset. Shared aliases must declare consistent server contexts. Existing running servers do not acquire this setting merely because source changed. Native streaming requires a completion marker and treats malformed or interrupted streams as failures. Source recovery uses preprovisioned half-context presets with the same weights, held-process ownership and confirmed original-model unload; request `num_ctx` alone does not resize native allocation. Private served aliases remain bound to configured model ownership for inventory/unload. Live native OOM behavior still requires acceptance evidence.

Ollama foreground and interruptible calls share complete-marker/partial-output handling. Interruptible calls retain one generic attempt; pre-output OOM can reserve one reduced-context retry within the original deadline even with `request_attempts=1`. Input/tool/schema/template content is retained; unknown vision cost or an oversized retained input refuses recovery. Partial output, cancellation, deadline expiry or unknown cleanup stops model/stale substitution. Recovered execution provenance is returned and excluded from caches under the original context profile. Completion-contract version 2 separates exact/semantic/stale keys from legacy records, which remain retained. No configuration edit or daemon restart is implied by these source changes.

Trace search is available through `local_ai_status(action="traces", min_duration_ms=1000, trace_action="search")` and `HubClient.status("traces", min_duration_ms=1000, trace_action="search")`, using the existing operator-authorized trace endpoint. Duration must be an integer from 0 through 86400000; action accepts at most 64 characters. Invalid filters fail explicitly rather than widening the search. Results remain bounded metadata; this does not grant new trace-reading authority.

Migration drift compares table/column names, including generated columns, using bounded in-memory SQLite migration replay and read-only live schema inspection. ASCII identifier case follows SQLite matching; results do not establish type/default/constraint equality. Limit or replay failures must remain unknown rather than `in_sync=true`.

Circuit-breaker resource tracking is bounded (default 256 keys); reaching capacity refuses untracked resources without evicting existing protective failures or probes. Transaction snapshot traversal rejects directory cycles and excessive depth (default 64). Token trimming consumes the input once and retains the requested head/tail line count; zero prints no content lines. These source changes still require integrated validation before release acceptance.

Pubsub retains bounded optional live cache (500 topics, 8 MiB serialized charge), 256 subscriptions and 4096 aggregate queue slots. New JSON message envelopes are limited to 64 KiB, 4096 nodes and 32 levels. Ephemeral capacity failure preserves admitted history; durable publication/replay continues with `cache_retained=false` if optional cache is full. Compaction expires cache without disconnecting active subscribers. These limits do not measure Python heap/RSS or prove live concurrency performance; retained durable data is preserved.

## Local telemetry

Basic aggregate telemetry remains enabled locally. Detailed request traces are disabled by default and can be toggled live in the dashboard. When enabled, they retain complete endpoint input/output locally, including sensitive values, within configured size and retention limits. Local telemetry and trace details stay on this device; only normal agent responses requested by cloud agents leave it.

Install updates stage and verify payloads before swapping files. Existing-runtime stop uses the installed config and must be confirmed; failed or unknown stop blocks replacement and startup. File rollback can leave the runtime stopped and must be reported separately. Shared skills are replaced or removed only when their Hub ownership hash matches; preserve unmanaged or user-modified trees and report conflicts.
