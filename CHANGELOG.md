# Changelog

## 3.0.0 — 2026-09-08

### Unified single-version surface — no legacy, no versioned branching

- **Removed all backward-compatible token accounting fallbacks.** `cloud_tokens_avoided_est`, `net_cloud_tokens_avoided_est`, `legacy_inference_cloud_tokens_avoided_est`, and `token_accounting_version` fields are gone from the telemetry surface. The canonical field is `net_cloud_token_delta_est`.
- **Dashboard labels are now consistent between HTML skeleton and JS.** JS no longer rewrites card labels based on `token_accounting_version` — the HTML renders the correct label (`Net cloud token delta`) from the start and JS only sets content values after load.
- **Removed legacy `tokensSavedSub` branch** (`legacy inference estimate · N cache hits`). The v3.0 subtext always renders the full breakdown: `baseline X − protocol Y (call Z + read W) · schema-adjusted N`.
- **Simplified `netDelta` and `schemaDelta`** JS expressions — removed `?? cloud_tokens_avoided_est` and `?? net_after_schema_tokens_avoided_est` fallback chains.
- **Cache layers table** now shows `net_cloud_token_delta_est` instead of the legacy `cloud_tokens_avoided_est` column.
- **Removed backward-compat attribution block** in `record_tool_accounting` that inferred `gross_input`/`gross_output` from early v2.4 reporters that only sent `savings_breakdown`. Callers must now supply explicit gross input/output fields.
- **Simplified `record_tool_accounting` field references** — all `event.get(field, event.get(old_alias, 0))` chains replaced with direct `event.get(field, 0)`.

## 2.4.0 — 2026-09-08

### End-to-end token-efficiency accounting
- Added MCP-boundary accounting that measures the agent-visible tool name/arguments and projected tool response, subtracting both from gross cloud-context/output avoidance. A signed net token delta exposes calls that cost more context than they save instead of hiding the overhead behind a zero clamp.
- Added separate gross input/output avoidance, tool-call tokens, tool-read tokens, protocol overhead, local-compute reuse and a conservative schema-adjusted scenario. Enabled-tool schema exposure stays separate from the default net metric because MCP hosts differ in schema injection/caching behavior.
- Added no-double-count savings attribution: overlapping deterministic/index/context transformations compete for the strongest counterfactual source baseline. The visible projected response is charged once; response compaction remains diagnostic and becomes the selected baseline only when no stronger upstream source baseline exists. Deterministic outline, bounded lexical-search candidate selection, diff/context packing, routed context and artifact-backed last-mile compaction now contribute to the same accounting model.
- Added local inference tokens avoided by exact/semantic/single-flight/stale cache reuse as a separate compute-efficiency metric rather than inflating cloud-context savings.
- Added additive telemetry/daily-rollup schema migration, per-source savings breakdown, dashboard/monitor fields and metadata-only batched reporting. Accounting never persists prompts, source, tool arguments or tool output.

### Latency, blocker and release hardening
- Removed synchronous telemetry flushes from live status/dashboard hot paths and moved MCP accounting delivery onto a lazy bounded daemon batcher with short best-effort deadlines, so observability cannot back-pressure foreground agent calls.
- Added bounded validation for the internal accounting endpoint and excluded that endpoint from normal workload journaling/accounting to prevent recursive telemetry.
- Fixed clean-checkout TaskStore bootstrap: the task projection no longer requires the AgentState SQLite file to pre-exist before the state store is allowed to create its schema.
- Streamlined token serialization/accounting and kept private accounting metadata out of agent-visible projections.
- Removed local runtime/internal artifacts from the release tree and aligned package/release/documentation metadata to 2.4.0.

## 2.3.0 — 2026-09-07

