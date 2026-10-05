# T11 exact-space v1 validation addendum

Supplement to `t11-embedding-space-root-current-v1.md`. Immutable patches remain unchanged.

Root preimages rechecked after overlay validation:
- `src/local_ai_hub/rag.py`: `23BEE629DA1B9F4BA555FE64D031701553118F4CC3B55D8421FDC8D3885626DE`
- `tests/test_rag_hybrid.py`: `FE3D476C2EAD5E0C9E5155EB6BEDC758E7489B60BBBACBEDBE807B87B1A66E1F`

Overlay: `C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001`.

Fail-first on copied root source, before production delta:
```powershell
$env:PYTHONPATH='C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\src'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q -p no:cacheprovider --tb=short C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\tests\test_rag_hybrid.py::test_search_uses_only_exact_embedding_space_and_reports_stale_rows C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\tests\test_rag_hybrid.py::test_search_reports_mismatch_when_only_foreign_or_empty_space_rows_exist
```
Result: **2 failed**. First returned foreign and empty-legacy vectors; second returned foreign vectors.

After production patch on copied source, with final tenant/workspace/path and FTS assertions:
```powershell
$env:PYTHONPATH='C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\src'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q -p no:cacheprovider --tb=short C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\tests\test_rag_hybrid.py::test_search_uses_only_exact_embedding_space_and_reports_stale_rows C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\tests\test_rag_hybrid.py::test_search_reports_mismatch_when_only_foreign_or_empty_space_rows_exist C:\Users\Adam\AppData\Local\Temp\codex-t11-space-v1-root-overlay-20261001\tests\test_rag_hybrid.py::test_search_keeps_fts_fallback_labeled_when_query_embedding_fails
```
Result: **3 passed in 14.43s**.

Both immutable root-current patches passed `git apply --check`. No root test or patch application occurred.
