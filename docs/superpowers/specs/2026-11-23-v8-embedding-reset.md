# Version 8 embedding reset

## Requirement

Keep the Hub online when an RAG index fingerprint differs. Do not compare vectors across embedding spaces. Use the configured Harfusha embedding model as the fixed model. Clear existing stored vectors now and ship an idempotent version 8.0 migration that clears vectors created before the reset.

## Approaches

- Rewrite the database fingerprint only: rejected because it can hide incompatible vector data.
- Replace the whole RAG database: rejected because it discards source text, file ownership, and index metadata that can be preserved.
- Clear vector values and embedding caches while preserving source records; rely on per-workspace embedding-space checks and lexical fallback: selected.

## Data behavior

- Clear vectors from RAG chunks, content-RAG cache, semantic cache, embedding cache, and agent-memory embeddings.
- Preserve RAG chunk text, file hashes, workspace ownership, agent-memory records, and non-embedding cache entries.
- Clear stale workspace embedding-space/reindex metadata. Mark the reset as applied.
- On startup, treat a fingerprint mismatch as degraded RAG state, not a Hub startup failure. RAG retrieval must continue to filter by embedding space and use lexical fallback for stale or unresolved spaces.
- When a reset marker proves all persisted vectors were cleared, adopt the active fingerprint without re-embedding.
- Version 8.0 updater migration must be offline, idempotent, backup-protected, and scoped to the affected SQLite stores. It must not run from the 7.x updater path or require a full-state staging copy.

## Acceptance

- A structurally valid database with a stale global fingerprint does not stop `LocalAIApp` startup.
- Per-workspace retrieval never mixes embedding spaces and marks stale workspaces for reindex/fallback.
- Migration removes all stored vectors from every current embedding store while preserving non-vector records and text.
- Backup and rollback restore affected databases and sidecars without replacing unrelated state.
- Migration can run twice safely. Startup after immediate cleanup uses the fixed model fingerprint.
