# Configuration

`defaults.toml` is the authoritative reference. `config.toml` should contain only overrides. User values are merged after the auto-selected hardware profile, so explicit settings always win. Malformed explicit TOML and invalid transport/resource limits fail fast.

Runtime accepts only config files stamped with `local_ai_hub.config_schema_version = 1`; defaults do not make an unversioned user file current. Setup/update migrates unversioned config and runtime overrides before launch, verifies adjacent recovery copies, and stamps the current version. Run the updater before starting an unversioned config. New dashboard runtime overrides are written with the current schema marker.

## HTTP authentication

The HTTP server accepts loopback peers only and binds to `127.0.0.1`. Hub API credentials do not exist; loopback HTTP/MCP calls need no Hub token. The retired `security.api_token`, `security.supervisor_token`, `security.action_tokens`, and `security.api_token_permissions` keys reject by presence, including empty values. Retired user, tenant, and principal fields also reject by presence. `allowed_roots`, command authorization, capabilities, approvals, leases, rate limits, and audit records continue to constrain operations.

## Telemetry and trace detail

`[telemetry].mode` is the single detail control: `off` disables persisted telemetry, `minimal` keeps aggregate request counts and fatal errors, and `full` enables detailed traces and endpoint latency data. The dashboard writes the canonical `telemetry.mode` setting (`full` or `minimal`). Trace retention and size limits, including `max_list_limit`, also live under `[telemetry]`.

The retired `[debug_traces]` and `[observability.debug_traces]` tables are converted during setup/update into `[telemetry]`; each changed config is first copied to a verified adjacent backup. Runtime config loading rejects these retired tables. Run the installer/update before starting a config that still contains them.

## Hardware

`[hardware].profile = "auto"` detects OS, architecture, RAM and NVIDIA/AMD/Intel/Apple graphics. Profiles are `cpu`, `integrated`, `low`, `balanced`, `high`, and `max`. They tune model choices, context, concurrency and batching; they are presets rather than hardware locks.

### Shared-memory iGPU and Intel NPU

The `integrated` profile is intentionally conservative. It is designed for iGPUs that borrow system RAM and therefore must not be scheduled from a nominal/dedicated VRAM value. The default integrated profile keeps one foreground LLM/model resident, disables the independent background Ollama runtime, routes preprocessing to the trained Qwen 3B model, quick tasks to 1.5B, complex work to 3B, and the hardest reasoning to 7B; it also reduces context and preprocessing concurrency. For Intel iGPU systems, see [the llama.cpp SYCL setup](LLAMA_CPP_SYCL.md).

Embedding and reranker defaults use `*_backend = "auto"` and `*_device = "auto"`. Both probe installed provider runtimes and try supported routes in this order: NPU, dedicated GPU, integrated GPU, CPU. Intel NPU/GPU uses OpenVINO; NVIDIA uses a working PyTorch CUDA runtime; supported AMD ROCm builds use PyTorch's CUDA-compatible device API; and ONNX Runtime DirectML is a Windows fallback for detected DX12 GPUs. AMD Ryzen AI NPU is considered only when its Vitis AI execution provider is installed. Provider packages and drivers are optional and are never installed or model weights downloaded by the router. For ONNX routes, the local model must already be cached; provider/export incompatibility skips to the next route. Active backend/device and route-specific cache identities keep results tied to the selected provider. Set a concrete backend/device to override automatic routing; CPU fallback remains available to `auto`.

File-card enrichment's separate background GPU worker is disabled by default. Set `[background_gpu].enabled = true` to opt in after foreground idle grace and scheduler admission; its existing limits, preemption and game-mode gates remain active. The configured preprocessing model and foreground hardware-profile routing remain authoritative.

For Intel integrated graphics, `[openvino]` controls optional retrieval acceleration. The SentenceTransformers wrapper remains on CPU while the underlying Optimum/OpenVINO model is compiled for the selected accelerator, so this path does not require a torch-native NPU device. Explicit device requests fail when that device is unavailable; `cpu_fallback = true` opts into CPU fallback for an explicit OpenVINO route that cannot load.

