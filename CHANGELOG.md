# Changelog

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