- Added durable **whole-task Work Orchestrator** (`local_ai_work`): closed repository tasks are decomposed into bounded dependency-ordered steps, executed serially for local-LLM safety, validated, integrated and verified against the original request before a handoff is returned.
- Added transactional edit journals outside Git, bounded path leases, crash-safe rollback/recovery, patch traversal/symlink/binary protections, create/delete permissions and bounded patch size/file limits.
- Added compact agent response profiles (`minimal`, `compact`, `standard`, `debug`), explicit field projection and output-token budgets with lazy artifact-backed details.
- Tightened the shared-memory `integrated` notebook profile: one inference/model, queue 32, per-tenant queue 12, async pending 16, 15 s preprocessing idle grace, prewarm off, two code-intelligence/headless sessions and bounded debug retention.
- Added bounded deterministic inspection parallelism while keeping LLM/edit work serial on integrated hosts. Planner dependencies are now normalized into a stable topological execution order, including forward references; cyclic plans fail closed instead of silently discarding edges.
- Hardened work-order admission with serialized queue-capacity checks and bounded printable work IDs, preventing concurrent submitters from exceeding configured queue limits or storing unbounded identifiers.
- Final verification is fail-closed: mutating work requires successful validation evidence and explicit acceptance criteria must be positively covered.
- Preserved v2.2 Intel NPU → iGPU → CPU OpenVINO retrieval fallback and conservative 0.5B/1.5B/3B local-model sizing.
- Expanded the compact public MCP surface from seven to eight tools with one deliberate high-level orchestration tool rather than exposing internal planner/executor primitives. The `/v1/work-orders` transport is routed through the authenticated POST pipeline with bounded endpoint schema validation, matching the MCP client contract.
- Final orchestration hardening treats cross-path patches as create+delete for permission enforcement, sanitizes duplicate/malformed planner step metadata, closes the idle-worker retirement race, and refreshes the shipping `AGENTS.md` policy so agents actually prefer `local_ai_work` and compact projected handoffs where appropriate.

## 2.2.0 — 2026-09-07

### Conservative integrated-GPU profile
- Added the `integrated` hardware profile for shared-memory iGPU notebooks and stopped treating Windows `AdapterRAM` aperture values as dedicated VRAM budgets. Intel Arc A/B-series discrete adapters remain classified as dGPUs.
- The integrated profile keeps one foreground request/model resident, disables the separate background Ollama process, uses 0.5B/1.5B routine coding models with a 3B heavy/reasoning ceiling, reduces context/batch/preprocessing budgets, and reserves additional shared-memory headroom.
- Hub-managed Ollama can explicitly admit integrated GPUs and Vulkan for this profile while preserving serial scheduling and CPU fallback behavior. Dashboard/system telemetry labels shared-memory iGPUs without presenting aperture memory as VRAM.

### Intel NPU / iGPU retrieval acceleration
- Added optional OpenVINO detection, status reporting, setup/prefetch support and `requirements-openvino.txt`. Intel integrated profiles use small export-friendly embedding/reranker models and device priority `NPU -> GPU -> CPU`.
- OpenVINO placement is passed to the underlying Optimum model while the SentenceTransformers wrapper stays on CPU, avoiding accidental dependency on a torch-native NPU backend. Model-load and first-inference failures advance to the next accelerator and finally the CPU SentenceTransformers backend.
- Added NPU discovery on Windows (including Intel AI Boost naming), OpenVINO device discovery, accelerator diagnostics in `doctor`, application status and dashboard summaries, plus cache identities that include the backend/device actually producing embeddings.
- Embedding and reranker caches now preserve v2.1 CPU entries through read-through migration while keeping NPU/GPU/CPU results device-qualified. Reranker requests restart atomically when first-inference fallback changes devices, preventing mixed-device score sets or cache writes under a stale accelerator identity.