`[ollama].enabled = false` is the default and prevents setup/service installation, startup, pulls, and health probes. `[ollama].allow_integrated_gpu` and `enable_vulkan` matter only after Ollama is explicitly enabled. With `headless.manage_ollama = true`, the supervisor owns an explicitly enabled Ollama process; otherwise the Hub does not run it. `llama_cpp.mode = "auto"` only probes an existing hardware-appropriate endpoint and never installs a runtime.

## Laya session lifecycle

`[laya].enabled` defaults to `true`; set it to `false` to disable active Laya inference and runtime-output capture while keeping `runtime_status` and candidate lifecycle actions available. Laya always runs as an active advisory; `laya.mode` is removed and rejected if present. `[laya].idle_unload_seconds` is fixed at `600` seconds. When enabled, Laya loads on the first eligible active decision, remains loaded during active requests, and unloads after 600 seconds without a completed request.

Idle time starts when an inference finishes. The shared session manager refuses to unload during active inference, serializes reload against closing, and closes the provider session only when its adapter confirms success. When `LayaRuntimeAdapter` is constructed with an unconfigured shared lifecycle, it binds its provider close callback through `LayaSessionLifecycle.bind_close_session` before loading the first session. Its default optional adapter uses Laya's public `Router` API with one local multilingual checkpoint and calls `Router.unload()` on expiry; it passes the pinned file hashes and disables the optional secondary model lane. Injected providers must expose an explicit `close()` result or use an already-configured lifecycle callback; moving parameters to CPU alone is not treated as successful close. If cleanup after a load/device failure is unconfirmed, the adapter stops instead of trying another device while the first session may still be resident. An existing configured provider callback remains authoritative; rebinding a different callback or changing it after load is rejected. Shutdown also waits for in-flight calls and closes the session. No model is loaded during startup. `runtime_verification` remains `NOT_VERIFIED`: source code and fake-provider tests do not prove memory reclamation on NPU/GPU/CPU, and unsupported provider cache APIs must not be reported as supported. The existing scheduler dispatcher polls this lifecycle; no separate timer thread or model service is created. Model weights in disk cache are not deleted.

The optional `laya-runtime` extra pins `laya==0.4.31` and `vegaml==0.16.1` in the isolated `tool-envs/laya` environment. The Hub runtime keeps that ML stack in a managed worker process, separate from OpenVINO/NPU packages in the main environment. Typed active advisory decisions lazily load only a valid pinned checkpoint. The server derives task/session identity and validates evidence. Actual runtime outputs can be captured for candidate review when Laya and training capture are enabled; ordinary context retrieval no longer queues background Laya evaluation. Training and benchmarks remain separate opt-in work.

The normal Hub status response includes `laya_runtime` lifecycle metadata, and the existing diagnostics ZIP includes the same metadata at `laya/report.json.runtime`. These fields report session availability, whether provider close is configured, in-flight calls, timeout and close errors. `runtime_verification` remains `NOT_VERIFIED` until a connected provider independently verifies placement and release; these status fields do not claim device support or reclaimed memory.

### Local review

Candidate review runs through the loopback-only, root-scoped Hub API/MCP surface. With no reviewer keys configured, the operator can confirm a candidate using the versioned rubric and one allowed target; no SSH keys, per-example consent receipt, or separate approval record is required. `model_review` accepts only a candidate ID and invokes the Hub application's configured local reasoning route; callers cannot submit decisions, confidence, or model identity. The route checks the configured model and runtime identity before and after review, and accepts output only from the pinned model through the local Ollama provider. Missing models, unavailable runtime, invalid output, or identity changes fail closed without storing a review. Configuration alone does not prove that the model is installed or available. Model reviews keep separate provenance and can never be exported as human-confirmed labels. Remote reviewer quorum and cloud review are not used.

## Code intelligence

`[code_intelligence]` controls Serena enablement, command, query/index deadlines, failure threshold, maximum persistent sessions and session idle TTL. `direct_agent_mcp=false` is recommended because the hub exposes Serena through the compact MCP surface.

## Server/security

The Hub is local-only: its HTTP server binds to `127.0.0.1`, and remote binding or remote Hub access is unsupported. The same-machine Browser Bridge remains available. `request_body_timeout_seconds` bounds slow uploads, `max_concurrent_requests` caps live HTTP handlers, and `overload_wait_seconds` controls the tiny admission wait before a retryable 503.

