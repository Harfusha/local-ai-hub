# Code-index budget and coverage

The built-in code index is intentionally partial. Preprocessing admits files that
the Hub has actually served as evidence, plus one level of eligible local Python
imports. It does not claim whole-project symbol coverage. Search responses must
keep their coverage and freshness fields visible and use source-based fallback
when the requested file is not indexed.

Direct deterministic affected-test queries may open the existing code index, but
they never admit every project file as a side effect. Only preprocessing admits
files from actual Hub evidence use. An absent or partial dependency graph keeps
`selection_complete=false`; heuristic test matches remain a fallback.

`[code_index].max_index_bytes` sets the shared code-index SQLite budget. The
default is 536,870,912 bytes (512 MiB), including the database and its WAL/SHM
sidecars. When over budget, preprocessing evicts the lowest recorded-use files
first, then the oldest files. Shared parser blobs are stored separately and are
not deleted by code-index eviction.

Eviction removes derived rows in one bounded transaction and invalidates query
generations. Small databases use a five-second bounded `VACUUM`; larger databases
use up to 65,536 incremental pages per preprocessing pass when incremental
auto-vacuum is enabled. Startup skips the one-time full-database conversion when
the database already exceeds its configured budget. Such a legacy database may
need a scheduled maintenance window before SQLite can return all freed space to
the filesystem.

`CodeIndex.enforce_size_limit(dry_run=True)` reports candidate paths and an
estimate without changing the database. The normal result reports before/after
page counts and physical bytes; `within_budget` is false when a bounded pass
could not release enough space. Existing SQLite free pages count toward the
reclaim estimate before live files are selected for eviction, so reusable pages
alone do not evict indexed files. A later preprocessing pass can continue cleanup.

This cap covers the code-index database only. RAG, deterministic facts,
preprocessing metadata, and shared parse-cache storage have separate lifecycles.
