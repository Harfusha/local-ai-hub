# Cross-worktree content identity fast path

## Goal

Make creation and first preprocessing of a new Git worktree scale with modified and untracked files, instead of rereading or rehashing the whole checkout.

## Design

The canonical per-file identity remains the existing content hash (`git:<blob-id>` for clean tracked files and SHA-256 for dirty or untracked files). Add a per-root hash-run cache for the complete Git index/blob map. The cache is loaded once for a preprocessing hash phase and reused by all batches; it is invalidated when the phase, root generation, or Git index/status identity changes.

During inventory, clean tracked paths may be seeded directly with their Git blob IDs and `needs_hash=0`. Dirty and untracked paths remain pending and are byte-hashed. After seeding, cross-worktree content-card, deterministic-blob, lexical-source, and CodeIndex caches are reused by the existing content-addressed lookup paths. RAG path rows remain local to each worktree, while embeddings/content data remain reusable by content identity.

Reuse the existing directory-level metadata signatures in `repo_state.py` for repeated untracked/degraded fingerprint scans. A directory signature is never treated as canonical content identity. Watcher-confirmed changes use the existing path-incremental inventory; watcher overflow, force refresh, or missing signatures fall back to the existing bounded full inventory. No duplicate persistent directory table is needed for the new-worktree fast path, because a new worktree must still materialize its path rows.

## Correctness

- File hashes remain authoritative for dirty and untracked content.
- Git blob IDs are used only for paths proven clean by Git status/index data.
- Directory signatures contain sorted relative entries and metadata; they only skip work when unchanged, never manufacture a content hash.
- New worktrees still materialize their own path-scoped rows and RAG chunks.

## Scope

Touch `repo_tools.py` for one-shot Git blob-map reuse, `preprocess.py` for hash-run lifecycle and clean-path seeding, and focused regression/performance tests. Do not change public MCP schemas or cache key formats.

## Verification

Tests must prove: one Git map load serves multiple hash batches; clean new worktree paths do not call byte hashing; dirty/untracked paths still do; existing cross-worktree cache linking remains correct; watcher/path changes preserve incremental behavior.