## Diagnostics support archive

`[diagnostics_export].max_archive_bytes` defaults to 8 GiB; `max_source_bytes` defaults to 64 GiB. The Service health export streams a ZIP64 archive through temporary disk space, so allow enough free space for the SQLite snapshots and compressed ZIP. The archive includes Hub source, redacted effective configuration, all Hub-owned state databases and operational logs across projects. Model weights and other project source stay out. Traces, logs, paths, tasks, and memories may contain private content; the archive is password-protected.

The existing `POST /api/diagnostics/export` request may be empty for a regular export. Candidate text stays out of that export: Laya candidate tables are removed from disposable database snapshots, and candidate-capture debug traces with linked content are removed. The archive includes `laya/report.json` with aggregate candidate counts and metadata-only Laya telemetry. To explicitly include train rows, send exactly `root` and `laya_candidate_export: { snapshot_id: "..." }`. Candidate capture is bound to an authorized repository, task/session, and validated evidence/source provenance. Repository/task/session scope, snapshot, hashes, and verified labels are rechecked; only the train split is added as `laya/candidates.train.jsonl`. The normal archive manifest reports omitted or included candidate rows. The source database and disk model cache are not modified.

Laya candidate capture stores actual outputs from active typed advisory/runtime calls when enabled. Laya capture runs only on actual active decisions; unrelated context, routing, budget, delegation, completion, and watchdog events do not trigger inference. Candidate data stays repository/task/session scoped, and export continues to require verified labels and a valid snapshot.

## Foreground repository state

`[workspace_cache]` keeps repository fingerprints off critical request paths. `fingerprint_ttl_seconds` controls the short in-memory reuse window. `git_probe_timeout_seconds` and `git_status_timeout_seconds` are hard foreground budgets; after a timeout, `slow_git_cooldown_seconds` temporarily reuses the last-good or bounded filesystem state rather than stalling the request. `max_changed_paths`, `max_untracked_walk_files`, and `degraded_fingerprint_max_files` bound work on unusually large repositories. Filesystem watchers remain the preferred warm-path invalidation source.

## Adaptive context guard

For non-trivial repository work, `local_ai_repo(action="context")` is the adaptive-only guarded context flow. Supply `task_id` or `phase`, or set `guarded = true`, to receive an adaptive context pack. The pack is bounded and revision-aware; omitted `mode` uses `adaptive`, while every other explicit mode rejects.

`[context.preloads]` configures optional, bounded preload inputs. Preloads are indexed and fingerprinted; their full contents are not copied into every response. Missing files or empty patterns are soft fallbacks, not configuration failures.

```toml
[context.preloads]
files = ["AGENTS.md", "README.md"]
patterns = ["docs/**/*.md"]
memory_kinds = ["finding", "reusable_candidate", "contract_mapping", "validation"]
max_files = 24
max_bytes = 120000
```

Use `preload_profile` to select a named project profile. Defaults have no mandatory project file, so repositories without optional preload paths still receive deterministic context.

The guard uses these phase values: `plan` (contract, scope, unknowns), `edit` (reuse candidates and exact symbols), `review` (drift and changed paths), `test` (receipts and affected tests), and `handoff` (decisions, checkpoints, and next actions). Each deterministic fact carries an opaque `evidence_id`; retain and cite those IDs when composing or validating work. `repo_revision`, `stale`, and `context_id` identify freshness and pack identity.

Guard warnings are machine-readable objects with `severity`, `code`, `message`, `evidence_ids`, `affected_paths`, `recommended_action`, and `requires_approval`. Context-compiler fallback warnings are smaller objects with `code`, `message`, and relevant path/error details. Canonical soft-stop severities are `info`, `warning`, `boundary`, and `high-risk`. `info` does not interrupt; `warning` needs a concise override reason; `boundary` and `high-risk` move an active task to recoverable waiting/approval until an authorized approval is present. Warnings never delete edits or rewrite history.

Agent OS memory is authoritative only while fresh and provenance-linked. Promotion from task/repository scope to project, user, or global scope requires explicit approval. A relevant repository revision change marks affected records `stale`; stale/conflicting records remain visible in diagnostics but are excluded from authoritative context until superseded or revalidated.

