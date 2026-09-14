# Configuration

`defaults.toml` is the authoritative reference. `config.toml` should contain only overrides. User values are merged after the auto-selected hardware profile, so explicit settings always win. Malformed explicit TOML and invalid transport/resource limits fail fast.

## Hardware

`[hardware].profile = "auto"` detects OS, architecture, RAM and NVIDIA/AMD/Intel/Apple graphics. Profiles are `cpu`, `integrated`, `low`, `balanced`, `high`, and `max`. They tune model choices, context, concurrency and batching; they are presets rather than hardware locks.

### Shared-memory iGPU and Intel NPU

The `integrated` profile is intentionally conservative. It is designed for iGPUs that borrow system RAM and therefore must not be scheduled from a nominal/dedicated VRAM value. The default integrated profile keeps one foreground LLM/model resident, disables the independent background Ollama runtime, routes preprocessing to 0.5B, quick tasks to 1.5B, complex work to 3B, and the hardest reasoning to 7B; it also reduces context and preprocessing concurrency. For Intel iGPU systems, see [the llama.cpp SYCL setup](LLAMA_CPP_SYCL.md).

For Intel integrated graphics, `[openvino]` controls optional retrieval acceleration. With `embedding_device = "auto"` / `reranker_device = "auto"`, Local AI Hub probes actual OpenVINO devices and uses `device_priority = ["NPU", "GPU", "CPU"]`. The SentenceTransformers wrapper remains on CPU while the underlying Optimum/OpenVINO model is compiled for the selected accelerator, so the path does not require a torch-native NPU device. `cpu_fallback = true` keeps RAG functional if the NPU/GPU driver or a particular model shape is unsupported.

`[ollama].allow_integrated_gpu` and `enable_vulkan` are enabled only by the integrated hardware profile. They affect hub-managed Ollama processes; a separately started Ollama process must be configured independently.

## Code intelligence

`[code_intelligence]` controls Serena/CodeGraph enablement, commands, query/index deadlines, failure threshold, maximum persistent sessions and session idle TTL. `direct_agent_mcp=false` is recommended because the hub exposes both capabilities through the compact MCP surface.

## Server/security

Loopback is the default. Remote binding requires explicit remote access and a configured API token. `request_body_timeout_seconds` bounds slow uploads, `max_concurrent_requests` caps live HTTP handlers, and `overload_wait_seconds` controls the tiny admission wait before a retryable 503. Never treat tenant IDs as security isolation.

## Foreground repository state

`[workspace_cache]` keeps repository fingerprints off critical request paths. `fingerprint_ttl_seconds` controls the short in-memory reuse window. `git_probe_timeout_seconds` and `git_status_timeout_seconds` are hard foreground budgets; after a timeout, `slow_git_cooldown_seconds` temporarily reuses the last-good or bounded filesystem state rather than stalling the request. `max_changed_paths`, `max_untracked_walk_files`, and `degraded_fingerprint_max_files` bound work on unusually large repositories. Filesystem watchers remain the preferred warm-path invalidation source.

## Search/Git acceleration

`[search].git_files_timeout_seconds` and `git_grep_timeout_seconds` are hard Git subprocess budgets. `git_files_cache_ttl_seconds` coalesces bursty inventories and `git_files_slow_cooldown_seconds` prevents repeated Git probes after a timeout; the hub falls back to bounded Python/indexed paths instead of wedging foreground work.

## Scheduler and command deadlines

`[scheduler].max_caller_wait_timeout_seconds` is a hard ceiling even when a caller omits or overspecifies its wait timeout. Model preparation failures use `model_switch_failure_cooldown_seconds` to fail repeated requests quickly. `[commands].coalesced_wait_seconds` bounds duplicate-command waiters; termination and post-kill drain windows are separately bounded. MCP and local clients additionally clamp their transport deadlines.

## Preprocessing and SQLite

`[preprocessing].sqlite_busy_timeout_seconds` is intentionally short for foreground control writes. `sqlite_write_retries` applies bounded retry with short backoff rather than allowing a single SQLite operation to block for many seconds. Completed projects sleep until their configured recheck time and are woken immediately by relevant watcher events. `watcher_refresh_seconds` controls only watch-registration reconciliation; per-project single-owner execution prevents CPU/GPU background loops from duplicating the same durable step.

## Client cold start

`[client].health_timeout_seconds`, `startup_wait_seconds`, `startup_poll_seconds`, and `start_lock_stale_seconds` bound MCP/CLI auto-start. Startup locks whose owning PID is gone are discarded immediately instead of consuming the full wait budget.

## Tiered Ollama runtime

`[smart_ollama]` is opt-in. The existing user-managed server at `127.0.0.1:11434` continues to serve fast and background model tiers. When enabled, Hub starts only its smart sidecar at `127.0.0.1:11437` for the configured smart model. Port `11435` belongs to Hub HTTP and `11436` remains reserved for the background runtime. The sidecar uses one request slot, 32k context, Flash Attention, and `q8_0` KV cache by default. Before switching tiers, Hub unloads only models named in its own configuration; an unknown model on the user-managed endpoint is never terminated and causes a retryable handoff failure instead.

## Agent integration

`[agents]` enables per-host setup for Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot. `extra_mcp_json_paths` and `extra_vscode_mcp_paths` can target additional MCP hosts without hardcoding vendor directories. Setup preserves unrelated configuration and writes portable manifests under `generated/`. `[agent_output.*]` controls compact host-specific projections after canonical local work, so expensive caches remain shared rather than fragmented by client.

## Headless supervisor

`[headless].health_probe_timeout_seconds` bounds an individual health request. `startup_grace_seconds` gives a newly spawned hub a separate cold-start window, while `unhealthy_grace_seconds` controls recovery of an already-running process. Keep only one supervisor/hub instance per state directory.

## Bundles

`[bundles]` limits compressed bundle bytes, decoded JSON bytes and rows per table. Bundles contain repository-derived local state and should be protected accordingly.

## Agent Operating System state

`[agent_state]` controls the local agent operating system state layer. It is enabled by default (`enabled = true`). When enabled, state is stored in `agent_state.sqlite3` under `server.state_dir`.
- `retention_days = 30`: TTL for terminal tasks, incidents, and unconfirmed memory candidates.
- `snapshot_interval_events = 100`: Periodic state snapshot interval.
- `max_event_bytes = 65536`: Event payload size ceiling.
- `sqlite_busy_timeout_seconds = 5.0` and `sqlite_write_retries = 5`: Bounded concurrency handling with backoff.
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
commands = true           # local_ai_command safe CLI broker
coord = true              # local_ai_coord coordination/leases tool
artifacts = true          # local_ai_artifact evidence slice tool
code_intelligence = true  # Serena & CodeGraphContext backends
preprocessing = true      # Background idle project warmup
subagents = true          # Named advisory subagent profiles
agent_os = true           # Durable execution: task contracts, receipts, memory
```

When a feature is disabled:
- The MCP server unregisters the tool so connected agents do not receive its schema.
- Action lists and documentation for composite tools (`local_ai_repo`, `local_ai_task`, `local_ai_coord`) automatically omit unsupported actions.
- Dynamic agent skills (`SKILL.md`) and instruction policies (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) omit all disabled tools, recipes, and models.

### Regenerating Artifacts

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
