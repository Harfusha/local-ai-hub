# T11 root-current RAG isolation v2

Combined replacement for earlier T11 v1 root patches. Keep v1 artifacts unchanged. Apply this v2 production/test pair together; do not combine it with v1 patches. Root files remain T20-owned. No root test, patch application, or write occurred.

## Immutable pair and root preimages

- Production: `t11-root-current-rag-isolation-v2-production.patch`
  SHA-256 `63F5091DDEE654F365782A7E2DBB23C8E77CCFD26ADB547F617AB48DE48832A7`
- Tests: `t11-root-current-rag-isolation-v2-tests.patch`
  SHA-256 `3637C2ECA2525D5E0854F70CF2E7FACF17C6F7C1E3623962FCA250816539025C`

Root preimages captured at `C:\Users\Adam\.local-ai-hub`:
- `src/local_ai_hub/rag.py`: `23BEE629DA1B9F4BA555FE64D031701553118F4CC3B55D8421FDC8D3885626DE`
- `tests/test_rag_hybrid.py`: `FE3D476C2EAD5E0C9E5155EB6BEDC758E7489B60BBBACBEDBE807B87B1A66E1F`
- `tests/test_rag_fragment_cache.py`: `A20136FF7EB60F7B85E15F0CA3C5AFDB50FE6E042D1F0BDEA16500D23E5C1623`
- `tests/test_rag_read_bounds.py`: `6E6CE0F1E93114579F6E2BA16AA3231D806F69506CB4BE5E368622B0E6A57E7C`

Both root `git apply --check` commands returned exit 0. Patches touch `rag.py` and three targeted test files only.

## Fixes

- Search cache/coalescing key includes tenant, configured/effective scope, embedding space, configured/active dimension, index revision and generation. Unknown runtime identity bypasses cache; lexical fallback entries are evicted.
- Vector, hybrid FTS and known-space lexical candidates require exact non-empty embedding space. Foreign and legacy rows report rebuild/mismatch state.
- Cross-workspace reuse requires exact non-empty embedding space in full, stepped and path indexing. Empty/NULL legacy vectors re-embed.
- Missing query embeddings use explicit degraded lexical-only mode, labeled `retrieval_mode=lexical_fallback` and backend `fts5` or `token_overlap`.
- Read uncertainty preserves committed snapshot, suppresses uncertain paths and invalidates generation/cache results.

## Validation receipts

Candidate T11 checkout:
- Four fail-first regressions reproduced tenant cache collision, dimension cache hit, mixed-space FTS results and unlabeled lexical fallback.
- Final targeted selector batch: **13 passed in 2.36s**. Includes exact vector isolation, runtime space/dimension cache changes, hybrid FTS, both legacy reuse tests, read uncertainty cache race and policy invalidation.

Root-current copied overlay:
`C:\Users\Adam\AppData\Local\Temp\codex-t11-v2-patch-apply-overlay-20261001`
- Copied root preimages, applied both v2 patches sequentially, then ran exact-space/cache/FTS/legacy/read-uncertainty selectors: **9 passed in 24.27s**.
- A separate earlier root-copy overlay also returned **9 passed in 25.94s**.
- No GPU, model, 100k benchmark, Local AI Hub or root tests used.

T20 can now integrate this single combined patch pair and record fresh root receipts. Do not mark root acceptance complete from overlay evidence alone.