Deterministic/indexed evidence is authoritative. Local-model passes may rank evidence, find gaps, or compose bounded text only; they may not override, replace, or invent repository facts. If optional code intelligence or a local model is unavailable, the guard returns the deterministic/indexed pack plus a concise warning and preserves its useful evidence.

## Search/Git acceleration

`[search].git_files_timeout_seconds` and `git_grep_timeout_seconds` are hard Git subprocess budgets. `git_files_cache_ttl_seconds` coalesces bursty inventories and `git_files_slow_cooldown_seconds` prevents repeated Git probes after a timeout; the hub falls back to bounded Python/indexed paths instead of wedging foreground work.

## Scheduler and command deadlines

`[scheduler].max_caller_wait_timeout_seconds` is a hard ceiling even when a caller omits or overspecifies its wait timeout. Model preparation failures use `model_switch_failure_cooldown_seconds` to fail repeated requests quickly. `[commands].coalesced_wait_seconds` bounds duplicate-command waiters; termination and post-kill drain windows are separately bounded. MCP and local clients additionally clamp their transport deadlines.

## Preprocessing and SQLite

`[preprocessing].sqlite_busy_timeout_seconds` is intentionally short for foreground control writes. `sqlite_write_retries` applies bounded retry with short backoff rather than allowing a single SQLite operation to block for many seconds. Completed projects sleep until their configured recheck time and are woken immediately by relevant watcher events. `watcher_refresh_seconds` controls only watch-registration reconciliation; per-project single-owner execution prevents CPU/GPU background loops from duplicating the same durable step.

## Client cold start

`[client].health_timeout_seconds`, `startup_wait_seconds` (default 30 s), `startup_poll_seconds`, and `start_lock_stale_seconds` bound MCP/CLI auto-start. Startup probes use `/ready`, not `/health`, so clients do not send requests while the app is still initializing. Startup locks whose owning PID is gone are discarded immediately instead of consuming the full wait budget.

## Optional tiered local runtime

`[smart_ollama]` is disabled by default and remains unavailable while `[ollama].enabled = false`. The Hub does not start a user-managed server or sidecar implicitly. Use an existing llama.cpp endpoint only when `llama_cpp.mode = "auto"` detects the required hardware route and the endpoint is healthy.

## Agent integration

`[agents]` enables per-host setup for Codex, Claude, Gemini/Antigravity, Cursor, Windsurf Cascade, Devin Local, VS Code/Copilot, and OpenCode. Devin uses the setup-managed global MCP route by default. Set `agents.devin_plugin_route=true` to select the bundled Devin Agent Plugin MCP/skills route instead; setup skips adding Devin's global MCP and reports any existing duplicate route for review. Install the plugin manually with Devin's CLI and review host trust. `extra_mcp_json_paths` and `extra_vscode_mcp_paths` can target additional MCP hosts without hardcoding vendor directories. Setup preserves unrelated configuration and writes portable manifests under `generated/`. `[agent_output.*]` controls compact host-specific projections after canonical local work, so expensive caches remain shared rather than fragmented by client.

## Headless supervisor

`[headless].health_probe_timeout_seconds` bounds an individual health request. `startup_grace_seconds` gives a newly spawned hub a separate cold-start window, while `unhealthy_grace_seconds` controls recovery of an already-running process. Keep only one supervisor/hub instance per state directory.

## Bundles

`[bundles]` limits compressed bundle bytes, decoded JSON bytes and rows per table. Bundles contain repository-derived local state and should be protected accordingly.

## Agent Operating System state

`[agent_state]` controls the local agent operating system state layer. It is enabled by default (`enabled = true`). When enabled, state is stored in `agent_state.sqlite3` under `server.state_dir`.
- `event_retention_days = 30`: Retention period for agent-state events and snapshots.
- `max_payload_bytes = 65536`: Event payload size ceiling.
- `snapshot_interval_events = 50`: Periodic state snapshot interval.
- `cleanup_batch_size = 100`: Maximum cleanup batch size.
- Governed promotion: Global memory and learned policy promotion strictly require explicit user approval.

## Dashboard-managed overrides

