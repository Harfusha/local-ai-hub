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

## Continuation checkpoint — 2026-11-04 (RAG freshness repair)

- Root cause of the remaining stale installation candidate: `tests/test_prompt_contracts.py` changed while retaining the indexed `mtime_ns` and size. The RAG manifest compared only those stat fields, skipped reading the file, and kept an obsolete chunk. Live search correctly rejected it as `fragment_mismatch`.
- Added a regression that edits equal-length content, restores `mtime_ns`, and requires RAG to replace the old chunk. It failed before the fix (`changed_files=0`) and passed after.
- RAG now hashes bounded source bytes whenever an indexed file's stat metadata matches. Changed bytes are reused for chunking; unreadable or oversized files become `read_uncertain_paths` and remain explicitly uncertain. Embedding-space rebuilds skip the extra verification read.
- RAG hybrid/fragment-cache suites passed **62/62**; the expanded RAG/read-bounds/search-mode/API/live-benchmark selection passed **102/102**. `release_check.py --allow-installed` passed.
- Synthetic no-op indexing of 1,000 files (567,000 bytes) took 0.611 s with content verification; initial indexing took 5.946 s. This measures one warm temporary fixture, not a production speedup or p95.
- After commit `d923147a` and Hub restart, RAG indexing succeeded for 2,506 files: 18,657 chunks, 281 changed files, 475 newly embedded chunks, 4,319 reused chunks, 2,225 unchanged files, and zero skipped. The response reported 2,784 file reads because the unchanged paths were hashed; full service wall time was not recorded.
- Live `/api/search` benchmark, two samples per case across lexical/RAG/hybrid, used the active `high` configuration and configured reranker. `english-installation` hybrid returned both manual targets first (recall@10 1.0, MRR 1.0, NDCG 1.0), with 64 preprocessed candidates, 44 fused candidates, no stale candidates, no degradation, and reranking used. Warm samples ranged from 153 ms (RAG) to 413 ms (hybrid); this tiny mixed-cache run does not establish a general latency gain. Exact `repo_search` recall@10 remained 1.0 in lexical mode.
- MCP `local_ai_rag(search)` reports `reindex_required=false`, `reranked=true`, and `hybrid=true`, but its top two chunks for the installation query were test files. Endpoint freshness is fixed; standalone RAG relevance still needs investigation. Post-restart compact status reported Hub/Ollama online but degraded dependency probes and `active_model=null`; runtime readiness is therefore not fully verified.

## Continuation checkpoint — 2026-11-04 (chunk verification and GPU fence)

