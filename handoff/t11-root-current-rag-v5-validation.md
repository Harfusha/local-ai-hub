# T11 V5 root-current validation

## Baseline and ownership

- Current root: `C:\Users\Adam\.local-ai-hub` (T20-owned).
- Fresh test copy: `C:\Users\Adam\AppData\Local\Temp\t11-v5-root-current-20261001`.
- The initial source pin `494594ba69ce6c18fe2a141b7d43debbc08f32d7151764fd730c3fd11781da25` matched a fresh copy and reproduced P1/P2 failures.
- During this work, root source changed to SHA-256 `4c0ed5c52ec4cd9d82b41f0d6d2188812d607d1ce58c4ffea956d045fbb9048a`. Current root source already contains both uncertainty fixes and the matching regression tests. No root files were edited by T11.
- Current root test pins: `tests/test_rag_hybrid.py` SHA-256 `8119845b5242761efad5811e803c415d2a89523a65d769b9589e15e0175d9200`; `tests/test_rag_read_bounds.py` SHA-256 `9d9f3ee9daad5306570d9a7c2674da1a4cf3342541a1a2b43abb1f798ec0d002`.

## V5 artifact

- Patch: `handoff/t11-root-current-rag-v5-legacy-space-test.patch`
- SHA-256: `f13e2190012edd870c484c9eaa36502f48346f1b97961cdd6d89582d3a0af7e6`
- Patch strengthens the existing cross-workspace legacy test: decode stored vector, assert its expected fresh value, and require exact `space-{mode}` across `index`, `index_step`, and `index_paths_step`.
- A production patch is unnecessary against current root because T20-owned root already contains P1/P2 source fixes. V4 candidate artifact remains unchanged.

## Receipts

- Fresh current-root copy targeted regressions: `3 passed in 1.60s`.
- Fresh current-root copy, `test_rag_read_bounds.py`, `test_rag_fragment_cache.py`, `test_rag_hybrid.py`: `35 passed in 8.61s`.
- V5 patch `git apply --check` against current root: passed with zero errors. Patch was not applied.
- Earlier copy at source pin `494594...`, after V5 source fixes: `114 passed, 4 failed, 3 skipped` across eleven scoped suites. Failures were four `test_rag_quality_contract.py` cases. They were outside changed source lines; no baseline isolation was completed, so no cause is claimed.
- No live Ollama, GPU, or 100k benchmark ran. Local AI Hub ignored.

## Acceptance boundary

Root's current P1/P2 code and regression tests are present under T20 ownership. V5 contributes a small legacy-vector test delta. T20 integration receipts and full end-to-end acceptance remain outstanding.