The dashboard writes only `config.runtime.toml` next to the active primary configuration. It never rewrites `config.toml`; this preserves comments, secrets and hand-maintained settings. Runtime overrides are merged last and require a hub restart to take effect. Resetting dashboard overrides deletes only the sidecar.

## Modular Features and Dynamic Generation

Every primary tool and capability can be toggled via `[features]` in `config.toml`:

```toml
[features]
status = true             # local_ai_status tool
repo = true               # local_ai_repo tool
tasks = true              # local_ai_task local model tool
rag = true                # local_ai_rag semantic retrieval tool
commands = true           # Internal command broker (used by work orchestrator)
coord = true              # local_ai_coord coordination/leases tool
artifacts = true          # local_ai_artifact evidence slice tool
code_intelligence = true  # Serena backend
preprocessing = true      # Background idle project warmup
subagents = true          # Named advisory subagent profiles
agent_os = true           # Durable execution: task contracts, receipts, memory
```

When a feature is disabled:
- The MCP server unregisters the tool so connected agents do not receive its schema.
- Action lists and documentation for composite tools (`local_ai_repo`, `local_ai_task`, `local_ai_coord`) automatically omit unsupported actions.
- Dynamic agent skills (`SKILL.md`) and instruction policies (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) omit all disabled tools, recipes, and models.

### Regenerating Artifacts

Generated skills, policies, MCP manifests, and schemas are installation artifacts. They are written to the selected installation/target directory and are intentionally ignored by Git; the generator source and static companion skills are the repository source of truth.

Whenever you change feature toggles or models in `config.toml`:

```bash
# Regenerate skills, instructions, MCP manifests, and schemas:
python tools/hubctl.py generate

# Or via setup:
python tools/setup.py --generate-only
```

### Verifying generation on shared-memory Windows GPUs

Check a short, known-answer prompt after installation. An HTTP success response
does not establish that the generated text is correct. If an integrated-GPU
configuration produces garbled or repetitive text, compare it with this
conservative CPU configuration in the installed `config.toml`:

```toml
[ollama]
enable_vulkan = false
allow_integrated_gpu = false
flash_attention = false
kv_cache_type = "f16"
```

Remove or disable inherited `OLLAMA_VULKAN` / `OLLAMA_IGPU_ENABLE` overrides,
then restart the managed service (`python tools/service.py restart`). Verify
the actual answer again. This is a compatibility fallback, not a claim that
every AMD or Intel adapter requires CPU inference. Keep the model downloads;
switching execution backends does not require downloading them again.

---

## Token Economy & Caveman Ultra Configuration

Local AI Hub enables global token-saving optimizations by default across all devices and profiles:

```toml
[token_saving]
concise_local_output = true    # Default: true — injects Caveman style (ultra) into all local LLM generations
compress_local_input = true    # Default: true — compacts excessive whitespace in safe plain-text prompts
```

### Instruction & Skill Compression CLI (`caveman-compress`)

To automatically compress agent instructions (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `rules.md`, `*.mdc`, `SKILL.md`) using local models in Caveman Ultra mode:

```bash
# Preview token savings on project instructions (creates byte-verified backups in staging, no file changes):
python tools/hubctl.py caveman-compress --root /path/to/project

# Apply compressed instructions in-place (atomic replace with SHA-256 manifest backup):
python tools/hubctl.py caveman-compress --root /path/to/project --apply

# Discover and compress all agent skills and instructions across all user environments:
python tools/hubctl.py caveman-compress --all-agents --apply
```

All compressions strictly enforce:
1. Exact preservation of code blocks, inline backticks, URLs, file paths, versions, and structure.
2. Independent semantic review for equivalence (`{"equivalent": true, "missing": [], "weakened": []}`).
3. Hash-verified backup retention with reversible manifests.

## Shared project retrieval hints

A project can version manually curated, purpose-specific retrieval hints in its existing `.local-ai.toml`:

```toml
[shared_path_hints]
search = ["src/Service", "docs/architecture.md"]
```

