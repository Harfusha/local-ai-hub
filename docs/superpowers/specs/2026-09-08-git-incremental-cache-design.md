# Git-Aware Incremental Repository Cache

## Goal

Use Git as the primary change detector for Git repositories so Local AI Hub hashes and reprocesses only modified or untracked files, while preserving correctness for worktrees, filters, submodules, sparse checkout, LFS, symlinks, and Git failures.

## Scope

The change affects repository inventory, file hashing, preprocessing invalidation, and content-derived cache reuse. It does not change the public MCP tool surface or automatically mutate repository Git configuration.

## Design

### Git snapshot

`RepositoryTools` will collect one bounded, cacheable snapshot per repository generation containing:

- repository common directory and worktree root;
- worktree-specific Git directory and index path/signature;
- `HEAD` and tree identity when available;
- porcelain-v2 status for modified, staged, deleted, renamed, and untracked paths;
- index blob OIDs for tracked paths;
- conservative indicators for submodules, sparse checkout, LFS, filters, and symlinks.

Git commands remain bounded. A timeout, non-zero exit, malformed output, or unavailable Git returns a degraded result and uses the existing filesystem fallback.

### Hash and reuse policy

- Clean tracked paths reuse the Git blob OID and prior derived records without reading file contents.
- Tracked paths differing between index and worktree are raw-hashed once from the working tree.
- Staged-only paths use index metadata only when the working-tree copy is also unchanged.
- Untracked paths are enumerated through Git and raw-hashed once; a stat/file-identity fast path reuses a prior hash only when metadata is unambiguous.
- Deleted paths invalidate all path-local derived records.
- Renames preserve content reuse when the source and destination content identity match.
- Ignored paths remain excluded from repository inventory.

Git blob OIDs are internal content identities. Existing APIs that require raw SHA-256 continue using raw SHA-256.

### Worktrees and shared caches

Worktree/index identity is part of repository-state fingerprints. Content-derived records may be shared by blob OID plus relative path and analyzer/config version. Project-derived records additionally require matching repository configuration, import context, ignore rules, and analyzer versions.

The implementation detects existing Git fsmonitor/untracked-cache support but does not enable or modify either setting automatically.

### Safety

The implementation is conservative for symlinks, submodules, sparse checkout, LFS/filter-managed paths, `assume-unchanged`, and `skip-worktree`. Ambiguous paths are rehashed or invalidated rather than reused. Non-Git repositories retain current filesystem behavior.

### Observability

Internal metadata-only counters will expose Git snapshots, skipped hashes, computed hashes, blob/tree reuse, and Git fallbacks. No prompts, source text, or file contents enter telemetry.

## Testing

Tests will cover clean tracked paths, modified/staged/untracked/deleted/renamed paths, worktree sharing and index divergence, Git timeout/malformed output fallback, special Git modes, fsmonitor/untracked-cache detection, and unchanged behavior for non-Git repositories.

## Compatibility

No public MCP schema change. Existing cache entries remain readable; new Git identities are additive and disposable with derived SQLite state.
