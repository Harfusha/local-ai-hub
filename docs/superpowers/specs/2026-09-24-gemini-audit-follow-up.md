# Gemini audit follow-up — Local AI Hub

Date: 2026-09-24
Source: user-provided Gemini audit (`Pasted text.txt`) and bounded follow-up review for master plan T01–T20.
Purpose: preserve every audit finding, its evidence gap, requested repair, task owner, and acceptance caveat. This is an audit baseline, not a claim that repairs have already landed.

## Decisions and guardrails

- Quality is the top priority. Performance claims require reproducible measurements, not configuration values or larger batch sizes alone.
- Completely remove CodeGraphContext/KuzuDB as a managed, configured, callable, or runtime backend inside Local AI Hub. Documentation may recommend installing CodeGraphContext separately as an optional standalone external tool. Do not retain a Hub integration path.
- Agent 2 retains exclusive ownership of `/api/context/pack`. No T-task may edit or overwrite it.
- T01–T20 run in separate task worktrees, each with a dedicated agent and its own goal. Agents may spawn their own subagents for bounded, disjoint work; each task owner remains responsible for review and handoff. Do not create duplicate task threads.
- T20 prepares release acceptance, but runs final acceptance only after T01–T19 are integrated.
- A task is not `done` until its existing master-plan acceptance criteria and relevant verification have passed. Record actual commands, results, changed paths, owner, and blockers.

## Findings and required follow-up