Keys are exact purpose names used by the existing project-context consumer.
Each value is a bounded list of repository-relative literal paths. Purpose-specific hints rank existing candidates ahead of broad entry points, request hints, and locally learned hints; they never add candidates, override path policy, or authenticate a fact. Missing paths are ignored by the existing validation pipeline. Use Git review for curated entries; the current implementation does not automatically publish learned hints. The ordinary configuration resolver and overlay precedence remain authoritative.

See [the V4 specification](superpowers/specs/2026-11-25-git-first-unified-project-intelligence-v4.md) for the proposed full project-state migration. This setting and the portable source locator are initial foundations, not the complete V4 integration.

## Repository knowledge (initial V4 contract)

The initial Git-native reader uses `.local-ai-hub/project.json` with
`schema_version: 1`, a canonical UUID `project_id`, and a `mode` of
`shared`, `review_only` or `read_only`. Mode is a repository declaration,
not an authorization grant. Knowledge files are one JSON object per record
under `.local-ai-hub/knowledge/<kind-directory>/<stable-id>.json`. The
initial envelope has `schema_version`, `project_id`, `kind`, `id`,
`payload` (title, statement, layer, optional boolean claim key/value),
`provenance`, `evidence` (portable source locators) and `relations`.
The reader is intentionally limited to the default knowledge directory and
128 entries per inventory; malformed, unavailable and truncated inventory
is reported as incomplete. Source freshness is calculated without writing files.

Read-only local inspection needs no running service:

```sh
python tools/hubctl.py knowledge catalog --root /path/to/project --json
python tools/hubctl.py knowledge query --root /path/to/project --query "paid order" --json
python tools/hubctl.py knowledge validate --root /path/to/project --json
```

The validation command fails for incomplete inventory, stale/unknown evidence,
or explicit boolean claim conflicts. A conflict is only a candidate; source
byte matches do not establish business truth or execution proof. The internal
bootstrap/edit API reuses the existing plan journal, revision and checkout
fences, and needs a caller-owned authorization callback. This is not yet an
automatic publication, Agent OS migration or complete knowledge UI.

Explicit local operator writes use the same journal, not a second database.
Initialize the existing plan workspace / ensure `.local-ai-hub/local/` is
ignored and untracked before attempting writes in Git projects:

```sh
python tools/hubctl.py knowledge init --root /path/to/project --apply
python tools/hubctl.py knowledge save --root /path/to/project --record-file rule.json --expected-revision "" --apply
python tools/hubctl.py knowledge review --root /path/to/project --finding-id ID --subject-digest DIGEST --decision expected --reason "Approved expected deviation" --expected-revision "" --apply
```

Use the exact current record revision instead of the empty create revision
for edits. Review declarations are stored separately from observed/intended
claims and bind to the current conflict subject digest. A later edit requires
revalidation; the original decision remains available. The initial strict
validator reports reviewed conflicts too: Git content alone does not establish
authorization for a completion waiver. Normal adaptive context retrieval
includes a bounded, explicitly untrusted projection of relevant knowledge
declarations when the project manifest is present; this is not yet full
process discovery or a substitute for current source evidence.

The ordinary repository delegate and semantic solve paths now use the same
bounded knowledge-context reservation and attachment as adaptive context.
Pure deterministic exact-fact answers still return without model inference.
The projection does not create evidence IDs or change the existing completion
contract. If the projection is unavailable or exceeds the budget, technical
retrieval remains authoritative. Semantic model cache identity includes the
attached knowledge digest.

### Portable Agent OS handoffs (initial migration boundary)

The local operator can preview and explicitly publish a scoped task handoff
into `.local-ai-hub/agent-os/handoffs/`. The record contains the goal,
acceptance criteria, constraints, non-goals and selected checkpoint guidance.
It is **not** a canonical replacement for the task store. Raw events, leases,
execution state, local evidence IDs, receipts and arbitrary checkpoint state
are never copied. Review the preview for sensitive text before publication.

```sh
python tools/hubctl.py knowledge handoff-export --root /path/to/project --task-id task_123
python tools/hubctl.py knowledge handoff-export --root /path/to/project --task-id task_123 --expected-revision "" --apply
python tools/hubctl.py knowledge handoff-resume --root /path/to/clone --handoff-id HANDOFF_ID
python tools/hubctl.py knowledge handoff-resume --root /path/to/clone --handoff-id HANDOFF_ID --expected-revision REVIEWED_DIGEST --apply
```