- Current source split noncontiguous module-level Python gaps into separate chunks. Regression proves every generated fragment is a verifiable contiguous source slice. The former join created synthetic fragments spanning omitted functions, which live freshness validation rejected as `fragment_mismatch`.
- Focused RAG/search set passed **27 tests**, with one benchmark test skipped unless `RAG_BENCHMARK=1`. `git diff --check` passed. Current source fix is not yet installed or activated in the running service.
- Latest live HTTP benchmark: `Local AI Hub installation` returned `docs/INSTALLATION.md` first in RAG and hybrid, with recall@10 1.0; hybrid MRR/NDCG were 1.0. Warm RAG was 133 ms and hybrid 367 ms in a two-repeat run. This small labeled sample does not establish general quality or p95.
- Direct MCP `local_ai_rag(search)` still degraded to heuristic reranking and ranked `src/local_ai_hub.egg-info/top_level.txt` first. Treat standalone RAG quality/backend behavior as unresolved.
- Exact lexical cold requests ranged from 2.7–16.8 s across the small live benchmark; warm requests ranged from 153–297 ms. `_exact_search_page` runs `rg --no-ignore` before bounded exact candidate filtering. Preserve exact totals while investigating redundant cold scanning.
- Current owner check found Hub PID 45156 and Hub `llama-server.exe` PID 18464 alive; GPU reports 14,842 MiB used. The orphan fence lacks lease metadata and no process-to-fence ownership proof is available. Authorized archive/clear was not performed because the final check did not establish that the fence is orphaned.
- SQLite still exceeds configured 512 MiB budget; read-only inspection measured 34,586,062,848 physical bytes and 31,269,007,360 reusable free bytes. Live eviction/compaction against the installed DB remains unverified.
- `/api/rag/search`, used by MCP `local_ai_rag(action="search")`, previously called `RAGStore.search` with its hybrid default. This contradicted the documented semantic-only RAG mode. It now explicitly sets `semantic_only=True`; the HTTP regression test failed before the fix and passed after.
- The combined HTTP/RAG/preprocessing focused set passed **40 tests** after this contract fix. `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, and `docs/MCP_AND_AGENTS.md` now describe direct RAG search as semantic-only with approximate candidates and incomplete coverage.
- Runtime remains on the pre-fix installed code until safe activation and fresh index/search verification. Do not infer direct MCP quality from the separate `/api/search` benchmark.

## Runtime activation — 2026-11-04

- `python tools/setup.py --generate-only --skip-companion-skills` regenerated MCP schemas and instructions. The Hub restarted successfully; `hubctl status` reports v5.1.3 online, RTX 5070 Ti 15 GB, and seven installed models.
- Read-only runtime config reports `hardware.profile=high` and `features.local_reranking=true`. Doctor reports no warnings; active quick model is `qwen3.5:4b-nvfp4`, and configured `qwen3.5:9b-nvfp4` is installed. Live reranker was used.
- Direct MCP RAG query `How do I install Local AI Hub from a fresh checkout?` returned `hybrid=false`, `reranked=true`, `degraded=false`, and `reindex_required=false`; `docs/PYTHON_SDK.md` ranked first. This verifies route semantics after restart, not broad relevance or the new chunker after reindex.
- Code changes are active. The Python chunk fix still needs a fresh RAG rebuild to validate current chunks. The orphan GPU fence remains uncleared: before restart the Hub llama-server was alive and GPU use was 14,842 MiB; no fence-owner identity was established. Live SQLite eviction/physical compaction remains unverified.

## Chunker revision invalidation — 2026-11-04

- Source-only follow-up adds `RAG_CHUNKER_VERSION` in `rag_meta`. Full indexing rechunks unchanged files after a version bump and publishes the marker in the same SQLite transaction only after a complete, certain pass.
- Demand-driven `index_paths_step` keeps indexing requested files during migration and reports `reindex_required=true` while legacy chunks remain. Semantic search cache keys include chunker revision; old workspaces report `degraded=true`, `index_state="stale"`, and `reindex_required=true`.
- Four red/green tests cover full rechunking, stale search metadata during normal and failed-backend search, and continued incremental progress. Focused RAG/search/API suites passed **124 tests**, with one optional latency benchmark skipped. `release_check.py --allow-installed` and `git diff --check` passed.
- Commit `92529dc9` was activated by Hub restart (v5.1.3, PID 35420). Direct MCP RAG now reports `index_state="stale"`, `reindex_required=true`, and `stale_reason="chunker_version_mismatch"`; it also reports `embedding_space_mismatch` and returns no candidates. Runtime therefore confirms fail-visible behavior, not a successful rebuild.
- The stale fence was checked before restart while the Hub `llama-server` was alive and GPU use was 14,842 MiB. Its lease metadata/generation is missing. Current `release_with_consent` requires a valid generation and expired metadata; no supported archive/clear operation handles this digest-only state. Do not unlink it directly or start the rebuild against unknown ownership.
- Rebuild and fresh RAG relevance remain unverified until a supported owner-bound fence recovery and embedding-space rebuild are available. The 512 MiB code-index limit and live SQLite compaction also remain unverified.

## 2026-11-05 runtime follow-up

- After an owner/process check, the user authorized archival and clearing of the metadata-less GPU fence. Its exact bytes were preserved in `state/external-gpu-reservation.orphaned-20261105T095520Z`; the Hub then reported the reservation free. No model was downloaded.
- The active Hub RAG index completed an incremental refresh: 31 changed and 2,481 unchanged files, zero skipped files, no reindex requirement, embedding space `bee36c7084a71fb39716d6349c074ad3c08a8c542dfdceb1471484df4d43d2a4`.
- A live `/api/search` check had repeatedly flagged the Git-ignored user `config.toml` as a stale fragment. The repository project policy now excludes that file and its named Hub backup variants from all indexed/search phases. Regression coverage verifies the repository policy; 11 project-policy tests passed.
- After refresh, live RAG and hybrid both returned `docs/INSTALLATION.md` first for `How do I set up Local AI Hub on Windows without running Ollama?`; each reported zero stale candidates, `degraded=false`, and `coverage_complete=false`. Both used the configured reranker. RAG returned 16 approximate candidates in 5,198 ms cold; hybrid returned 45 approximate candidates in 4,306 ms with a cache hit. These are single samples, not a latency comparison. The active profile was `high`; model downloads were disabled.
- Focused search, freshness, project-policy and benchmark tests passed **133 tests**. MCP transport at `127.0.0.1:11436` failed during this run, while the installed HTTP Hub on `127.0.0.1:11435` stayed online and answered benchmark requests.
- The live RAG reranker comparison on the same installation query returned 16 candidates and moved `docs/INSTALLATION.md` from rank 2 to rank 1. Three warm paired repeats measured median 115.43 ms without reranking and 110.89 ms with it; one query is too small to claim a speed gain. A separate CPU cross-encoder comparison on two labeled queries improved MRR 0.25 to 0.50, but missed the target in one top-8 candidate set and took 15,697.93 ms median (21,888.06 ms max). CPU and live Hub measurements are separate.
- Two one-shot live mode checks for general English and Czech installation prompts ranked `docs/INSTALLATION.md` first in RAG and hybrid. Lexical returned exact counts but missed that semantic target; observed latency was 13.1–18.3 s lexical, 2.8–7.2 s RAG and 0.68–0.70 s hybrid. Single observations only; some requests were warmed by prior modes.
- The independent reranker benchmark's first two labels were stale (`docs/INSTALL_PROMPT.md`); they now target the verified installation guide. The exact-search ripgrep accelerator now passes safe basename-only project exclusions on Windows before scanning, while retaining its authoritative project-policy postfilter and exact counts. Focused regressions passed **152 tests**, with one POSIX-only case-path test skipped on Windows.
- Search fixtures now include the manually checked direct English and Czech installation queries. One live sample per mode ranked `docs/INSTALLATION.md` first in RAG and hybrid for both; lexical kept exact counts but did not return that semantic target. After adding the Git-ignored `backups/**` tree to project exclusions, incremental RAG refreshed to 2,507 files / 20,440 chunks (from 2,513 / 20,450); `reindex_required=false`, and the live installation sample showed no stale candidates or degraded results. RAG/hybrid latencies were 767/794 ms in this run.
- The attempted post-exclusion lexical benchmark ended with `ConnectionResetError`; the following Hub status request returned retryable 503 with `request_not_sent=true`. That attempt is not a valid latency sample. The installed HTTP endpoint had answered immediately before it; live lexical performance after the exclusion change remains unverified.
- A later three-repeat live lexical benchmark for `How to install the local AI hub on Windows` succeeded: 4,118 exact matches, one cold request at 21,807 ms, and two warm hits at 192/191 ms. `docs/INSTALLATION.md` was not in the first lexical page, as expected for this semantic question. This is the installed endpoint measurement before the newest source-only path-policy optimization.
- A bounded cProfile of direct `RepositoryTools.search` on the real repository found about 1,800 repeated project-policy/path resolutions among 1,794 scanned files. Reusing one policy object per exact-search request kept exact count and scanned files unchanged and reduced this direct profile from 5,030 to 4,871 ms (3.2%); file reads and per-path checks still dominate. This local-source profile is not equivalent to the installed HTTP benchmark.
- The next live lexical attempt timed out at 30 s; Hub status then returned online, with `active_model=null`. The timeout is not a latency result, and the installed process revision is not yet bound to the current source commit.
- Focused exact-search, pagination, policy and mode regressions now pass **163 tests**, with one Windows-inapplicable POSIX case-path test skipped.
- Still open: larger manually judged multi-language and negative-query sets; representative cold/warm latency aggregates; optimize and remeasure exact lexical scans without weakening exact totals; verify HTTP/MCP transport and client/prompt parity; full installation/runtime and worktree coverage; remaining code-index admission/eviction, concurrency and physical SQLite verification. Do not treat these small live samples as broad quality evidence.
- Still open: larger manually judged multi-language and negative-query sets; representative cold/warm latency aggregates; optimize exact lexical scans without weakening exact totals; verify HTTP/MCP transport and client/prompt parity; full installation/runtime and worktree coverage; remaining code-index admission/eviction, concurrency and physical SQLite verification. Do not treat these small live samples as broad quality evidence.

## Continuation checkpoint — 2026-11-05 (direct semantic RAG)

- Current live status: Hub `5.1.3`, profile `high`, quick model `qwen3.5:4b-nvfp4`; reranking capability enabled. VRAM pressure was `unknown` in the status response, although a concurrent review admission sample observed 8,631/16,303 MiB used at nominal pressure. These are separate samples, not one synchronized hardware measurement.
- Incremental RAG index completed for 2,507 files and 20,457 chunks: 10 changed, 2,497 unchanged, 48 embedded, 162 reused, zero skipped, and `reindex_required=false`.
- On that live index, direct semantic-only query `Local AI Hub installation` omitted `docs/INSTALLATION.md` from top five. The same endpoint with bounded terms `setup bootstrap getting started` ranked the guide first. Both used reranking, reported `hybrid=false`, `degraded=false`, and `reindex_required=false`. This is one real-repository query pair, not a broad quality claim.
- Source now adds bounded English/Czech installation aliases only to semantic-only embedding queries. The original query remains the reranker input; lexical and ordinary hybrid inputs stay unchanged. The expanded embedding query is included in the cache identity. No response fields or MCP schema changed.
- TDD: three focused regressions failed before implementation for missing English/Czech expansion and exact-identifier preservation. After implementation, the semantic-only, RAG deduplication, and root-scope set passed **21 tests**; targeted `git diff --check` passed. This verifies source behavior, not installed runtime activation.
- Still open: activate and remeasure the new direct-RAG source in HTTP/MCP; broaden judged English/Czech/negative cases; investigate cold lexical scans; validate code-index demand admission, bounded eviction, concurrent deletion, actual SQLite reclamation, and installation/worktree boundaries. Preserve all unrelated dirty files and P23.

## Continuation checkpoint — 2026-11-05 (worktree index growth)

- Current Hub status: `5.1.3`, high profile, `qwen3.5:4b-nvfp4`, online; GPU reservation status now reports `free`. No fence files were removed in this continuation.
- Live direct MCP RAG query `Jak nainstaluji a zprovozním Local AI Hub ve Windows?` ranked `docs/INSTALLATION.md` first (embedding 0.7459, rerank 0.9275), `hybrid=false`, `reranked=true`, `degraded=false`, `reindex_required=false`. Lower ranks still included evaluation artifacts; RAG precision remains open despite the correct first result. This is one sample.
- Read-only source review found `_seed_from_parent` copied every parent `files`, `symbols`, `refs`, and `edges` row into each child worktree, multiplying unrelated rows and overstating child coverage.
- Removed that bulk code-index clone. Demand admission remains in `_step_code_index`, using root-scoped served evidence and the existing bounded, non-recursive one-hop Python import resolver. Shared content-addressed parse blobs remain available.
- Added regression `test_parent_seed_does_not_clone_whole_code_index_into_worktree`. It failed before the fix (`code_index=1`, expected `0`) and passed after it. Combined worktree cache, RAG seed, one-hop demand and size-budget run: **26 passed, 1 optional benchmark skipped**.
- Synthetic row-growth impact: four indexed parent files previously created four duplicate child file rows per registration; now child code-index rows remain zero until child-root demand admission. The existing 16-file storage benchmark measured 17,223,680 B before and 10,170,368 B after bounded cold eviction; 7,053,312 B physically released, six files evicted, hot file retained, configured 12,056,576 B target met. This synthetic eviction run does not measure the installed SQLite file or its physical reclaimable bytes.
- Remaining: current full benchmark/runtime activation, exact lexical and HTTP/MCP parity, broader judged retrieval, complete installed SQLite/table inventory, active-root-safe eviction and cleanup, and actual physical compaction evidence.

## Budget maintenance follow-up (2026-11-05)

- Idle maintenance now protects roots whose preprocessing status is `running`, evicts at most 512 cold indexed files and 8,192 orphan parse blobs per pass, and schedules another idle pass after 300 seconds while the index remains over budget. A regression exposed that the prior timestamp adjustment still checked the 1,800-second configured interval; maintenance now stores and checks the shorter retry interval directly.
- Focused size-budget and demand-priority tests: **19 passed**. Synthetic size benchmark: **17,223,680 B → 10,170,368 B**, 7,053,312 B physically reclaimed, six cold files evicted, hot file retained, 12,056,576 B target met.
- Current read-only installed-index snapshot: **4,046,466,936 B** against **536,870,912 B** configured; 984,304 pages × 4,096 B, zero freelist pages. Preprocessing registry: 3 running roots protected, 14 waiting, 53 complete. Dry-run selected 512 files and 8,192 of 61,722 orphan parse blobs (129,183,413 B payload); predicted physical size remains 3,387,107,203 B. This is a bounded estimate, not physical reclaim evidence. Read-only page/freelist values were unchanged across the dry-run.
- Root-cause evidence remains consistent with the earlier inventory: orphaned parse-blob payload and symbol-trigram data dominate logical growth; zero freelist means deletes alone cannot shrink the database. Actual live eviction/compaction has not been run against the 4 GB installation.
- Active config selects `hardware.profile=high`, enables reranking, and selects `BAAI/bge-reranker-v2-m3` with the CUDA Torch backend. Hub service reports ready on v5.1.3; `ollama ps` is empty and no external GPU reservation file exists. The MCP transport failed before request dispatch, so current live search/RAG and reranker-loaded behavior were not reverified. No fence was cleared and no model was downloaded.
- Current source/runtime evidence: Hub status reports `high`, active model `qwen3.5:4b-nvfp4`, CUDA hardware, Torch reranker backend and reranking enabled. The Hub process is ready, but ports 11436/11437/11439 have no listener; MCP search remains unavailable. Reranker-loaded state and live inference remain unverified.
- Synthetic holdout exact-search benchmark (`benchmark_search_quality.py`, 7 labeled cases, 100 noise files, 5 repeats, isolated service, no HTTP/MCP or preprocessing): recall@10 **1.0**, MRR **1.0**, negative case correct. Per-case median latency: **39–46 ms**; observed p95 range **44–981 ms**. Small synthetic set; one 981 ms outlier and non-exhaustive labels prevent a general-quality or tail-latency claim.
- Real-repository exact-search benchmark (`benchmark_real_search.py`, 4 manually labeled symbol cases, 5 repeats, isolated service, optional backends disabled): all expected paths rank 1, recall@10/MRR **1.0**. Four first-query samples: median **529 ms**, p95 **1,215 ms**; 16 warm-cache samples: median **74 ms**, p95 **81 ms**. Labels are not exhaustive; no HTTP/MCP, RAG or reranker comparison.
- Synthetic RAG vector-scan benchmark (`test_retrieval_latency_and_peak_memory_baseline`, uncached query path after warmup, no reranker): 1,024/8,192/16,384 chunks measured median **7.0/25.8/56.7 ms**; traced peak memory **2.43/2.49/2.44 MiB**; batches capped at 512. Three samples per size; this is not live-Hub cold-cache evidence.
- Focused search-mode, completeness, relevance, API and native-ranking tests: **60 passed, 1 optional latency test skipped**. MCP/operation search-boundary subset: **7 passed**. Reranker/search benchmark harness tests: **14 passed**.
- Cold exact-search profile found duplicate freshness probes: one `RepoStateTracker.fingerprint()` in lexical hint validation, then another forced fingerprint in `_repo_cached`. The request now reuses one forced snapshot. The real-repository profile dropped one Git status subprocess (four child processes → three, including ripgrep). Focused cache, mode, pagination and HTTP/MCP hint tests: **57 passed**; MCP/operation search subset: **7 passed**.
- Follow-up real-repository run (four labeled exact symbols, five samples each): cold median/p95 **489/743 ms**, warm **76/234 ms**, recall@10/MRR **1.0**. Earlier same-script sample was **529/1,215 ms** cold and **74/81 ms** warm. These runs are unpaired and sensitive to OS cache/outliers; they show no established speedup. The controlled process profile proves one Git status launch was removed from the first cold request.

## Continuation checkpoint — 2026-11-05 (query-set expansion and live lexical follow-up)

- Expanded the source-anchored live fixture from 14 to **25** manually reviewed cases: **9 English**, **8 Czech**, exact symbols, and **3 negatives**. New labels cover hybrid/RAG degradation, incremental RAG, pagination bounds, one-hop symbol lookup, and worktree scope. Negative query text is base64 encoded so the benchmark fixture cannot answer its own negative cases. TDD observed the expected failure at 14 cases; the complete benchmark unit file passes **5 tests**.
- Live installed HTTP `/api/search`, exact `pagination_bounds_error`: correct file ranked first, exact count **32**, current-source coverage; cold **1,948 ms**, warm **319 ms** (`cache_hit=true`). Two samples from one query; not a general latency claim.
- A separate single-sample HTTP run returned `repo_search` with recall@10/MRR **1.0**, exact count **155**, and **4,142 ms** latency. English and Czech natural installation queries took **13,559 ms** and **9,329 ms** in lexical mode; lexical is not the semantic path for these queries. The negative unknown symbol returned zero matches in **781 ms**. These are individual cold observations; no aggregate or paired speedup is established.
- Current read-only `state/code-index.sqlite3` snapshot is **1,814,528 B**, 443 pages, zero freelist, integrity `ok`; compaction dry-run predicted **0 B** reclaimable. The database currently has zero `files`, `symbols`, `refs`, `edges`, and parse blobs, plus 348 usage rows and 6,904 orphan trigram rows. The trigram roots still have Git metadata and are protected by cleanup policy. This small, empty snapshot does **not** prove the configured 512 MiB limit or useful coverage on a populated installation; the prior 4.0 GB snapshot belongs to an earlier runtime state and must not be substituted for this one.
- The Hub remains on `high`; active model is null and GPU admission is `outcome_unknown`. Fence generation `d6412d5774cf4f43bc5e4f29f6d7bdeb` has valid, unexpired metadata owned by live Hub process PID 29612 (owner thread 43448 is absent). It is not eligible for release under the owner-death/expiry contract. No further RAG/reranker requests or fence mutation were made. CUDA rebuild, reranker A/B, fresh RAG relevance and MCP parity remain open.
- Focused current code-index demand, size-budget, compaction CLI, stale-file cleanup and trigram tests: **48 passed**. P23 and all foreign dirty paths were left untouched.
- The 11 newly added labels were also sampled against live lexical HTTP: **2/9** positive natural-language targets appeared in top 10; the two hits ranked fourth and third. The exact unknown-symbol negative returned no results; the unrelated natural-language negative returned irrelevant files. Single cold samples ranged **949–14,931 ms**. This supports keeping lexical for exact/count contracts and requiring the unavailable RAG/hybrid run before judging natural-language quality; it is not an aggregate production estimate.
- Current read-only RAG inventory: `state/rag.sqlite3` is **557,744,128 B**, with **44,777** chunks and **10,947** file rows across 17 repository roots. The Local AI Hub workspace has **2,509** files and **20,592** chunks: 315 under `docs/`, 208 under `src/`, 1,278 under `tests/`, and 708 elsewhere. It has one embedding space, zero chunks without file rows, and three files without chunks. P23 appears as a separate 23-file root; it was not read or changed beyond aggregate database counts.
- The active Hub project config now excludes `.merge-checks/**` and `**/*.egg-info/**` from search and preprocessing. Evidence: `.gitignore` marks both classes ignored, and the RAG DB held an old ignored test artifact plus generated package metadata. `ProjectPathPolicy` checks confirmed both patterns are rejected in both phases while installation docs and Python source remain allowed. Existing RAG rows remain until the next authorized workspace refresh; the active GPU lease prevented that refresh in this turn.
- Repository-sampled preprocessing benchmark (`2048` text files, `22,816,562` bytes, query `_step_rag`, no model inference): demand priority returned useful context in **171 ms** after 64 files versus **2,030 ms** after 512 files in FIFO baseline. First batch selected all 7 matching files; both modes completed all 2,048 files in 32 batches. Selection median/p95 was **2.54/4.40 ms** with demand versus **1.90/3.44 ms** baseline. This one bounded workload shows useful-work latency and no batch starvation, not sustained concurrent fairness. Focused RAG/policy/incremental/freshness suites passed **84 tests**; project-config suite passed **81 tests**.
- Current live MCP lexical verification: `pagination_bounds_error` returned the exact declaration at rank 1 with `index_state=current_sources`, `count_exact=true`, and **33** exact matches. Pages at offsets 0, 1, and 2 returned three distinct paths and advanced `next_offset` by the actual returned count; response budgeting limited each page to one result. A random unknown symbol returned zero results with exact total 0. This confirms lexical exactness and response-aware pagination on the running Hub, but does not establish semantic quality or latency.
- Current shared dirty-tree regression run: **176 tests passed in 12.10 s** across GPU reservation lifecycle/MCP release, agent routing, prompt contracts, semantic services and preprocessing demand priority. Hub reports **5.1.3/high**, Ollama online, active model null; an embedding lease is renewed by a live Hub process/thread. `python tools/cleanup_code_index.py --dry-run` returned `hub_online` for `state/code-index.sqlite3`; it made no changes, so live reclaimable bytes remain unmeasured until safe offline maintenance. No source, index, or P23 data was changed by these checks.
- Read-only live code-index inventory: configured `max_index_bytes=536,870,912`; SQLite main file **452,161,536 B**, WAL **148,352 B**, SHM **557,056 B** (total **452,866,944 B**). `page_count=110,391`, `freelist_count=76,781` (**314,494,976 reusable page bytes**). Tables hold 40 files, 2,226 symbols, 8,846 refs, 9,045 edges, 161 parse blobs, 275 usage rows, and **445,139 symbol trigrams**. A temporary SQLite backup snapshot preserved all these row counts; VACUUM reduced the copy from **452,161,536 B** to **128,569,344 B**, reclaiming **323,592,192 B**, with freelist 0. The live source remained **452,161,536 B**; it was not vacuumed because the Hub was online. Measured physical excess is SQLite free pages retained in the live file; the row inventory shows a trigram-heavy live index. Exact operation history that created the free pages is unknown; the copy result is not live-install reclamation proof.