| # | Area and audit result | Assessment / gap | Required follow-up | Owner |
|---:|---|---|---|---|
| 1 | **Serena timeout and session pool.** Both defaults report 60 s hard query/startup timeouts, 4 s soft timeout, 16 sessions per backend, and 3600 s idle TTL; config tests cover values. | 4/5 for presence, not proven optimal. Memory pressure, contention, latency, and throughput are unmeasured. | Benchmark realistic concurrency, memory, cold/warm startup, timeout rates, and fallback latency. Keep values only if measurements support them. | T02, T10 |
| 2 | **Serena soft fallback and lock.** Soft timeout fallback to CodeIndex and survival of the MCP process have tests. Lock wait is 1.5 s, not the reported 1 s; live Serena behavior is unverified. | 4/5 initially; exact lock contract and live behavior remain open. Follow-up found adaptive context may pass a 3 s hard timeout, expiring before the 4 s soft timeout and killing the process. | Make hard/soft timeout ordering coherent in every caller; bound lock wait to the declared contract; preserve a running Serena process on soft timeout; test fallback metadata, lock contention, and live behavior where available. | T02, T10 |
| 3 | **MCP protocol version.** Client hardcodes `2024-11-05`. The claim that `2025-11-25` was invalid is unsupported; a compatible older version may be intentional. No negotiated server version or live Serena initialize handshake was verified. | 2/5. Static constant is not proof of protocol compatibility. Specification now has newer revisions and handshake behavior changed. | Test initialize negotiation against Serena's supported version(s); handle a server-selected compatible protocol version and incompatibility clearly. Do not change the constant merely to follow an inaccurate claim. References: [2025-11-25 MCP release](https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/) and [2026-07-28 MCP specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/). | T03, T10 |
| 4 | **Empty query.** Adaptive context skips Serena and RAG search, with a test that external backends are not called. | 4/5. Follow-up found workspace lookup can happen before the empty-query guard; runtime behavior beyond the unit seam is not confirmed. | Return promptly before workspace/RAG/Serena work for semantically empty input; test all expensive/remote calls and output contract. | T10 |
| 5 | **Complete CodeGraph/Kuzu removal.** Audit found `external_tools.py` session/config/query paths, a preprocess phase, public MCP description/action, example config, docs and missing `.codegraphcontext` ignore coverage. “Backend removed” status conflicts with callable query code. | 1/5, P1. Hub-side removal is incomplete; RAM/CPU savings are not established. | Remove the Hub runtime, process/session management, config flags, routing, actions, phase/status handling, dependencies, tests and stale managed-backend claims. Keep only a clearly separate standalone installation recommendation outside Hub. Add a complete absence/contract test and ignore generated `.codegraphcontext` data. | T10, T19 |
| 6 | **Native AST call graph.** `find_callers()`/`find_callees()` and Tree-sitter call edges exist for Python, C#, TS/JS, Go and Rust. Coverage is incomplete; “under 1 ms” has no benchmark. | 3/5. Replacement exists, but language coverage and query semantics need proof. Follow-up found callers/callees may return non-call edge kinds; Rust `::` names may not match `/` suffix lookup. | Add direct per-language call-edge tests; filter SQL to `kind='calls'`; fix Rust qualified-name matching; test missing-parser fallback. Benchmark indexed queries and label measurements with dataset/hardware. | T02, T10 |
| 7 | **RAG batch size.** `rag_files_per_step = 128` is configured in both defaults; one profile overrides it to 6. | 3/5. 128 is 8× batch size over 16, not proof of 8–10× end-to-end indexing speed. Memory and failure-recovery tradeoffs are unknown. | Benchmark representative repositories across profiles, including throughput, peak memory, cancellation/retry cost, and end-to-end time. Preserve profile overrides when justified. | T02, T11 |
| 8 | **Parent-to-worktree cache inheritance.** `_seed_from_parent()` exists and tests parent index inheritance; “under 200 ms” has no benchmark. | 4/5 source-level, but cache correctness and performance unproven. Follow-up found RAG hash may be copied without RAG chunks/vectors, causing RAG to be skipped; same-size dirty files may inherit stale hashes/cards; registration/seeding may race. | Seed only artifacts actually copied; verify dirty content rather than size/mtime shortcuts; make registration/seeding atomic or safely retryable; test missing RAG vectors, same-size edits, races, and measure initialization time. | T02, T11 |
| 9 | **Diagnostics, self-root, subprocess cleanup.** Diagnostics phase, timeout/`terminate_tree`, and self-root exception exist. Windows descendant cleanup was not confirmed. | 3/5. Source presence and unit tests do not prove Windows runtime cleanup. Follow-up found diagnostic commands use `Popen(shell=True)` and are not guaranteed read-only. | Enforce read-only diagnostics, bound and drain subprocess streams, terminate descendant trees reliably on Windows; add self-root regression and Windows-gated child-process proof. | T06, T08, T15 |
| 10 | **LLM synthesis switch.** `disable_llm_card_synthesis = true` disables file-card synthesis by default. | 4/5 for file cards only. It does not disable all module/project synthesis and can be overridden. | Clarify exact scope in config/docs; test file, module, and project synthesis independently. Keep any separate semantic work explicitly controlled. | T11, T12, T19 |
| 11 | **Cloud autonomy and native reads.** Semantic handoff is advisory in the inspected prompt/generator paths; native `view_file` guidance is present. | 4/5 for inspected sources, not every generated/install/update policy. Some MCP/agent docs remain stale. | Search and align canonical policies and generated docs: cloud agents may reason/code autonomously; local models remain on demand/advisory per policy; native bounded reads are permitted. | T12, T19 |
| 12 | **`local_ai_repo` pipeline.** Runtime permits parallel non-mutating steps (up to four) and serializes mutation actions. Generated schema omits `steps`. Duplicate actions overwrite by action key; completion count can be wrong; top-level success may remain true after nested failure. | 2/5, P1. Schema prevents reliable client construction and aggregate result can lie. Follow-up also flags malformed step input raising instead of a structured per-step failure. | Add runtime/schema parity; validate malformed steps into bounded structured errors; preserve duplicate step results by stable position/id; count attempted/completed correctly; derive aggregate success from all required step results; test mixed success/failure, duplicates, mutation serialization and concurrency cap. | T03 |
| 13 | **`local_ai_artifact` schema.** Runtime supports `action="list"`, empty/default `artifact_id`, and binary mode; generated schema still requires the ID and omits binary. | 2/5, P1. Strict MCP clients cannot reliably call supported runtime behavior. | Generate schemas from the actual callable contract; add generated-schema parity tests for required/optional fields, defaults, enums and binary output. | T03, T14 |
| 14 | **`local_ai_status` alias.** `action` works as alias for detail; runtime supports `status/health/check/info` beyond generated schema. | 3/5. Alias is usable, but strict-client discoverability and supported values disagree. | Decide canonical actions/aliases; align runtime and generated schema; verify alias behavior and status field parity. | T03, T18 |
| 15 | **`chunks.embedding_space` old database.** New table creation includes the column; audit found no old-schema migration/check. | 1/5, P1. Existing derived DB may fail later queries. Repo policy says no migration shims for this initial-release branch and derived SQLite state is disposable. | Prefer reliable detection and rebuild of disposable derived `chunks` state, or another policy-compliant recovery; do not add a deprecated migration shim. Test a database with the old schema and verify useful recovery/no silent data corruption. | T11 |
| 16 | **Windows absolute lease paths.** In-root Windows path normalization exists; tests mainly use host-native absolute paths. An out-of-root absolute path may collapse to a basename and collide. | 3/5. Cross-platform safety and repository boundary are not proven. | Normalize Windows-style paths independent of host; accept paths proven inside root; reject out-of-root/ambiguous paths instead of falling back to basename; test drive, UNC, traversal and case behavior. | T09 |
| 17 | **Agent phase aliases.** Aliases exist, but lacked direct tests. Canonical implementation phase is `implementation`, not `execution`. | 3/5. Behavior may be valid, but mapping/output contract differs from informal description. | Define canonical phase names from actual enum; test every alias maps to supported canonical state and is persisted/queried consistently. Do not invent unsupported phases. | T08 |
| 18 | **Windows Job Object.** Handle check/helper and Windows descendant integration test exist; test was not run. Audit follow-up notes the termination API result may be ignored before emptiness check. | 3/5 design; runtime acceptance unproven. | Check and surface Job Object termination failures; test wrong/bool handle and API failure branches; run bounded Windows descendant termination test and verify no child remains. | T06 |

