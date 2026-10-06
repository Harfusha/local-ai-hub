# Adaptive Retrieval Orchestrator Design

## Goal

Make repository context retrieval quality-first: combine deterministic/indexed evidence, built-in code intelligence, Serena, CodeGraphContext, lexical search, RAG, and bounded local-model reranking before returning a context pack.

## Current problem

The MCP context action forwards the full task/query to the repository layer. The lexical fallback tokenizes prose into flat `OR` patterns and can run a broad `git grep`. The tool agent only asks Serena or CodeGraphContext when it notices selected words in the task. The deterministic fast path can return before other useful evidence contributes.

## Design

`/api/context/pack` remains the public contract. Its internal retrieval pipeline becomes adaptive:

1. Capture repository revision, phase, changed paths, and context budget.
2. Run cheap deterministic and indexed retrieval to establish anchors.
3. Query available CodeIndex, Serena, CodeGraphContext, preprocessor cards, and RAG using the anchors and task intent. Optional backends run with independent budgets and degrade cleanly.
4. Normalize all findings into bounded evidence records with source, path, line range, symbol/relationship metadata, revision, and confidence.
5. Fuse rankings with reciprocal-rank evidence, exact phrase/symbol matches, graph proximity, changed-path relevance, backend agreement, and source diversity.
6. Ask a local model only to rank/label bounded candidate evidence and identify one missing concept; it cannot invent source facts.
7. Perform at most one bounded expansion pass when coverage is low.
8. Select diverse exact snippets under the context budget and return provenance plus quality diagnostics.

The lexical fallback remains available, but receives high-signal phrases/terms, source pathspecs, generated-directory exclusions, global match limits, and a process-tree-safe timeout. It is never the primary relevance engine.

## Compatibility

Legacy string `query` remains accepted. Existing response fields remain intact. New diagnostics and evidence metadata are additive. Explicit low-latency callers may retain fast mode; the default context path uses adaptive retrieval.

## Instruction surface

MCP descriptions, generated agent guidance, `skills/tool-orchestration/SKILL.md`, `AGENTS.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md` will state that `local_ai_repo(action="context")` is the first repository step for new work and that it orchestrates all available retrieval backends before native discovery.

## Acceptance

- Context retrieval uses more than lexical grep when relevant backends are available.
- Serena/CodeGraphContext are not gated by fragile task-word checks.
- Deterministic evidence remains authoritative; local models remain advisory.
- Results are fused, deduplicated, diverse, bounded, and revision-aware.
- Lexical fallback cannot leave an orphan process or capture unbounded output.
- Existing legacy context tests pass; new tests cover orchestration, backend degradation, quality selection, and lexical process bounds.
