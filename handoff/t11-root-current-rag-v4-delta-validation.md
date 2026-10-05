# T11 V4 delta validation

## Pins

- Candidate root: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`
- Candidate HEAD: `3c7da92aa6a267c2a18af0555d927f0e67d4c476`
- V3 pin manifest: `handoff/t11-pin-manifest-v3.json`
- V3 pin manifest SHA-256: `8a75decba5eea8840a829ff943601d9c1d276c8062ab2e3c33bee79ac60990e2`
- V4 delta: `handoff/t11-root-current-rag-midread-preemption-v1-delta.patch`
- V4 delta SHA-256: `9442d24111600f8219716aa2a9f13ee1b4a96aacf02c78bc79eeba5fb11cb4b2`
- T21 source: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\src\local_ai_hub\project_config.py`
- T21 source and T11 candidate SHA-256: `f51cd2bd05ac993139c388ca553ff816c4b39d572182afd433e3fa7430a766d5`

## Delta

- Publish accumulated read uncertainty before incremental path preemption returns.
- Retry read-uncertain paths from `index_step` even when mtime and size match prior snapshot.
- Strengthen changed-embedding-space assertions across `index`, `index_paths_step`, and `index_step`; decode and compare fresh vector.
- Integrate the approved T21 `project_config.py` into this T11 candidate. T21 checkout remains unchanged.

## Receipts

- Fail-first confirmed both RAG defects: preempted unreadable path remained visible; incremental index reported zero processed files after same-metadata recovery.
- The first combined run also exposed a malformed test-side `dict` conversion. Corrected the test; the strengthened three-entrypoint embedding-space test passed.
- Corrected fail-first regressions after source changes: `3 passed in 1.65s`.
- RAG read bounds, fragment cache, and hybrid search: `52 passed in 16.08s`.
- T11 policy consumers, ingestion contract, and seed integrity: `63 passed, 2 skipped in 22.98s`. Skips require live Ollama and opt-in benchmark.
- Reranker cache identity, embedding cache/batch deduplication, RAG quality contract, and near-duplicate handling: `53 passed, 1 skipped in 4.96s`. Skip requires the excluded 100k benchmark.
- V4 delta applies cleanly to the preserved V3 snapshot: `git apply --check` passed.
- Tracked-source `git diff --check` passed. New test file contains no trailing whitespace.
- V3 production, test, and validation artifact hashes still match V3 manifest.
- Local AI Hub was ignored. No GPU or 100k benchmark ran. T02 test slot was released before validation.

## Acceptance boundary

Candidate-only targeted Python acceptance is green. Full end-to-end acceptance remains incomplete until T20 integrates pinned patches and records valid integration receipts. Live Ollama and 100k measurements remain unverified and out of this bounded pass.