### Packaging and compatibility
- Added the `intel-accelerators` optional dependency, ships the OpenVINO requirements/prefetch helper, accepts `integrated` across setup/runtime dashboard configuration, and keeps OpenVINO optional so non-Intel/CPU-only installations retain the 2.1 dependency surface.
- Updated release tests/documentation for 2.2 and added regression coverage for iGPU classification, conservative profile limits, OpenVINO NPU-to-GPU fallback, accelerator placement, cooldown behavior and managed Ollama iGPU admission.

## 2.1.0 — 2026-09-07

### MCP process lifecycle and concurrency
- Bound each managed stdio MCP reader to the exact subprocess generation and per-generation response/diagnostic buffers, preventing late readers from an old Serena/CodeGraph process from consuming or injecting JSON-RPC traffic after a fast reset/restart.
- Added bounded reader-thread joins and stale diagnostic cleanup during MCP resets/close, plus context-manager support for managed MCP clients and external code-intelligence sessions.
- Hardened external index execution so unexpected pipe/runtime failures still terminate and reap the indexer process, and made multi-session shutdown best-effort so one failing close cannot strand later sessions.
- Cleared CodeGraph session-access metadata immediately when indexing invalidates a project session.
- Bounded per-root repository fingerprint single-flight waits with `fingerprint_flight_timeout_seconds`; a pathological/network filesystem can no longer make every request for that root wait indefinitely behind one owner.
- Short explicit MCP call deadlines are now honored down to a small safety floor instead of being silently inflated to 500 ms, reducing fallback-chain tail latency.
- Process liveness now distinguishes exited-but-still-handleable Windows processes as well as Linux zombies, avoiding unnecessary termination grace waits on both platforms.
- Partial programmatic configurations without `server.state_dir` use a process-scoped private temporary state directory instead of writing `cache.sqlite3` into the current checkout; forked children derive their own fallback path.

### Release integrity
- Added an optional expected-version gate to `tools/release_check.py`; tagged releases now fail before build when the Git tag and package/release metadata disagree.
- Tagged release builds now smoke-install the generated wheel and verify its runtime `__version__` against the tag.
- CI/package and tagged-release jobs now require no tracked test/setup mutations, clean ignored runtime/build side effects, and rerun the release hygiene gate immediately before packaging.
- GitHub release assets now include `SHA256SUMS.txt` covering the built wheel and source distribution.
- Post-test release validation now runs before ignored-file cleanup and permits only known test/build caches, so newly created runtime SQLite/config/generated payloads cannot be silently erased and masked.
- `ORIGINAL_REQUEST.md` is treated as an internal-only workspace artifact and is explicitly rejected/removed from release checkouts.

## 2.0.0 — 2026-09-06

### Release hardening
- Added `tools/release_check.py` and wired it into CI and tagged releases so local configuration, runtime SQLite files, coverage/cache data, generated payloads, egg-info and internal agent workspaces fail the release gate instead of leaking into a package/repository snapshot.
- Stopped including user-owned `config.toml` in source distributions; `config.toml.example` remains the portable template.
- Made `tools/selftest.py` use the package version dynamically so future releases cannot silently drift from the live health contract.

### Cross-platform reliability
- MCP modules can now be imported without the optional MCP SDK; only actual server execution fails with the dependency guidance. This keeps diagnostics, static inspection and offline tests usable.
- Added host-independent rooted-path detection so Windows drive/UNC paths are not treated as relative on POSIX hosts, and hardened lease paths against drive-qualified traversal forms on every OS.
- Preserved foreign-platform absolute client roots instead of accidentally prefixing them with the current workspace.

### Storage and preprocessing performance
- Unified preprocessing connections/retries/WAL initialization with the shared SQLite support layer while retaining its larger bounded cache/mmap hints.
- Enabled SQLite foreign-key enforcement on all shared connections.
- Added query-aligned indexes for task recency/status, memory expiry cleanup, incident fingerprint lookup/recent retry decisions and verification receipt recency.
- Kept preprocessing incremental/watch-driven behavior and cached generation-level pruning while removing duplicated lock/busy retry logic.

