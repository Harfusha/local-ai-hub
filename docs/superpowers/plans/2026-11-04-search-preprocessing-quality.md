# Search and Preprocessing Quality Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan. Preserve existing work in the checkout.

**Goal:** Measure and improve repository search quality and latency, and preprocessing usefulness, without weakening coverage or freshness guarantees.

**Architecture:** Add a reproducible, labeled fixture with positive, negative, lexical and ranking cases. Measure exact search and explicitly identify the measurement boundary; separately examine preprocessing scheduling and safe index reuse. Optimize only evidenced bottlenecks and verify behavior against the labeled corpus and existing safety tests.

**Tech Stack:** Python, pytest, existing RepositoryTools and preprocessing APIs.

## Expanded objective: agent retrieval and index lifecycle

- [ ] Replace automatic whole-project code-indexing with demand-based indexing
  of used paths plus verified one-hop neighbors; inspect every indexing entry
  point, preserve partial-coverage signaling, fallback and access policy.
- [ ] Add a configurable storage bound, usage/age eviction, atomic bounded
  cleanup and honest SQLite logical versus physical space measurements;
  preserve shared parse cache and active roots.
- [ ] Measure and test incremental admission, one-hop limits, eviction,
  concurrent changes/removals, cache invalidation and real installation impact.

Current implementation checkpoint: HTTP/MCP search exposes `lexical`, `rag`,
and `hybrid`. RAG is semantic-only; hybrid fuses bounded lexical and semantic
candidates by file with RRF and keeps counts approximate. Semantic candidates
are checked against current authorized source files. Czech semantic queries
now append bounded English equivalents for common terms; exact lexical
matching retains the original query and responses report
`query_expansion_applied`. Existing RAG indexes still need a versioned,
bounded reindex to benefit from source/chunking changes.

Runtime measurement: the active Hub reported high profile but CPU-only Torch
in its own environment. A cached BGE reranker on CPU took 8.8–23.4 seconds
on three small candidate sets. A Czech installation target was absent from
the candidates, which reranking alone cannot repair. The `local_reranking`
setting was enabled in the ignored active configuration file, but the running
service was not restarted and the setting is not yet active.

Read-only index inventory: `code-index.sqlite3` was 34,586,996,736 bytes with
456,577 free 4096-byte pages at measurement time. The empty, unregistered
`f36f/.local-ai-hub` root had 1,663 indexed files and 2,618,593 trigram rows.
Full table-size analysis exceeded the bounded read-only scan; its contribution
to physical size is not yet established. No index data or worktree was removed.

- [ ] Inventory the current service/configuration, installed model and device readiness, worktrees, and code-index storage without mutating index state; never modify P23.
- [ ] Specify and implement explicit `lexical`, `rag`, and `hybrid` search modes across HTTP, MCP and client contracts, with scoped and truthful freshness, coverage, reranker and degradation metadata. Preserve exact lexical pagination and define stable semantic pagination.
- [ ] Evaluate existing RAG chunking, metadata, English/Czech natural-language retrieval, indexing freshness and removals; improve measured problems while keeping source/root/worktree authorization.
- [ ] Validate the requested high profile and installed reranker without downloading models; measure quality, latency, VRAM and degradation with and without reranking; activate safely and verify the running service.
- [ ] Design bounded, idempotent, interruption-safe derived code-index cleanup with dry-run and measured reclaimability, preserving active roots and shared parse cache.
- [ ] Extend judged benchmarks and run regression/integration and actual HTTP/MCP checks; synchronize both canonical prompts and document evidence boundaries.

- [x] Create a deterministic fixture and labeled queries for literal punctuation, identifiers, ranking and absent terms. Report per-query recall, reciprocal rank and latency distribution.
- [x] Run a baseline, identify failure cases and bottlenecks, then add regression tests before fixes.
- [x] Extend evaluation with changed files, real repository symbol judgments and a separate synthetic holdout suite.
- [x] Use existing learned query demand to prioritize bounded RAG and file-card work while reserving regular batch slots.
- [ ] Validate demand priority under live preprocessing load, disabled and failing optional backends, concurrent changes, and sustained workloads.
- [x] Measure isolated loopback HTTP search with cold and warm cache; test immediate modification through the HTTP endpoint.
- [ ] Measure MCP and live preprocessing workloads; complete broader regression checks.

## Initial evidence (2026-11-04)

`python tools/benchmark_search_quality.py --repeats 5 --noise-files 100 --mode service` measures an isolated `LocalAIServices.repo_search`, with caching and optional backends disabled. The eight-case synthetic suite has seven positive queries. On this fixture, engine reciprocal rank improved from 0.929 to 1.000 after file-level term coverage; service reciprocal rank improved from 0.886 to 1.000 after retaining the punctuation in `C++`. Recall@10 remained 1.000. These are development cases used to design the fixes, not independent estimates of production relevance.

