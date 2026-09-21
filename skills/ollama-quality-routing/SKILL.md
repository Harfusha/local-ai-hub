---
name: ollama-quality-routing
description: Routes bounded local model work through Local AI Hub between the fast and smart model tiers.
---

# Local Model Quality Routing

1. Use `local_ai_status` when model/runtime state is relevant. Never assume a model is available from an old skill or provider-specific MCP schema.
2. Use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression after any needed evidence exists.
3. Reserve the configured background model for preprocessing. Use the configured fast tier only for quick/simple requests, the general tier for ordinary tasks, the heavier tier for more involved work, and the configured reasoning tier for the hardest cases. Use indexed and deterministic Hub actions for exact facts, symbols, diff and tests; they do not replace semantic local-model work.
4. Read active model roles from this machine's Local AI Hub configuration; do not assume another computer uses the same model tags or backend. Check availability with `local_ai_status` and use only the configured, already-running local backend (llama.cpp when hardware/profile-gated; Ollama only after explicit opt-in).
5. Embeddings and reranking are Hub-managed. Use `local_ai_repo` and `local_ai_rag`, not direct `ollama_embed` calls.
6. Treat local output as advisory. Verify with repository authority, diagnostics, and real project tests.

Avoid direct `ollama_status`, `ollama_reason`, `ollama_review`, `ollama_generate`, and `ollama_embed` calls: they are not part of the current MCP surface.