## Cross-cutting acceptance

1. Compare generated MCP schemas against actual runtime tool signatures and behavior; include a captured/live FastMCP schema check where practical. A hand-maintained schema-only assertion is insufficient.
2. Preserve negative/failure expectations. Do not make flaky suites green by weakening assertions; investigate shared state, order dependence, cleanup, and timing. Keep T02's originally observed combined-suite failure (2/25) unconfirmed until reproduced or explained.
3. Distinguish static inspection, unit tests, benchmark results, Windows runtime tests, live Serena handshake, and installed-instance acceptance. Report each as separate evidence.
4. Keep task status one of `not started`, `active`, `blocked`, `review`, `done`; record owner, changed paths, exact command, actual result, and blockers. `done` requires plan criteria plus verification.
5. T20 final release checks run only after the task branches are reviewed and integrated. No full-suite acceptance from isolated worktrees alone.

## Task ownership map

| Task | Audit work included |
|---|---|
| T01 | `--check` read-only inventory bug; API coverage inventory and generated surface checks. |
| T02 | Flake investigation and honest latency, memory, throughput, seed-time, and call-graph baselines. |
| T03 | Pipeline/artifact/status schema-runtime parity; malformed and partial-failure contracts; MCP negotiation contract. |
| T04 | Endpoint/client/conversation regression coverage outside Agent 2's `/api/context/pack`. |
| T05 | Identity, shared-memory isolation, provenance and trust boundaries. |
| T06 | Mutation/process safety, Windows Job Object failure handling and descendant cleanup. |
| T07 | Retry/idempotency/side-effect correctness. |
| T08 | Agent OS state/events/recovery and phase-alias tests. |
| T09 | Verification receipts, Windows path normalization and worktree ownership. |
| T10 | Serena fallback/empty-query/protocol; CodeGraph/Kuzu removal from Hub; AST call graph correctness. |
| T11 | RAG batching, parent cache seeding/hash correctness, synthesis scope, old derived SQLite state recovery. |
| T12 | Model routing, local/cloud autonomy policy behavior and inference scheduling. |
| T13 | Async job lifecycle and conversation reliability. |
| T14 | Context budgets, artifacts and cache/token accounting. |
| T15 | Command streaming, performance and safe process execution after T06 contracts. |
| T16 | Orchestration and handoff, depending on T06/T08/T09 contracts. |
| T17 | Browser/vision/audio acceptance in its existing task/worktree; keep prior symbol ownership constraints; never touch `/api/context/pack`. |
| T18 | Status/dashboard/telemetry/admin truthfulness and boundedness. |
| T19 | Canonical install/update prompts and docs; remove stale managed-CodeGraph claims, retain standalone recommendation only. |
| T20 | Release acceptance matrix now; final verification after T01–T19 integration. |

## Orchestration note

The active Codex goal text API exposed in this run can read the goal and change its status, but cannot edit an active goal's objective. Therefore the existing goal remains active and unchanged in metadata; this document is its durable scope amendment. The master task conversation must also retain this amendment. Do not complete and recreate the goal merely to change wording.
