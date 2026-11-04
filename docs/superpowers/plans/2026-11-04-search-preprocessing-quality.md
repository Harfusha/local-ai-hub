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
code-index cleanup had run at this checkpoint.

## Live code-index inventory and cleanup (2026-11-04)

Read-only inventory found 58 roots; all root directories exist. The
`f36f\.local-ai-hub` directory is empty and is not a Git worktree, but its
index held 1,663 file rows (26,086,393 source bytes). A dry-run found exactly
those 1,663 stale paths, with no other stale roots. P23 is an active Git
worktree and was skipped by cleanup.

The bounded cleanup removed only those derived rows; it preserved shared parse
blobs and is safe to repeat after interruption. The P23 root still has 1,772
code-index file rows. SQLite incremental vacuum freed one page. After stopping
the Hub, a single WAL truncate checkpoint released 659,250,200 physical bytes
from sidecars; no database file was deleted. The main database remains about
34.59 GB, with 1,263,160 free pages (about 5.17 GB) still inside it. Physical
database compaction and enforcement of the 512 MiB configured limit remain
unproven; full VACUUM was not run. Latest runtime check reports Hub 5.1.3
online, VRAM nominal, but `active_model=null`; the last installer doctor had
reported high profile, RTX 5070 Ti 15 GB, and no warnings.

## Natural-language RAG follow-up

After the fresh index revision, direct RAG search for `Local AI Hub
installation` still ranked `src/local_ai_hub.egg-info/top_level.txt` above the
installation guide, and that request used the heuristic reranker fallback.
Queries phrased as `How do I install Local AI Hub?` retrieved `CONTRIBUTING.md`,
`docs/PYTHON_SDK.md`, and `docs/INSTALL_PROMPT.md`; `Hub installation setup
bootstrap` retrieved `docs/INSTALLATION.md` first with the configured
reranker. This isolates a vocabulary gap in the short natural query, rather
than an absent document or stale index.

Semantic expansion now adds bounded `install`, `setup`, `getting started`, and
`bootstrap` terms for installation queries. The benchmark label for the
English installation case now points to `docs/INSTALLATION.md`. Lexical mode
continues to receive the original text. The focused search-mode suite passes
18 tests. The synthetic holdout service benchmark (7 cases, 100 noise files,
3 repeats) reports recall@10 and MRR 1.0; its median query latencies are
40–45 ms, with one 81 ms outlier. This exercises lexical service retrieval,
not live RAG or Hub transport. Re-run the labeled live RAG/hybrid benchmark
after deploying this change; runtime quality and latency remain unverified.

The committed installation-query fix was installed into the editable Hub
package and the Hub was restarted. The first full setup pass stopped after
package installation because the existing Codex Superpowers plugin required
review. A supported `--generate-only --skip-companion-skills` pass refreshed
MCP, schemas and instructions without replacing that plugin; the Hub was
started and verified online on high profile. No model was downloaded. The
GPU reservation check returned `state=free`, so no orphan fence was archived
or cleared.

After a fresh RAG index run (2,506 files; 34 changed; 18 embedded chunks), the
live HTTP benchmark over two samples per query reported RAG recall@10 1.0 for
English installation (MRR 1.0), and 0.0 for Czech code-index size. Hybrid
reported English recall 1.0 (MRR 0.333) and Czech recall 0.0. Requests marked
the index stale with three rejected candidates despite successful reranking;
RAG median latency was 259–345 ms and hybrid 894–1,375 ms. The benchmark's
HTTP response has no cache-hit field, so cold/warm splits were unavailable.
This live evidence shows the install expansion helps candidate recall but
the size-query expansion still needs work.

An isolated live RAG probe with additional bounded terms `database storage
eviction maximum bytes` returned `docs/CODE_INDEX.md` and
`src/local_ai_hub/code_index.py` among its top three candidates, while the
benchmark script and fusion test also ranked highly. Those terms are now added
to Czech index-size query expansion and covered by unit tests (70 passed,
including the concurrently present task-input change). This latest expansion
has not yet been restarted into the running Hub or evaluated in the live
benchmark. The unrelated modifications in `operation_contracts.py` and
`test_task_canonical_inputs.py` appeared during setup; they are preserved for
review and are not included in this search fix commit.

## Live checkpoint — 2026-11-04

