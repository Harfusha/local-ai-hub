---
name: ollama-quality-routing
description: Routes bounded local model work through Local AI Hub between fast and smart model tiers.
---

# Local Model Quality Routing

1. Check model/runtime state: call `local_ai_status`. Never assume availability from stale skills/schemas.
2. Semantic generation/review: use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` after required evidence exists.
3. Tiering: background model = preprocessing; fast tier = quick/simple; general tier = ordinary; heavy tier = involved; reasoning tier = hardest cases. Deterministic/indexed Hub actions = exact facts/symbols/diffs/tests (authoritative).
4. Config authority: read model roles from local config. Endpoint must be healthy local backend (llama.cpp or Ollama).
5. Embeddings/reranking: Hub-managed via `local_ai_repo` / `local_ai_rag`. No direct `ollama_embed`.
6. Output advisory: verify with repo authority, diagnostics, real tests.

Forbidden (not in MCP surface): direct `ollama_status`, `ollama_reason`, `ollama_review`, `ollama_generate`, `ollama_embed`.
