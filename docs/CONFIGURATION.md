# Configuration

`defaults.toml` is the authoritative reference. `config.toml` should contain only overrides. User values are merged after the auto-selected hardware profile, so explicit settings always win. Malformed explicit TOML and invalid transport/resource limits fail fast.

## HTTP authentication

The HTTP server accepts loopback peers only and binds to `127.0.0.1`. Hub API credentials do not exist; loopback HTTP/MCP calls need no Hub token. The retired `security.api_token`, `security.supervisor_token`, `security.action_tokens`, and `security.api_token_permissions` keys reject by presence, including empty values. Retired user, tenant, and principal fields also reject by presence. `allowed_roots`, command authorization, capabilities, approvals, leases, rate limits, and audit records continue to constrain operations.

## Hardware

`[hardware].profile = "auto"` detects OS, architecture, RAM and NVIDIA/AMD/Intel/Apple graphics. Profiles are `cpu`, `integrated`, `low`, `balanced`, `high`, and `max`. They tune model choices, context, concurrency and batching; they are presets rather than hardware locks.

### Shared-memory iGPU and Intel NPU

The `integrated` profile is intentionally conservative. It is designed for iGPUs that borrow system RAM and therefore must not be scheduled from a nominal/dedicated VRAM value. The default integrated profile keeps one foreground LLM/model resident, disables the independent background Ollama runtime, routes preprocessing to 0.5B, quick tasks to 1.5B, complex work to 3B, and the hardest reasoning to 7B; it also reduces context and preprocessing concurrency. For Intel iGPU systems, see [the llama.cpp SYCL setup](LLAMA_CPP_SYCL.md).

Embedding and reranker defaults use `*_backend = "auto"` and `*_device = "auto"`. Both probe installed provider runtimes and try supported routes in this order: NPU, dedicated GPU, integrated GPU, CPU. Intel NPU/GPU uses OpenVINO; NVIDIA uses a working PyTorch CUDA runtime; supported AMD ROCm builds use PyTorch's CUDA-compatible device API; and ONNX Runtime DirectML is a Windows fallback for detected DX12 GPUs. AMD Ryzen AI NPU is considered only when its Vitis AI execution provider is installed. Provider packages and drivers are optional and are never installed or model weights downloaded by the router. For ONNX routes, the local model must already be cached; provider/export incompatibility skips to the next route. Active backend/device and route-specific cache identities keep results tied to the selected provider. Set a concrete backend/device to override automatic routing; CPU fallback remains available to `auto`.

File-card enrichment's separate background GPU worker is disabled by default. Set `[background_gpu].enabled = true` to opt in after foreground idle grace and scheduler admission; its existing limits, preemption and game-mode gates remain active. The configured preprocessing model and foreground hardware-profile routing remain authoritative.

For Intel integrated graphics, `[openvino]` controls optional retrieval acceleration. The SentenceTransformers wrapper remains on CPU while the underlying Optimum/OpenVINO model is compiled for the selected accelerator, so this path does not require a torch-native NPU device. `cpu_fallback = true` keeps RAG functional if the NPU/GPU driver or a particular model shape is unsupported.

`[ollama].enabled = false` is the default and prevents setup/service installation, startup, pulls, and health probes. `[ollama].allow_integrated_gpu` and `enable_vulkan` matter only after Ollama is explicitly enabled. With `headless.manage_ollama = true`, the supervisor owns an explicitly enabled Ollama process; otherwise the Hub does not run it. `llama_cpp.mode = "auto"` only probes an existing hardware-appropriate endpoint and never installs a runtime.

## Laya session lifecycle

`[laya].idle_unload_seconds` defaults to `600`. It accepts finite numeric seconds in the inclusive range `0` through `86400`; fractional seconds are allowed. `0` disables idle-triggered unloading. Booleans, strings, non-finite values (`nan`/`inf`), and out-of-range numbers fail configuration validation with `ConfigError`.