### Agent context and coordination
- Context compilation now invalidates knowledge links only for explicitly changed paths, honors `include_kinds`, and can include active repository write leases so workers avoid planning conflicting edits.
- Lease-aware context is wired through the application and HTTP agent-state transport with the current tenant identity.

### Lifecycle and live-state correctness
- `LocalAIApp` is an idempotent context manager and now shuts down prewarm/watchdog, preprocessing, external-tool, async-job, background GPU, scheduler, telemetry and logging workers in a bounded order.
- Async-job scheduler watchers are explicitly owned, stop on manager shutdown or durable job completion/cancellation, and reject submissions after close instead of leaving orphan helper threads.
- Agent-state counts are refreshed even when the expensive system status snapshot is cached, preventing stale task/memory/incident summaries immediately after state mutations; `status()` now also returns the standard `success: true` marker.

## 1.6.0 — 2026-09-05

### Agent Operating System & Intelligence
- **Autonomous Multi-Agent Swarm Orchestrator**: `SwarmCoordinator` managing complex multi-step workflows (`CODING`, `TESTING`, `REVIEWING`, `COMPLETED`, `FAILED`) with atomic scope leases, CRDT blackboard task state, and evidence-backed verification receipts. Exposed via `swarm_dispatch`, `swarm_step`, and `swarm_status` in `local_ai_coord`.
- **AST Call-Graph Semantic Diff**: Detects breaking signature changes in Python code (added required parameters, removed/renamed arguments) and performs AST call-site analysis across the codebase to identify broken callers. Exposed via `call_graph_diff` and `semantic_diff` in `local_ai_repo`.
- **Hardware-Adaptive Benchmark Suite**: `HardwareBenchmarkRunner` measuring real TTFT (time-to-first-token), token throughput (TPS), VRAM footprint delta, and composite hardware capability score (0–100). Exposed via `hardware_benchmark` in `local_ai_task` and `/v1/benchmark/summary`.
- **Real-Time Command Output Streaming**: Dual-thread non-blocking stdout/stderr stream readers with real-time SSE event dispatch (`command.log`) over `/v1/agent-state/events/stream`.
- **Autonomous Self-Healing Repair Loops**: Automated fix synthesis, speculative patch application with in-memory backups, re-testing, and automatic verification receipt minting on success or clean rollback on failure.

## 1.5.0 — 2026-08-29

### Contention and hang hardening
- Added a bounded HTTP admission gate, slow-body timeout and retryable 429/503 responses so connection bursts cannot create unbounded handler threads. Supervisor and autostart health logic now treat admission 503 as alive-but-busy instead of triggering restart/spawn storms.
- Added hard scheduler caller deadlines even when callers omit a timeout, model-switch failure cooldowns, and compatibility with runtime adapters whose successful `prepare_model()` returns no eviction list. OpenAI-compatible streaming now uses the same affinity scheduler/model policy and closes recovery/telemetry lifecycle state.
- Converted repository fingerprint coalescing to real per-root single-flight locks, allowing independent workspaces to probe Git concurrently instead of serializing behind one global lock.
- Bounded external MCP response queues and discard stale response IDs so a broken peer cannot grow memory or make every future call rescan old responses.

### SQLite and cache reliability
- Centralized SQLite connection/WAL/busy handling across cache, telemetry, RAG, deterministic, CodeIndex, evidence, learning, artifacts, memory, leases, semantic cache and recovery journal stores. WAL setup is no longer repeated on normal hot-path connections.
- Separated transient `locked`/`busy` contention from corruption recovery. Busy stores use short bounded retry/fallback and are never quarantined as corrupt solely because another writer holds the database.
- Reduced write amplification on cache/evidence/semantic read hits and made expired read paths non-mutating where safe. Shared SQLiteCache files perform schema/integrity initialization only once per process/path.

