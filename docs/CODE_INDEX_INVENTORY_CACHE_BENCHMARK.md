# Code-index inventory cache

`ProjectPreprocessor._step_code_index` validates the current `file_refs` inventory before selecting demand-seeded files and their direct local dependencies. When a large project needs several bounded batches, rebuilding that same allowed-path map on every batch repeats path-policy and filesystem checks.

The preprocessor now reuses the map for the same repository root, preprocessing generation, `file_refs` revision, and project settings. Inserts, deletes, path, content-hash, size, mtime, and `needs_hash` changes advance the revision. A different generation or settings object invalidates the cache and reruns pruning, so changed path permissions remove newly disallowed rows. The cache holds at most four roots and skips inventories larger than 50,000 allowed paths. If revision tracking is unavailable, indexing falls back to the uncached full scan.

The code-index still grows from files actually served as evidence and their direct one-hop dependencies. Existing root and path-policy checks, pruning, batch size, and freshness checks remain in the indexing path.

## Synthetic benchmark

Run from the repository root:

```powershell
.venv\Scripts\python.exe tools\benchmark_code_index_inventory_cache.py --files 5000 --demand-files 32 --repeats 3
```

Measured on 2026-11-06 with a synthetic 5,000-file inventory and 32 demanded files:

| Mode | Path-policy checks | Median total | p95 total |
|---|---:|---:|---:|
| Full inventory scan each step | 165,000 | 1,389.440 ms | 1,432.463 ms |
| Revision cache | 5,000 | 723.321 ms | 735.247 ms |

This run reduced path-policy checks by 96.97% and median total time by 47.94%. It used a warm local OS cache, synthetic files, and an in-memory code-index writer. It does not establish cold-cache performance, real-repository speed, or live-service impact.

### Repeat run — 2026-11-06

Re-ran the same command in the current checkout. Full rescan median was 1,459.787 ms; revision-cache median was 801.831 ms, a 45.07% reduction. p95 totals were 1,526.102 ms and 997.179 ms. Path-policy checks stayed at 165,000 versus 5,000 (96.97% reduction). All six samples indexed 32/32 demanded files. This confirms the synthetic result on this run only; warm-cache and synthetic limitations above still apply.

### Repeat run — 2026-11-06

Re-ran the same command after source-revision pruning changes. Full rescan median was 1,577.401 ms; revision-cache median was 849.409 ms, a 46.15% reduction. p95 totals were 1,603.196 ms and 919.391 ms. Path-policy checks stayed at 165,000 versus 5,000 (96.97% reduction). All six samples indexed 32/32 demanded files. Results remain synthetic and warm-cache only.
