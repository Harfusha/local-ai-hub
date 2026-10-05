# T11 root-current offline end-to-end

- Root `C:\Users\Adam\.local-ai-hub` at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Candidate f678 at `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- Current root source/tests copied into isolated overlay. Root stayed unchanged during final test run.

## Validation

- Command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_quality_contract.py tests/test_t11_rag_ingestion_contract.py tests/test_rag_hybrid.py tests/test_rag_read_bounds.py tests/test_t11_project_policy_consumers.py tests/test_rag_fragment_cache.py tests/test_rag_dedup.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py`
- Result: **128 passed, 3 skipped in 33.46s**.
- Skips: live Ollama/reranker, bounded retrieval benchmark, synthetic RAG batch/seed benchmark.
- Fixture patch already integrated: strict reverse apply-check passed.

## Scope

- No production source or `/api/context/pack` edits. No live model, GPU, 100k benchmark.
- An earlier pytest launch used root as CWD by mistake and was interrupted after 38 progress dots; final receipt above ran from the isolated overlay. Root hashes/status were checked afterward.