### Agent and command behavior
- Strengthened installed skills, global agent policy and MCP descriptions around cheapest-first retrieval, exact-once asynchronous preprocessing, evidence reuse, no duplicate native discovery, no polling, and bounded fallback behavior. Agents now have explicit stop conditions, result-state semantics (`cache_hit`/`coalesced`/`in_progress`/`retryable`/`degraded`) and a prohibition on fanning out overlapping retrieval layers for the same question.
- Duplicate cached commands now have a finite coalesced wait and return `in_progress=true` rather than launching duplicate work. MCP command host timeouts leave termination margin for the child process.
- Added explicit generic MCP/VS Code config paths for clients beyond the built-in Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot integrations.

### Runtime contracts, process lifecycle and cross-platform quality
- Completed the real `OllamaRuntime` contract used by scheduler/background preprocessing (`request_interruptible`, `prepare_model`, `unload`), added one-total-deadline retry semantics, managed-server startup single-flight, stale PID validation and POSIX process-group lifecycle handling. This closes latent production-only failures previously masked by fake runtime adapters in tests.
- Completed the built-in `CodeIndex` contract (`file_summary`, `related_paths`, `impact`, `prune`) used by deterministic, search, impact and preprocessing layers. Impact queries are parameter-batched for compatibility with SQLite builds that use conservative host-variable limits.
- Reused one persistent background GPU executor, bounded helper-thread shutdown, cleaned per-root fingerprint flight locks after use, preserved sub-second cache TTLs, and added POSIX listening-PID discovery for managed-process recovery.
- Hardened Linux bootstrap for apt/dnf/zypper/apk/pacman and root-without-sudo environments; hardened Windows Python 3.14 bootstrap when the new interpreter is not yet visible in the current shell.
- CI keeps Python 3.11–3.14 across Linux, Windows and macOS and adds an installed-wheel import smoke test.
- Added v1.5 production regressions for SQLite busy/corruption separation, shared-cache initialization, HTTP overload shedding, scheduler deadline/model-switch behavior, per-root Git concurrency, retryable client metadata, custom MCP configs, stale external MCP responses, real runtime/CodeIndex interface contracts, interruptible model streams, single-flight Ollama startup and large-diff CodeIndex impact.

## 1.4.0 — 2026-08-29

### Preprocessing and cache reuse
- Added per-project single-owner execution so CPU and GPU preprocessing loops cannot duplicate the same durable phase or contend on its SQLite writes.
- Reused one bounded CPU thread pool for hashing/lexical micro-jobs instead of recreating executors every step.
- Reworked filesystem-watch lifecycle: watches are reconciled for active roots, removed for paused/unregistered/deleted projects, and the watcher is restarted by resilience checks if it exits.
- Repository search now consumes preprocessed FTS/card candidates in addition to deterministic/CodeIndex candidates. A preprocessing lookup failure no longer discards already-valid cheaper candidates.

### Foreground latency and process resilience
- Added cached + per-root single-flight `git ls-files` inventory, strict Git helper budgets, and slow-repository cooldowns; repeated timeout storms fall back to bounded Python/index paths.
- Added `git grep` cooldown after timeout and surfaced Git file-list/coalescing/cooldown counters in repository snapshot stats.
- MCP/CLI startup locks now validate owner PID + age, removing dead locks immediately. Health/startup budgets are configurable and use monotonic deadlines.
- Setup/service/dashboard subprocesses now have finite default deadlines so platform management commands cannot hang indefinitely.

### Agent integration
- Strengthened the `local-ai-orchestrator` contract into a mandatory cheapest-first tool gate: preprocess once without polling, deterministic/indexed retrieval first, RAG/model reasoning last, cached command execution before repeated shell work, exact evidence slices instead of broad rereads, and bounded fallback behavior.
- Added setup integration and compact output profiles for Cursor, Windsurf and VS Code/Copilot while retaining Codex, Claude and Gemini support.
- Setup always emits portable generic MCP and VS Code manifests plus a reusable agent-policy document; user-owned unrelated configuration is preserved.
- Added explicit multi-agent lease/memo guidance and prohibited `force`/`preprocess_refresh` as normal retry mechanisms.