Resume creates a new planned task through the existing scoped Agent OS client;
it does not execute, complete or grant verification to the task. Its contract
requires current revalidation. Handoffs are excluded from generic knowledge
retrieval and require explicit selection. Custom SLO profiles and non-task
scopes are rejected pending a lossless migration contract. Git still owns
reviewed portable handoff history, not live execution coordination.

Structured process declarations may optionally include `payload.flow` with
an entry step, a list of uniquely identified action/decision/terminal/external
steps and transitions with explicit conditions. Validation checks the graph
contract and reports unreachable steps, terminal successors and nonterminal
dead ends as advisory candidates. It does not infer production behavior.
The catalog projects transitive freshness for `depends_on`, `derived_from`
and `verified_by` relations; pin each target's record revision using
`target_revision`. Missing/unpinned or unverified dependencies are unknown,
changed pins and stale source dependencies propagate stale. Other relations
support one-hop query navigation. The bounded online query intentionally
does not claim full dependency source verification.

### Quality report, business impact and remediation

`hubctl knowledge audit --root ROOT` combines revision-bound claim conflicts,
stale/unverified knowledge, dependency issues and process topology candidates.
`hubctl knowledge impact --root ROOT --changed-path src/order.py` separates
direct source references, reverse dependency chains and related candidates;
unmapped paths remain explicit, not a promise of no business impact.
The existing knowledge review command accepts these finding IDs and subject
digests. Stale subjects never create current waivers. To prepare a corrective
Agent OS task, preview with `knowledge remediate --root ROOT --finding-id ID
--subject-digest DIGEST`. Add `--apply --task-id NEW_ID` to create a task
through the existing scoped client. This does not execute or complete the
task; current evidence and fresh verification remain mandatory.

Normal adaptive context and solve use the caller's scoped changed paths to
prioritize direct source links and reverse business dependencies, even when the
task wording shares no lexical terms with a rule. Czech business terminology
is expanded by the existing Laya cross-lingual lexicon (deterministic fallback,
not evidence of neural-model quality). The existing active, evidence-gated
Laya next-step recommendation can see a bounded revalidation signal; its
baseline requests more evidence for stale or unknown knowledge. No background
Laya evaluation, training or approval authority is added.

### Opt-in preprocessing candidate publication

Machine configuration `[security].knowledge_auto_publish_roots` is an exact
absolute checkout allowlist, empty by default. It does not replace repository
read authorization, and a Git project manifest alone cannot authorize it.
The project must be initialized in shared mode and the local journal ignored.
Existing file-card creation and cache-hit linking can publish at most one
source-card business interpretation per file using exact unique source quotes
in a bounded source slice. The record stores only candidate summaries and
portable locators, not raw quotes, prompts, or receipts. It remains unreviewed
interpretation, never a verified rule. Untouched generated records may refresh
through CAS; edits or review references are preserved. Publication failure
does not block technical indexing, and status counts use preprocessing stats.
This is initial bounded card-based discovery, not full semantic process
inference. Previously indexed files need a normal card refresh to participate.

`hubctl knowledge sync-status --root ROOT` and the Projects dashboard's
Git sync status report local tracked, modified, untracked, ignored and
conflicted shared paths, plus accidental tracking of private local state
(without disclosing private filenames). Ahead/behind compares only the
existing local upstream tracking ref; no fetch or remote verification occurs.
This diagnostic never changes the Git index, commits, stashes or merges.
It reports the default shared layout, not arbitrary custom workspace paths.

### Explicit static business assertions

An intended requirement/business rule may include `payload.source_assertion`,
e.g. `{"path":"settings.py","format":"python_literal","key":["ALLOW_RESCHEDULE"]}`
alongside its boolean claim. Full catalog/audit reads current source through
the existing bounded source reader and compares an unambiguous Python
module-level literal, JSON key path or TOML key path. Dynamic, ambiguous,
private or oversized targets are rejected or unknown. Findings bind current
source digest and record revision; a later source edit reopens review.
This checks explicitly linked documentation intent against static source
declarations, not effective runtime behavior. No source is imported/executed,
and PHP/dynamic semantics still require evidence-backed analysis.
