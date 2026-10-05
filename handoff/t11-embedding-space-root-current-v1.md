# T11 exact embedding-space isolation — root-current v1

Created 2026-10-01 from the verified T20 root preimages. Root source and tests were not modified or run. Changes belong to T11; T20 remains root integrator.

## Immutable patches and preimages

- Production patch: `t11-root-current-embedding-space-v1-production.patch`
  SHA-256 `5631CC11281F207EB70B244AEF7468EF5867257FE8736E0F1C9FE9623C41B636`
  Root `src/local_ai_hub/rag.py` preimage SHA-256 `23BEE629DA1B9F4BA555FE64D031701553118F4CC3B55D8421FDC8D3885626DE`.
- Test patch: `t11-root-current-embedding-space-v1-tests.patch`
  SHA-256 `4FBBE2D81DA5CC58C457A050370319747923016342714D5B440F3CE186DEE62E`
  Root `tests/test_rag_hybrid.py` preimage SHA-256 `FE3D476C2EAD5E0C9E5155EB6BEDC758E7489B60BBBACBEDBE807B87B1A66E1F`.

Both `git -C C:\Users\Adam\.local-ai-hub apply --check <patch>` commands returned exit 0. Checks did not modify root.

## Root-copied overlay evidence

Overlay: `C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001`.

Fail-first against copied root source, before production patch: two exact-space selectors failed. Vector search returned `foreign.py` and `legacy.py`; stale-only query returned foreign vectors.

After applying production delta only to overlay, command below returned **3 passed in 14.43s**:

```powershell
$env:PYTHONPATH='C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\src'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q -p no:cacheprovider --tb=short <three test selectors in tests/test_rag_hybrid.py>
```

Coverage: current query space excludes foreign and empty legacy vectors; foreign-only and empty-only rows return no vector result and report `embedding_space_mismatch`; tenant scope, workspace, and `scope_path` remain enforced; unavailable query embeddings retain degraded `bm25_fts` labeling for lexical fallback.

## Delta and limits

Vector batches now require exact query `embedding_space`, retaining tenant/workspace and optional path predicates. Foreign or legacy rows set `embedding_space_rebuild_pending`; no exact-space rows return degraded `embedding_space_mismatch` with `reindex_required`. FTS remains a labeled lexical fallback, not a claim that foreign vectors matched.

No root test, apply, or write occurred. No Local AI Hub, GPU, model, or 100k benchmark was used. Root integration and receipts remain T20-owned.
