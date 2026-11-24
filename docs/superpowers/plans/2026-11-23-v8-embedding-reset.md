# V8 embedding reset implementation plan

## Scope

Keep the configured Harfusha embedding model unchanged. Remove all persisted vector payloads from the current state while preserving source records and unrelated cache entries. Keep a stale global RAG fingerprint from preventing Hub startup; rely on per-workspace embedding-space validation and lexical fallback. Ship the persistent cleanup as an offline, idempotent state migration applied by app release 8.0.0.

## Steps

1. [x] Add schema-aware, repeat-safe cleanup for RAG, content-RAG, embedding cache, semantic cache, and agent-memory vectors. Write the completion marker only after verification.
2. [x] Let structurally valid stale RAG fingerprints start in degraded mode. Adopt the active fingerprint only after the reset marker and empty-vector checks.
3. [x] Add the data migration to the 8.0.0 updater path, gated away from 7.x. Back up only affected SQLite stores with rollback support.
4. [x] Add regressions for preserved data, idempotence, scoped restore, stale-fingerprint startup, fingerprint adoption, and release gating.
5. [x] Run targeted tests and release checks; clear the live state and verify every vector store. Remove task-created snapshots after verification because they contained the embeddings the user asked to delete.

## Acceptance

- No existing stored embedding vectors remain in any discovered persistent store after immediate cleanup.
- Non-vector RAG text, ownership, agent-memory records, and non-embedding cache entries are preserved.
- Same configured embedding model remains selected.
- A structurally valid fingerprint mismatch no longer blocks service startup; cross-space comparisons remain prohibited.
- Release 7.x does not apply the 8.0 migration; release 8.0 applies it once and safely rolls back on failure.
- Targeted regressions and repository checks pass on the working checkout.

## Results — 2026-11-24

- Live state migration succeeded. Counts: `chunks` 31,719 with 0 vectors; `content_rag_chunks` 519,382 with 0 vectors; embedding cache 0 rows (1,479 unrelated cache rows remain); semantic cache 11 rows with 0 vectors; agent-memory embeddings 0 rows and 117 memory records remain. `verify_embedding_reset` returned true.
- `PRAGMA quick_check` returned `ok` for `rag.sqlite3`, `cache.sqlite`, `semantic-cache.sqlite3`, and `agent_state.sqlite`. Hub ports 11435/11436 remained closed and `state/service.disabled` remained present. Ollama and model training were not stopped.
- `.venv\\Scripts\\python.exe -m pytest --no-cache -q tests/test_embedding_reset_v8.py tests/test_update_install.py` → 12 passed. `compileall`, `release_check.py --allow-installed`, and `git diff --check` passed. Two malformed literal `\\n` suffixes in existing Laya tests were fixed so compileall could complete.
- Configured embedding model stayed `Harfusha/local-ai-hub-bge-small-en-v1-5-code`, revision `7bdcdf89c776fadc557b189c42b754d89d7832d1`; no model or config route was changed. Config loading still reports the separate unsupported `laya.mode` value, so live Hub restart/acceptance remains open.
- Scoped snapshots were removed after all four DB checks passed, per the request to remove the old embeddings. No reset backup remains.