`python tools/benchmark_preprocess_pending.py --files 10000 --repeats 7` measures only pending-batch selection, with the former inventory query simulated. Median was 10.28 ms with the simulated old scan and 7.14 ms without it. It does not measure embeddings, complete preprocessing, contention, or production throughput.

The final stale-path pruning scan is retained. The two search benchmarks do not measure HTTP/MCP transport, enabled preprocessors or a live running installation. The changes do not establish broader speed or quality improvements without the remaining evaluations above.

## Follow-up evidence (2026-11-04)

The separate synthetic holdout has seven cases (six positive); all six labeled paths ranked first and its negative returned no results. The labels are manual and the corpus remains small.

`python tools/benchmark_real_search.py --repeats 3` checks four source-verified symbol definitions in this repository. Initially three of four labeled paths appeared in the first ten and mean reciprocal rank was 0.5625; after declaration ranking and preserving engine order, all four ranked first. Labels identify one relevant path per query, not all relevant results. The isolated service had no cache or optional backends. Baseline per-query medians were 3.36–5.36 seconds with a locked project-excluded state directory causing ripgrep to fail; after translating safe project exclusions on Windows they were 0.31–0.43 seconds. This comparison is specific to that checkout and execution environment.

`python tools/benchmark_real_search.py --repeats 3 --cache` subsequently measured first requests at 474–545 ms and cache hits at 76–110 ms with a fresh repository fingerprint. This is in-process service timing, without HTTP/MCP transport, preprocessing or optional intelligence backends. Search skips cache reuse for degraded or incomplete fingerprints and explicit forced includes. Immediate file modification and addition were tested before the fingerprint TTL expired.

`python tools/benchmark_preprocess_demand.py --files 4096 --batch-size 64` placed a labeled hot file in batch 1 rather than batch 64 while still selecting 63 ordinary files in the first batch. Queue selection took 3.60 ms with demand hints versus a 2.39 ms baseline median; no model inference or full preprocessing ran. Learned hints are advisory, cached briefly, limited to four queries and 32 paths, and do not exclude regular work.

`python tools/benchmark_http_search.py --suite holdout --repeats 3 --noise-files 100` launches an isolated CPU-profile supervisor and calls `/api/search` over loopback HTTP; preprocessing is disabled. Six labeled targets ranked first and the negative case returned no result. Cold requests were 172–315 ms; most warm requests were 92–131 ms, with two observed outliers of 1,316 ms and 2,150 ms. Three samples per query do not establish p95 or sustained performance. A separate live HTTP test verifies literal `C++` and a source edit before the fingerprint TTL expires. The operator's installed Hub is not restarted by either check.

## Search continuation (2026-11-04)

The live MCP diagnostic returned a stale/partial RAG index and
`stale_or_denied_candidates`; reranking ran, but cannot repair missed
candidate recall. The live HTTP rerun after reindex still returned 0/2 for
Czech targets; subsequent RAG calls reported `embedding_space_mismatch` or
`embedding_backend`, and hybrid degraded to lexical fallback. Reranking was
configured, but was not used when embedding failed. High profile is active,
the reranker is configured, and no model downloads occurred. Czech expansion
is applied to RAG and bounded hybrid candidates; exact lexical mode is
unchanged. The failed recall shows expansion alone is insufficient.

The real HTTP exact-symbol case `max_index_bytes` returned both labeled paths
(recall@10 1.0, MRR 1.0); cold latency was 3,192 ms and warm-cache latency
256 ms. This is not a before/after comparison: an earlier direct MCP request
was cancelled after exceeding 70 seconds. Natural-language lexical queries
`Local AI Hub installation` and `Jak omezit velikost code indexu?` each
missed all labeled targets (0/1 and 0/2) in the live run. Their cold latency
was 4,388 ms and 3,341 ms; warm requests were 163 ms and 174 ms. These results
show current quality limits on this small labeled set.

The installed code-index DB measured 34,586,824,704 bytes, with zero-byte WAL
and 32,768-byte SHM sidecar. Runtime logs repeatedly report the 512 MiB budget
could not be enforced and skip startup auto-vacuum conversion for the oversized
database. The eviction candidate query previously evaluated four correlated
counts for every indexed file. It now limits candidate inventory to the
configured batch, then counts child rows only for selected files. Synthetic
storage benchmark released 7,053,312 bytes (16 files before, six evicted,
hot file retained); this does not measure live DB reclaim. Focused search,
RAG, demand and size-budget tests pass (59); release check passes. No live
code-index cleanup has been run by this patch.