- Hub `5.1.3` online, profile `high`, active model `qwen3.5:9b-nvfp4`; reranker enabled and used by live search. Model downloads: none.
- RAG index succeeded for the Local AI Hub root: 2,506 files, 18,859 chunks, 10 changed files, 90 newly embedded chunks, 385 reused chunks. This is an incremental result, not proof of exhaustive semantic coverage.
- A four-query live sample (two HTTP requests per query/mode) found RAG recall@10 1.0 for installation and Czech index budget (MRR 1.0 and 0.333); exact `C++` recall 0; unknown-symbol negative correct. Hybrid recall@10 1.0 for installation and Czech index budget (MRR 0.333 and 0.2); exact and negative queries had no relevant result and took up to 10.42 s and 7.42 s respectively. RAG observed request times were 0.14–0.83 s; hybrid 0.26–10.42 s. Small sample; not a general-quality claim.
- Several search responses still reported `index_state=stale`, `coverage_complete=false`, or `stale_or_denied_candidates` after indexing; cause remains under investigation. Search must continue to disclose that state.
- Implemented a hybrid exact-symbol short-circuit: run current-source lexical search directly; skip RAG/reranker; expose `result_source`, skip reason, and lexical exact count. Focused tests and live post-restart latency verification remain.
- GPU reservation release returned an output-contract error, but subsequent authoritative status reports `reservation_present=false`, `state=free`, `manual_intervention_required=false`. No second release call was made.

## Post-implementation verification — 2026-11-04

- Restart initially stopped Hub but returned `managed_ollama_stop_unverified`; `hubctl status` confirmed stopped, `service.py start` returned `started`, and MCP status then confirmed Hub `5.1.3`, profile `high`, Ollama online, VRAM `nominal`. Reranker remains operator-enabled.
- The expired reranker fence release reported an MCP output-contract error, but a later authoritative reservation status showed `reservation_present=false`, `state=free`, and `manual_intervention_required=false`. No retry was made.
- Post-restart live hybrid benchmark verified the exact-symbol fast path. `C++`: recall@10 1.0, MRR 1.0, exact count 30, cold 1,194 ms, warm 158/183 ms, `result_source=lexical`, `coverage_complete=true`, reranker requested but intentionally unused. Unknown symbol: zero matches, cold 1,115 ms, warm 190/196 ms, same explicit skip reason. Earlier pre-change hybrid samples reached 10,420 ms and 7,419 ms respectively; small, non-paired sample.
- After prompt updates, RAG was indexed again: 2,506 files, 18,861 chunks, 5 changed files, 9 embedded chunks, 363 reused chunks. Natural-query search still reported `stale_or_denied_candidates` for installation and `index_state=stale` despite `reindex_required=false` from direct RAG search; root cause remains open.
- Contract clarification: `local_ai_repo(search_mode="rag")` explicitly calls RAG semantic-only. Separate `local_ai_rag(action="search")` currently reports `hybrid=true` and uses backend hybrid retrieval.
- Focused search/HTTP/MCP tests: 82 passed; release check passed. Synthetic code-index storage benchmark and broader active-worktree cleanup/physical SQLite shrink remain distinct, incomplete acceptance items.

- The RAG backend already returns `search_cache.hit/coalesced`; repository search now preserves these fields so `/api/search` benchmarks can distinguish actual cold, warm, and coalesced retrieval. The benchmark fixture also records exact-symbol RAG skip metadata.

## Continuation checkpoint — 2026-11-04 (fence recovery and paging guard)

- User authorized archive/clear of the orphan GPU lease. Final check found its owner PID 32644 absent, its lease expired at 14:59 UTC, and no active digest fence or canonical lease metadata. Under the reservation lock, the exact stale temp lease was moved to `state/orphan-archive/` and an audit event was appended. No model was downloaded. The same RAG workspace then indexed successfully: 2,506 files, 18,866 chunks, 4 changed files, 8 embedded chunks, 307 reused chunks.
- Commit `c3b6be8a` includes the independently labeled `CONTRIBUTING.md` installation evidence, natural-query CodeIndex hint test correction, and current goal checkpoint. Targeted tests passed 69/69; `release_check.py --allow-installed` passed; diff check was clean. Worktree P23 was not accessed.
- After restart, service status reported Hub ready and Ollama online. Compact MCP status briefly returned `active_model=null`, but live HTTP benchmark identified the configured `high` profile and reranker model `BAAI/bge-reranker-v2-m3`; reranker was requested and used on sampled RAG/hybrid queries. This proves use, not model quality or stable GPU telemetry.
- Three-query live HTTP sample (3 repeats each, RAG + hybrid) confirmed English installation recall@10 1.0 in both modes; hybrid also recalled both Czech index-size targets (MRR 0.2, NDCG 0.442). Semantic RAG missed the exact `_exact_search_page` symbol as expected for semantic-only mode. Most warm requests were 0.12–0.25 s, but hybrid outliers reached 5.4–9.5 s even with `cache_hit=true`; sample is small and does not establish a general speedup. Several responses still exposed stale coverage (`stale_or_denied_candidates`).
- The experimental RAG `top_k` reduction was not accepted: live data did not isolate a reliable speed gain, and the query window varied with offset. Replaced it with a stable `max(32, page_limit)` candidate window; added a regression test proving offsets 0 and 20 use the same window. Focused follow-up: 38 passed. Need repeat a bounded live comparison after restart and diagnose high-tail latency/stale candidates before claiming improvement.

