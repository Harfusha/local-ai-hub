# T11 rerank relevance reproduction

- Candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub` at `3c7da92aa6a267c2a18af0555d927f0e67d4c476`. Root: `C:\Users\Adam\.local-ai-hub` at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Reported live failure: expected `doc:Credential Rotation Plan`, actual `doc:Cafeteria Menu`; selector `tests/test_t11_rag_ingestion_contract.py::test_t11_live_ollama_rag_ingest_and_reranker_truthfulness`. No current command log or model scores were available.
- Candidate offline set: **71 passed, 2 skipped / 24.36s**. Skips: live Ollama/reranker and 100k benchmark.
- Root-source isolated overlay: **2 passed, 1 skipped / 2.57s**. Root was not written. The skipped selector requires live Ollama/reranker.
- Offline behavior does not reproduce reported inversion. No scoring patch created; changing ranking without RED would be speculative.

## Source pins

- `src/local_ai_hub/rag.py` root `4c0ed5c52ec4cd9d82b41f0d6d2188812d607d1ce58c4ffea956d045fbb9048a`; candidate `db181093f53f0d6666a890413bfea5f52359890ce8236def0160df744cf0c6ff`
- `src/local_ai_hub/reranker.py` root `12773e04a90db8f8a367e618d725a3ea995faf4b624244907b8a13f30ced2ec7`; candidate `ee8b660c9fa261ea34fb63587f8eaaf6119b83b544a4053d22669ef8d9c5c562`
- `tests/test_t11_rag_ingestion_contract.py` root `4876d98a26b9eb26701a841799ba088f3dac3021b842a2b55945f53641306914`; candidate `4876d98a26b9eb26701a841799ba088f3dac3021b842a2b55945f53641306914`
- `tests/test_rag_quality_contract.py` root `4ba233cb1e69c8c42a782021f4d545a6cd1fd4c748104439fa479b473a10c51f`; candidate `81c17571143a4256cf9d9a9017137b82cfd564cd4f45b21e48e5f3fbecba7a3c`

## Performance

- Existing matching-source receipt: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-resume-rag-16k-perf-receipt-20261001.json` SHA-256 `65138497c78525fb9425f607593902d49ad09f9c8bc22f7dc236d26087b01a37`.
- 16,384 synthetic vectors, 384 dimensions, CPU; batch 2048 median 55.722 ms, p95 56.527 ms. Reranker disabled. This is retrieval performance, not reranker throughput.

## Scope

- Root unchanged. `/api/context/pack` untouched. No 100k, GPU, or live-model run.
- No root-current code patch exists because source failure was not reproduced. Exact live command/output and reranker scores remain required for scoring diagnosis.
