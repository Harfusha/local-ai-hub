# Architecture

Local AI Hub is a local deterministic-first service between coding agents and repository/model tooling. The design goal is to reduce cloud-context duplication while keeping expensive or failure-prone work bounded.

## Layers

1. **Compact MCP surface** — seven public tools in `src/local_ai_hub/mcp_server.py` (`local_ai_status`, `local_ai_task`, `local_ai_repo`, `local_ai_rag`, `local_ai_coord`, `local_ai_work`, `local_ai_artifact`); agent-specific projection and result compaction happen before responses leave the hub.
2. **HTTP service** — authenticated local API, request limits, recovery journal, telemetry and dashboard.
3. **Deterministic repository layer** — inventory/search, code index, AST/facts, dependency/security/test/git analysis, evidence and artifacts.
4. **Code intelligence** — the built-in Tree-sitter/SQLite index provides deterministic symbols and call relationships; optional Serena adds semantic navigation. Serena runs in timeout-bounded per-project sessions with LRU/TTL eviction and circuit failure handling. CodeGraphContext/KuzuDB are not Hub backends.
5. **Retrieval** — lexical search, semantic cache, embeddings/reranking and RAG; deterministic sources are preferred before semantic retrieval.
6. **Local inference** — Ollama scheduler with background/fast/smart roles selected by configuration/hardware profiles.
7. **Preprocessing** — checkpointed pipeline that warms indexes and cards without blocking interactive requests.

## Local-only control boundary

Local AI Hub has no remote-use or remote-control mode. The HTTP daemon binds only to `127.0.0.1`; `HubClient` and supervisor probes target that address directly. The dashboard and stdio MCP adapter use loopback HTTP only as same-machine internal transport. `server.client_host`, `security.allow_remote`, and non-empty `security.allowed_hosts` or `security.allowed_origins` are removed and rejected. Credentials do not enable remote access. Same-machine Browser Bridge support is separate from remote Hub access.

## Task context and model boundary

`/api/agent-state/context` is the unified task-context contract. It joins Agent OS state (goal, checkpoint, receipts, memories, leases and incidents) with the revision-bound repository context pack. `context_id` and `etag` identify the bounded result; stale or mismatched revisions are partial and cannot establish completion. `local_ai_task(task_id=...)` consumes this contract before semantic inference, while deterministic facts and validation remain authoritative.

Local-model responses pass a deterministic quality assessment for empty, queued, malformed, error and unrelated-path output. Every result stays visible and advisory; weak results carry `semantic_quality`, `quality_warning` and a bounded bypass reason instead of being discarded or converted into a task failure. Model candidates require reproducible evaluation receipts and a quality floor before promotion.

## Failure model

Derived state is rebuildable. External tools and local models are optional dependencies: failures degrade the affected layer instead of blocking deterministic repository operations. Timeouts exist at HTTP, command, scheduler and MCP subprocess boundaries.