### Compatibility and quality
- Expanded stable CPython coverage to 3.11–3.14 across Linux, Windows and macOS CI; Windows/macOS bootstrap prefers Python 3.14 when installation is required.
- Added v1.4 regressions for preprocessing single ownership, foreground CPU policy, Git cache/cooldown behavior, stale startup locks, new agent projections and VS Code/portable manifests.
- Release metadata, packaged defaults, documentation and live self-test expectations are aligned to 1.4.0.

## 1.3.0 — 2026-08-28

### Foreground latency and cache correctness
- Bounded repository fingerprints so slow Git can no longer hold `/v1/command`, search or context requests for 15 seconds; timeouts degrade to a stale last-good or bounded filesystem fingerprint instead of failing the request.
- Changed Git discovery from recursive untracked expansion to collapsed untracked directories and metadata signatures, with a cooldown for repositories where Git is temporarily slow.
- Watcher revisions and dirty paths now invalidate warm repository caches immediately without spawning Git, and changed-intelligence refresh reuses that same state instead of performing a hidden second fingerprint.
- Repository-state health/cooldown counters are exposed in realtime runtime statistics.

### Preprocessing
- Fixed the completed-project scheduler: a completed project now truly sleeps until `next_check_at` or a filesystem event instead of being immediately selected for another inventory pass.
- Added a watcher-driven incremental inventory path that updates only changed files; full inventory remains a periodic/fallback consistency pass.
- Coalesced editor filesystem event storms and handles source/destination paths for moves.
- SQLite WAL mode is initialized once, foreground writes use short `BEGIN IMMEDIATE` transactions with bounded lock retry, and long per-connection lock waits were removed.

### Service resilience
- The HTTP port is bound before application/database construction, preventing a duplicate hub process from opening shared SQLite stores before discovering that another hub already owns the port.
- Supervisor cold-start grace is separated from runtime unhealthy grace, reducing restart loops during startup while retaining bounded recovery after a running hub becomes unhealthy.
- Client-visible cache metadata reports degraded/stale repository state when the bounded fallback path is active.

### Quality
- Added production-log regression coverage for Git timeout degradation, watcher-only incremental updates, SQLite lock recovery, completed-project sleep semantics and duplicate-process startup behavior.
- Release metadata, packaged defaults and self-test expectations are aligned to 1.3.0.

## 1.2.0 — 2026-08-28

### Interactive performance and caching
- Fixed accelerated search misses: a successful zero-result ripgrep/git-grep query no longer falls back to an O(repository) Python scan.
- Complete watched projects use an in-memory/SQLite generation fingerprint on warm repository requests instead of repeatedly spawning Git.
- Foreground project LRU touches are debounced and no longer mutate preprocessing revision state.
- Deterministic and CodeIndex foreground queries refresh only changed paths while background preprocessing catches up.
- Expensive deterministic operations share repository-state cache and single-flight coalescing.

### Incremental preprocessing
- Structural invalidation is topology-based rather than file-size-based; normal edits stay incremental.
- Git-aware rechecks use changed paths and long warm intervals while filesystem watchers wake projects immediately on real changes.
- Mtime-only changes preserve semantic cards when file bytes are unchanged.
- Hashing uses a hash-only path and larger bounded batches; CodeIndex and deterministic indexing batch SQLite reads/writes and generation invalidation.
- Fixed active-project enforcement and made background preprocessing yield to interactive foreground work.
- Implemented CodeIndex pruning so deleted source does not remain in the derived symbol index.

