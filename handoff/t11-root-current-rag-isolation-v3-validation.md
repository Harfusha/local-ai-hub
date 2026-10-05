# T11 RAG isolation v3 validation

## Scope

- Candidate checkout: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`
- Root-current baseline: `C:\Users\Adam\.local-ai-hub`
- Root was not edited or tested. Patches were applied to fresh temporary copies.
- Local AI Hub was intentionally not used per user instruction.

## v3 fixes

- Require a nonempty exact embedding space for same-workspace reuse.
- Publish unreadable-path suppression before embedding can fail or preempt.
- Retry uncertain paths during full indexing even when metadata matches old snapshot.
- Re-key search cache after runtime embedding identity or dimension changes.
- Exclude uncertain paths in SQL before vector, FTS, and token-overlap limits.

## Validation

- Candidate targeted regressions: `21 passed in 6.70s`.
- Fresh root-copy overlay, applying v3 production and test patches: `31 passed in 7.15s`.
- `git apply --check` for each v3 patch against root: passed.
- Root source and test preimage hashes unchanged after checks:
  - `src/local_ai_hub/rag.py`: `23bee629da1b9f4ba555fe64d031701553118f4cc3b55d8421fdc8d3885626de`
  - `tests/test_rag_hybrid.py`: `fe3d476c2ead5e0c9e5155eb6bedc758e7489b60bbbacbedbe807b87b1a66e1f`
  - `tests/test_rag_fragment_cache.py`: `a20136ff7eb60f7b85e15f0ca3c5afdb50fe6e042d1f0bdea16500d23e5c1623`
  - `tests/test_rag_read_bounds.py`: `6e6ce0f1e93114579f6e2ba16aa3231d806f69506cb4be5e368622b0e6a57e7c`

## Patch hashes

- Production: `afac10c2903ff46613bdcd9e7cc6fb831315e4fa145aa48b7356cf226e2eaa42`
- Tests: `cd2922e6c746eb08d21a99bc96f8cd7e17d044c0951928ce7118f405a025b224`

## Acceptance boundary

These receipts cover focused Python tests and patch applicability in a copied root overlay. Root integration and T20 acceptance remain pending.
