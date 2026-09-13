---
name: ollama-quality-routing
description: Routes bounded local model work through Local AI Hub between the fast and smart model tiers.
---

# Local Model Quality Routing

1. Use `local_ai_status` when model/runtime state is relevant. Never assume a model is available from an old skill or provider-specific MCP schema.
2. Use `local_ai_task(action="reason"|"review"|"delegate"|"second_opinion")` for bounded local generation after deterministic/indexed evidence exists.
3. Default fast/general tier is `qwen2.5-coder:7b`.
4. Use smart tier only for substantial refactors, multi-file review, architecture synthesis, or difficult debugging; current smart model is `qwen3.5:9b`.
5. Embeddings and reranking are Hub-managed. Use `local_ai_repo` and `local_ai_rag`, not direct `ollama_embed` calls.
6. Treat local output as advisory. Verify with repository authority, diagnostics, and real project tests.

Avoid direct `ollama_status`, `ollama_reason`, `ollama_review`, `ollama_generate`, and `ollama_embed` calls: they are not part of the current MCP surface.
