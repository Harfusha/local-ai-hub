# Feature map

| Area | Behavior | Benefit |
|---|---|---|
| Agent surface | 8 compact MCP tools with strong tool-first descriptions and agent-specific projection | Low schema/context overhead across coding agents |
| Execution order | cache → deterministic facts/code index → Serena/CodeGraph → semantic retrieval → minimum local-LLM work | Lower latency and cloud-token use |
| Built-in code intelligence | Incremental symbols, references, calls, imports, manifests, routes, tests, config and risk facts | Common repository questions without a model |
| Adaptive context guard | `local_ai_repo(action="context")` default bounded pack before non-trivial planning/edit/review/test; reuse-first candidates, evidence IDs, guarded override reasons, compact deterministic/local-model composition | Consistent context without duplicate discovery or invented repository facts |
| Serena | Managed project index + MCP symbol lookup/reference queries | Language-aware semantic navigation |
| CodeGraphContext | Managed repository index + graph MCP relationship/dead-code/complexity queries | Call/dependency/impact graph analysis |
| Preprocessing | Durable checkpointed inventory/hash/index/Serena/CodeGraph/RAG/card phases | Reuse expensive discovery across agents and restarts |
| Local agents | Read-only tools for built-in indexes, Serena, CodeGraph, RAG and exact evidence | Local model reasons over tools instead of rereading repositories |
| RAG | CPU embeddings + reranker, persistent query/embedding/reranker caches | Semantic retrieval without consuming foreground accelerator memory |
| Evidence | Content-addressed exact `E…` slices with freshness verification | Progressive disclosure without source rewriting |
| Commands | Safe classified validation/read/build broker, repo-state cache and single-flight | Avoid repeated test/lint/build runs |
| Caching | RAM L1 + persistent SQLite L2 + generation/repo/RAG/command/snapshot caches | Cross-agent reuse |
| Scheduling | Fair queue, model affinity, bounded fallback, foreground/background separation | Fewer model swaps and stalls |
| Hardware | OS/architecture/RAM plus NVIDIA/AMD/Intel/Apple GPU detection, shared-memory `integrated` profile, and optional Intel OpenVINO NPU/iGPU retrieval acceleration | Portable conservative defaults across CPU, iGPU/NPU and discrete GPU hosts |
| Reliability | Timeouts, circuit breakers, stale-root guards, process-tree cleanup, watchdog and disposable derived state | Failure containment |
| Dashboard / operations | Realtime telemetry plus preprocessing, code intelligence, safe commands, bundles, source/dependency audits, maintenance, service controls and validated runtime overrides | Operate the hub without hand-editing derived state |
| Observability | Async metadata-only telemetry, realtime status and end-to-end token accounting (gross avoidance, tool call/read cost, signed net delta, schema scenario and local-compute reuse) | Diagnose latency/adoption/token efficiency without storing source/prompts/tool output |
| Security | Loopback default; remote exposure requires explicit enablement and API token | Safe local default |
| Work orchestration | Durable closed-task plan/DAG execution, transactional leased edits, bounded replanning, validation, whole-task verification and compact artifact-backed handoff | Delegate complete local work without flooding the calling agent context |
| Agent Operating System | Event-sourced journal, tasks, scoped memory, incidents, verification, context compiler, policy & learning | Governed durable agent execution (feature-flagged) |

Hardware profiles are starting points, not hardware allow-lists. Explicit `config.toml` values always override automatic tuning.
