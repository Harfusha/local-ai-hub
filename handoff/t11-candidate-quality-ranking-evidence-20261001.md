# T11 candidate retrieval quality evidence

- Candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`
- Scope: deterministic local SQLite store, fixed vector fixture, no external model calls.
- Existing golden test: `tests/test_rag_quality_contract.py::test_golden_corpus_keeps_relevant_credentials_above_realistic_distractors`.
- Golden corpus: six source-grounded credential documents and 58 unrelated distractors. Test requires the credential rotation runbook first, Recall@10 = 1.0, and nDCG@10 = 1.0 for baseline and candidate indexes.
- Existing lexical/vector test: `tests/test_rag_hybrid.py::test_hybrid_rag_search_combines_fts_and_vector`.
- Exact command: `python -m pytest -q --tb=short tests/test_rag_quality_contract.py::test_golden_corpus_keeps_relevant_credentials_above_realistic_distractors tests/test_rag_hybrid.py::test_hybrid_rag_search_combines_fts_and_vector`
- Exact result: `.. [100%]`; `2 passed in 0.64s`.
- No new test or production code added. No 100k, GPU, or live Ollama validation ran.

This is candidate-only retrieval quality evidence. It does not replace T20 integration receipts or full end-to-end acceptance.