Idle time starts when an inference finishes. The shared session manager refuses to unload during active inference, serializes reload against closing, and closes the provider session only when its adapter confirms success. When `LayaRuntimeAdapter` is constructed with an unconfigured shared lifecycle, it binds its provider close callback through `LayaSessionLifecycle.bind_close_session` before loading the first session. Its default optional adapter uses Laya's public `Router` API with one local multilingual checkpoint and calls `Router.unload()` on expiry; it passes the pinned file hashes and disables the optional secondary model lane. Injected providers must expose an explicit `close()` result or use an already-configured lifecycle callback; moving parameters to CPU alone is not treated as successful close. If cleanup after a load/device failure is unconfirmed, the adapter stops instead of trying another device while the first session may still be resident. An existing configured provider callback remains authoritative; rebinding a different callback or changing it after load is rejected. Shutdown also waits for in-flight calls and closes the session. No model is loaded during startup. `runtime_verification` remains `NOT_VERIFIED`: source code and fake-provider tests do not prove memory reclamation on NPU/GPU/CPU, and unsupported provider cache APIs must not be reported as supported. The existing scheduler dispatcher polls this lifecycle; no separate timer thread or model service is created. Model weights in disk cache are not deleted.

The optional `laya-runtime` extra pins `laya==0.4.31` and `vegaml==0.16.1`. `[laya.runtime]` defaults to `enabled = false`; this installation has it enabled. With an absolute `checkpoint_path`, matching directory-name `revision`, and `expected_sha256` entries, eligible normal context requests run Laya in shadow. Eligibility requires an unresolved evidence gap, at least two authorized sources, and verified evidence IDs. The server derives repository/task/session identity and sends only gap/source/freshness/coverage codes and evidence IDs. It stores actual runtime outcomes as local-scoped pending candidates. Per-example consent and receipt IDs are not required or stored. Automatic inference uses the existing bounded executor, with at most one queued or running capture; context delivery does not wait for it. The inference result never changes Hub retrieval, routing, permissions, task state, or tool execution. Runtime/provider failures do not change the context response. Startup remains lazy. Training and benchmarks are not started by enabling capture.

The normal Hub status response includes `laya_runtime` lifecycle metadata, and the existing diagnostics ZIP includes the same metadata at `laya/report.json.runtime`. These fields report session availability, whether provider close is configured, in-flight calls, timeout and close errors. `runtime_verification` remains `NOT_VERIFIED` until a connected provider independently verifies placement and release; these status fields do not claim device support or reclaimed memory.

## Code intelligence

`[code_intelligence]` controls Serena enablement, command, query/index deadlines, failure threshold, maximum persistent sessions and session idle TTL. `direct_agent_mcp=false` is recommended because the hub exposes Serena through the compact MCP surface.

## Server/security

The Hub is local-only: its HTTP server binds to `127.0.0.1`, and remote binding or remote Hub access is unsupported. The same-machine Browser Bridge remains available. `request_body_timeout_seconds` bounds slow uploads, `max_concurrent_requests` caps live HTTP handlers, and `overload_wait_seconds` controls the tiny admission wait before a retryable 503.

## Diagnostics support archive

`[diagnostics_export].max_archive_bytes` defaults to 8 GiB; `max_source_bytes` defaults to 64 GiB. The Service health export streams a ZIP64 archive through temporary disk space, so allow enough free space for the SQLite snapshots and compressed ZIP. The archive includes Hub source, redacted effective configuration, all Hub-owned state databases and operational logs across projects. Model weights and other project source stay out. Traces, logs, paths, tasks, and memories may contain private content; the archive is password-protected.

The existing `POST /api/diagnostics/export` request may be empty for a regular export. Candidate text stays out of that export: Laya candidate tables are removed from disposable database snapshots, and candidate-capture debug traces with linked content are removed. The archive includes `laya/report.json` with aggregate candidate counts and metadata-only Laya telemetry. To explicitly include train rows, send exactly `root` and `laya_candidate_export: { snapshot_id: "..." }`. Candidate capture is bound to an authorized repository, task/session, and validated evidence/source provenance. Repository/task/session scope, snapshot, hashes, and verified labels are rechecked; only the train split is added as `laya/candidates.train.jsonl`. The normal archive manifest reports omitted or included candidate rows. The source database and disk model cache are not modified.

Laya capture accepts only actual runtime outcomes recorded by the callback attached to `evaluate_context_source`; it does not accept synthetic or batch capture. Candidates remain pending until a reviewer labels and verifies them. Existing-card export reads only selected cards already present in the Hub index and generates no new cards.

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

`[agents]` enables per-host setup for Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot. `extra_mcp_json_paths` and `extra_vscode_mcp_paths` can target additional MCP hosts without hardcoding vendor directories. Setup preserves unrelated configuration and writes portable manifests under `generated/`. `[agent_output.*]` controls compact host-specific projections after canonical local work, so expensive caches remain shared rather than fragmented by client.

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