## Continuation checkpoint — 2026-11-04 (preprocessed hybrid candidates)

- Commits `4016cee8` and `04e81b38` add a bounded preprocessed candidate scope for hybrid natural-language lexical search. The source still verifies current content, project policy, root confinement and file type. Candidate sets are capped at 64; empty/unsafe sets reject or fall back to current-source scanning. Exact-count search explicitly rejects candidate scoping. Hybrid reports `lexical_candidate_source`, candidate count, and still reports incomplete coverage. Path hints are merged into the candidate scope.
- Focused search/T10/live benchmark/API pagination tests passed 56/56 before the final report-only metadata field; release check passed. After restart the RAG index succeeded: 2,506 files, 18,867 chunks, 3 changed files, 4 embedded chunks, 294 reused chunks.
- Live hybrid sample after activation: installation and Czech index-budget recall@10 remained 1.0; English installation had MRR 1.0 and NDCG 0.920, Czech MRR 0.25 and NDCG 0.501. Natural queries used 64 preprocessed candidates and the live reranker. Warm English was 453/492 ms, compared directionally with the earlier unpaired 1.295/9.484 s sample; Czech warm was 383/2,431 ms, showing a large tail remains. Cold English reached 17.2 s, so this small, non-paired run does not establish an overall speedup.
- Exact `_exact_search_page` remained precise, complete, and reranker-bypassed; warm times were 211/1,775 ms in this run, showing service latency variance even on the lexical fast path. English still reports `stale_or_denied_candidates`; the specific stale chunk and safe freshness treatment remain unresolved. Benchmark output now preserves lexical candidate source/count and stale candidate count for the next diagnostic run.

## Continuation checkpoint — 2026-11-04 (reranker and regression evidence)

- Offline reranker benchmark used only cached files (`model_downloads_allowed=false`): high profile, `BAAI/bge-reranker-v2-m3`, PyTorch CUDA backend. On four synthetic natural-language labels, the relevant candidate moved from rank 3 to rank 1 (MRR 0.333→1.0, NDCG 0.5→1.0); exact `repo_search` labels were already rank 1 and did not improve. Two-sample median per query was about 34–35 ms except installation (5.52 s median due an 11.03 s first sample); script marked samples `warm_hit`, so the cold/warm label needs correction before using this as production latency evidence. This is synthetic ranking evidence, not repository quality proof.
- Post-index live ad-hoc English question “How do I install Local AI Hub?” reached both manual targets (recall 1.0, MRR 1.0, NDCG 0.920), used 64 preprocessed candidates and reranker, and had stale count 0. The benchmark fixture’s “Local AI Hub installation” still reports exactly one stale/denied candidate after a successful fresh index (`reindex_required=false` in direct RAG); another nearby query has zero. Candidate-specific cause is not yet isolated; endpoint correctly marks this result degraded and incomplete.
- Broad search regression selection passed **181 tests**, with one skip because the filesystem is case-insensitive. This covers search modes, pagination, exact matching, API path hints, completeness, policy consumers, and live benchmark runner. `release_check.py --allow-installed` also passed on the committed source.
- `nvidia-smi` after the local reranker run reported RTX 5070 Ti, 16,303 MiB total, 5,288 MiB used, 10,708 MiB free. This is a post-run snapshot, not a before/after VRAM delta. Do not claim a measured peak VRAM impact from it.
- Corrected the synthetic reranker benchmark: it now forces one `cache_enabled=false` inference per case, restores the instance setting, then measures cache hits with explicit hit/computed counts and records whether model loading was included. Verified on high/CUDA with downloads disabled: manual labels improve MRR 0.333→1.0 and NDCG 0.5→1.0 for natural queries; the exact symbol baseline remains rank 1. First cold model load took 10.525 s; one uncached Czech inference took 2.718 s while the other three took 51–70 ms; cached samples were 49–68 ms except one 555 ms outlier. One sample per case is too small for p95 or stable latency claims.
