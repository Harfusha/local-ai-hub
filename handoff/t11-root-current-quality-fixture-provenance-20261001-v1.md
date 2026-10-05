# T11 root-current quality fixture provenance

- Root `C:\Users\Adam\.local-ai-hub` at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Candidate f678 at `3c7da92aa6a267c2a18af0555d927f0e67d4c476`. Root unchanged.
- RCA: exact-space isolation excludes fixture vectors without `embedding_space`. Cursor-close assertion did not reach scoring because no vector row survived. Root code closes cursor before scoring.
- Fixture repair adds matching `quality-space` metadata and commit forwarding. Assertions stay unchanged.

## RED before repair

- Root source + root tests: **69 passed, 4 failed, 2 skipped in 36.00s**.
- Failures: expected `[2,3,1]` but got empty; overflow result empty; tie results empty; cursor flag false because no row reached dot scoring.

## GREEN after repair

- Four selectors with root source: **4 passed in 0.45s**.
- Same selectors with candidate source: **4 passed in 0.56s**.
- Full root-source offline acceptance: **73 passed, 2 skipped in 20.00s**. Live reranker and benchmark skipped.

## Root-current patch

- [Patch](t11-root-current-quality-fixture-provenance-20261001-v1.patch), SHA-256 `f6a232af6dea372f601ab88f7aff9c3772cce352fdaf5bd3598e84b585a7651e`.
- Root preimage `tests/test_rag_quality_contract.py` SHA-256 `4ba233cb1e69c8c42a782021f4d545a6cd1fd4c748104439fa479b473a10c51f`.
- Strict root `git apply --check --whitespace=error`: passed. Patch remains unapplied and read-only.
- Patch changes fixture metadata and wrapper forwarding only. No assertions changed.

## Scope

- No root writes, production source changes, `/api/context/pack`, live model, GPU, or 100k benchmark.
