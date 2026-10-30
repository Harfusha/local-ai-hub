# Changelog

## 5.1.2 — 2026-10-30

- Fix Windows read-only SQLite URI handling for drive-letter paths.
- Prevent concurrent Windows initialization of empty cache and code-index lock files from racing before the first lock.
- Resolve Windows SQLite EXPLAIN URIs safely within the repository root and stabilize Windows CI path and Python 3.11 test behavior.
- Decode dashboard Node harness output as UTF-8 on Windows and keep cross-volume tests portable.
- Clamp autostart process timeout to the caller's exact startup budget.
- Keep GitHub failure annotations printable on legacy Windows console encodings.

## 5.1.1 — 2026-10-30

- Discard vision backend output when cancellation arrives after a non-interruptible inference call.
- Serialize MCP HTTP cancellation notifications with compact JSON separators for strict clients.

## 5.1.0 — 2026-10-26

- Follow-up candidate fix: treat upstream Caveman compression output that is not smaller than the input as no useful reduction, and cover that response with a regression test.

- Delivered comprehensive performance optimizations across the entire runtime pipeline (T0–T12).
- Added opt-in native Cython SimHash acceleration through the `[native]` extra with 100% bitwise parity; the default and production wheel remain pure Python.
- Resolved cross-platform command process tree cleanup on POSIX/Linux systems by verifying process group vacancy before confirming termination.
- Added a native benchmark runner emitting perf_candidate.v1 records. The historical JSON-budget tail result used a synthetic baseline and is not acceptance evidence.
- Added authentic 117-query bilingual relevance quality evaluation corpus across all 8 required categories.
- Added bounded thread-safe path resolution cache, cutting Windows realpath syscalls by 94.6%.
- Integrated SQLite embedding cache batching with get_many/set_many across L1 RAM and persistent L2 disk cache.
- Replaced unconstrained lexical fallback with streaming cursor into bounded top-k heap.
- Propagated deadlines and cancellation events into RAG chunk batch scanning and model rerankers.
- Added explicitly configured, task-owned browser and desktop automation behind the MCP surface.
- Fixed dashboard plan creation to emit IDs accepted by the repository plan schema; plan calls now ignore the MCP host's injected active-task acceptance metadata.
- Packaged the repository plan schema with the application and added installed-wheel validation of planner support.
- Fixed dashboard task edits to send canonical coordination fields and select a newly created plan on its board.
- Repaired clean development installs and Python 3.11/3.12/3.13/3.14 compatibility while retaining Windows junction/process identity checks.
- Aligned advisory review generation with JSON consistency contracts and reported deterministic diff counts.
- Redacted credentials idempotently in decision memory and hardened telemetry and SQLite accounting boundaries.
- Hardened FastMCP schema generation and aligned ergonomics parameter contracts across all 7 canonical MCP tools.
- Confined configurable project workspace and plan-intent paths to their repository roots, rejecting traversal and external targets.
- Rejected symlinks and Windows reparse points during repository inventory before scanning or collecting files.

## 5.0.0 — 2026-10-19

- Aligned HTTP, MCP, telemetry, derived state, caches and dashboard rendering on the single-owner runtime contract.
- Added bounded agent event waiting, generic semaphores and project board coordination.
- Updated the managed runtime and generated agent policies for the 5.0.0 release.

## 4.0.0 — 2026-09-21

- Unified task context joins Agent OS state, repository evidence, revisions, freshness and bounded deltas.
- Deterministic quality gates keep local-model output advisory and reject irrelevant, queued, malformed or unverified claims.
- Added shell-safe command transport, review queue SLA, root-family budgets, context reuse and receipt-gated completion.
- Added the 3.0 → 4.0 migration contract and rollback checklist.

## 3.0.0 — 2026-09-08

- One application release contract: Local AI Hub 3.0.0.
- One unversioned internal HTTP namespace under `/api/`; no parallel endpoint aliases.
- Package-native seven-tool MCP server is the only MCP entrypoint.
- Derived Agent OS and telemetry databases use one current schema; non-matching derived state is rebuilt rather than transformed.
- Embedding and reranker caches use one device-qualified key identity and one namespace each.
- End-to-end token accounting uses signed `net_cloud_token_delta_est` as the canonical cloud-efficiency metric, with protocol cost, schema exposure and local-compute reuse reported separately.
- Dashboard HTML owns static labels and layout; JavaScript populates runtime values and state only.
- Historical planning/specification artifacts are not part of the release tree.