### Local model intelligence
- Exact local-agent cache is checked before preprocessing, deterministic, Serena or CodeGraph bootstrap work.
- Preprocessed cards and precomputed deterministic/CodeIndex intelligence are now actually included in the local-model prompt.
- Repository solve pipelines pass already-computed bootstrap evidence into local synthesis instead of recomputing it.
- High-confidence warm tasks can use a one-shot synthesis path without sending tool schemas; uncertain tasks retain the bounded read-only tool loop.
- Bootstrap evidence is compacted to coordinates/facts/symbols rather than duplicating raw source text.

### Agent and operator surface
- MCP is package-native (`python -m local_ai_hub.mcp_server`) so integrations do not depend on a release-directory wrapper path.
- Public MCP surface remains exactly seven compact tools with deterministic/cache-first routing.
- Dashboard removes Code Explorer, Commands and Architecture from the primary operator surface and shows the actual 13-phase preprocessing pipeline including Serena and CodeGraph.

### Quality
- Added performance regressions for accelerated search misses, incremental invalidation, batched indexes and local-agent cache-before-bootstrap behavior.
- Release metadata, packaged defaults, installer integration and diagnostics are aligned to the package-native 1.2 surface.

## 1.1.0 — 2026-08-27

### Reliability and correctness
- Fail-fast TOML parsing and validation for transport/resource limits.
- Persistent cache reads now update hit/LRU metadata and self-heal malformed JSON rows.
- Bounded LRU/TTL Serena and CodeGraphContext MCP sessions with reset/rediscovery controls.
- Fixed the public code-index query endpoint, multi-language import resolution, stale-root handling and bundle schema mismatches.
- Bundle v2 adds integrity validation, ZIP/path/size limits and lossless binary embedding round-trips.
- HTTP request size/time limits, strict JSON/content-type handling, hardened response headers and normal client-disconnect handling.
- Command policy is fail-closed for unknown/mutating package-manager, build and formatter invocations.
- SQLite and managed MCP subprocess resources are explicitly closed; the test suite treats resource/unraisable/thread warnings as failures.

### Agent/tooling
- Kept the public MCP surface at seven tools while routing semantic and graph work through managed Serena/CodeGraph backends.
- Repository tool instructions explicitly prioritize Local AI Hub before broad reads/searches and repeated shell validation.
- `resolve_imports` now supports automatic Python/C#/TypeScript/JavaScript detection.
- Hardware-driven model roles are exposed as background/fast/smart instead of assuming fixed model sizes.

### Dashboard and operations
- Token-aware remote dashboard shell, safe command classify/run, bundle import/export, Serena/CodeGraph reset/rediscovery, operational log tail, doctor, preprocessing controls, maintenance and service restart/stop.
- Fixed duplicate DOM IDs and bundle upload contract; dashboard JavaScript is parser-checked in tests.
- `tools/doctor.py` is a non-starting probe: diagnostics no longer bootstrap the service and mask an offline hub.

### Tests and distribution
- Expanded regression coverage across config, cache, external tools, semantic cache, deterministic/code-index behavior, bundles, dashboard and real HTTP process behavior.
- Release packaging includes defaults, installers, MCP wrapper, skills, docs and tests; CI covers Windows/macOS/Linux and Python 3.11–3.13.

## 1.0.0 — 2026-08-27

Initial open-source release.

- Seven-tool compact MCP interface for Codex, Claude Code, Gemini CLI and MCP-compatible agents.
- Deterministic repository analysis, evidence store, command broker, RAG, caching and local Ollama agent pipeline.
- Managed Serena and CodeGraphContext integration in preprocessing, MCP repository queries and local-model tool loops.
- Cross-platform hardware detection and automatic `cpu`, `low`, `balanced`, `high` and `max` resource profiles.
- Idempotent installer with optional Ollama, local NLP models, Serena, CodeGraphContext, agent policy/skill configuration and per-user service setup.
- Headless supervisor, bounded timeouts/circuit breakers, stale-root handling and disconnect-safe HTTP responses.
- Metadata-only observability, realtime dashboard and diagnostics.
