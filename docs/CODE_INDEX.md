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
first, then the oldest files. Parse blobs share this database; eviction removes
only blobs no indexed file references, preserving shared parse-cache entries.

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

`python tools/cleanup_code_index.py --dry-run` opens the existing database in
SQLite read-only/query-only mode and skips schema initialization. It can measure
while the Hub is online; `hub_online` reports whether that state was confirmed.
The dry-run holds a read snapshot and reports orphan-trigram candidates,
protected roots, and stale file rows whose source paths no longer exist. Stale
file scans are bounded by `--max-roots` and `--max-paths-per-root` (20,000 by
default); oversized roots are skipped and reported. Active Git roots stay
protected. When more roots remain, `next_stale_root` is a keyset cursor for the
next bounded run; pass it with `--after-root`. Dry-run output shows at most 20
stale path examples per root. `--apply` still requires the Hub to be confirmed
offline. Apply deletes bounded orphan trigram rows and derived rows for missing
source files; it preserves shared parse blobs and never removes roots or source
files. The report separates logical source bytes from SQLite physical bytes
and reusable pages. Use `--compact` only for a confirmed-offline apply when
returning pages to the filesystem is needed.

Live dry-run on 2026-11-05 (`--max-rows 1000 --max-roots 16`) found 6,904 orphan
trigram rows, but zero eligible rows across three scanned roots: all three roots
were active Git roots and stayed protected. It reported 317,538,408 physical
bytes before and after, zero reusable pages, and zero bytes released. This is a
live-install measurement, not a cleanup or compaction run.

This cap covers the code-index database only. RAG, deterministic facts and
preprocessing metadata have separate lifecycles.

Admission is checked before each new single-file or batch write. The writer
reserves conservative space for parse payloads, symbols, references, edges, and
SQLite indexes. Near the cap, one bounded eviction pass runs before the write.
Current and other running preprocessing roots are protected; if their active
root snapshot is unavailable, eviction is refused. If the database still cannot
fit the estimate, the write is deferred and reports `budget_limited=true` with
`coverage_complete=false`. Removed source files are still pruned. The project
waits five minutes before retrying, so it does not spin while the cap is full.

Preprocessing status exposes the actual `code_index_files` count and marks its
coverage as incomplete by contract. A completed preprocessing project therefore
does not imply complete code-index coverage. Search continues to verify indexed
candidates against current source and falls back to source search when coverage
is partial or a candidate is stale.
