# Search benchmark results — 2026-11-05

## Live installed Hub: lexical baseline

Measured against the configured loopback HTTP `/api/search` endpoint in the real repository checkout. The runner used manually labeled case set `agent-search-manual-2026-11-05-v2`, 25 cases, and two requests per case (50 requests). Labels are source-anchored and manually judged; they are not exhaustive corpus truth.

Reproduce with:

```powershell
python tools/benchmark_live_search.py --modes lexical --repeats 2
```

| Measure | Result |
| --- | ---: |
| Cases with successful result | 25 / 25 |
| Requests | 50 (2 per case) |
| Positive cases | 22 |
| Mean recall@10 | 0.432 |
| Mean precision@10 | 0.085 |
| Mean reciprocal rank | 0.330 |
| Mean NDCG@10 | 0.331 |
| Negative cases correct | 2 / 3 |
| Request median latency | 771.9 ms |
| Request p95 latency | 8,891.7 ms |
| Cold-cache median / p95 | 6,275.3 / 9,502.6 ms |
| Warm-cache median / p95 | 228.5 / 957.1 ms |

The five installation cases all missed `docs/INSTALLATION.md` in the returned top 10. Results frequently repeated paths such as `src/local_ai_hub/generator.py`; the benchmark computes ranking metrics over unique paths, but duplicate snippets still consume result slots. These are concrete lexical relevance and latency targets for the next iteration.

## Runtime boundary

- Hub reported version `5.1.3`, profile `high`, reranking enabled in configuration, and `active_model=null`.
- The lexical benchmark did not request or use reranking. `reranker_configured=true` is configuration evidence only.
- Runtime reported `gpu_admission_state=outcome_unknown`, stale VRAM telemetry, and reranker `provider_readiness=not_checked`. Therefore this run does not establish RAG/hybrid quality, reranker quality, or GPU inference capacity.
- Read-only device inventory found an NVIDIA GeForce RTX 5070 Ti with 16,303 MiB total and 9,247 MiB used at sampling time. Ollama listed `qwen3-embedding:0.6b`; this does not establish that the Hub's embedding request succeeded. No models were downloaded.

## Scope limits

This is one small, manually labeled set on one real repository and one installed-service mode. It is not evidence of general search quality. RAG, hybrid, reranker on/off, MCP boundaries, active preprocessing load, and current-source changes/removals still need independent measurements. The live GPU reservation must be reconciled through a supported Hub action before inference benchmarks can run.

## Live installed Hub: lexical latency recheck — 2026-11-06

The same 25-case set ran once per case against the installed loopback HTTP endpoint and the real repository. All 25 requests returned HTTP 200 with `success=true`; all reported `cache_hit=false`, so this sample has no warm-cache measurements. The configured profile was `high`; reranking was configured but used by zero lexical requests. No response was marked degraded.

| Measure | Result |
| --- | ---: |
| Cases / successful requests | 25 / 25 |
| Median of per-case latencies | 3,447 ms |
| Maximum observed latency | 7,835 ms |
| Negative cases correct | 2 / 3 |
| Reranker used | 0 / 25 |

There was one sample per query, so the maximum is not a stable p95 estimate. This run records current installed-service latency only; relevance metrics above belong to the separate 2026-11-05 two-repeat run. The Hub still reported `active_model=null` and `gpu_admission_state=outcome_unknown`, so no RAG, hybrid, or reranker comparison was attempted.

## Live installed Hub: lexical repeated run — 2026-11-06

The same 25 labeled cases ran three times against the installed loopback endpoint. All 75 requests succeeded with HTTP 200. In the first run, each query had one cache miss followed by two hits. Cold samples had a 3,365 ms median and 6,063 ms p95 (nearest-rank, 25 samples). A separate all-warm 75-request run measured a 201 ms median and 1,195 ms p95. The warm p95 includes service-load outliers; it is not a model-latency estimate.

| Measure | Result |
| --- | ---: |
| Manually labeled cases / samples | 25 / 75 per run |
| HTTP-successful requests | 75 / 75 per run |
| Cold median / p95 | 3,365 / 6,063 ms, 25 samples |
| All-warm median / p95 | 201 / 1,195 ms, 75 samples |
| Macro recall@10 / precision@10 | 0.432 / 0.085 |
| Macro MRR / NDCG@10 | 0.330 / 0.331 |
| Negative cases correct | 2 / 3 |
| Reranker configured / used | yes / 0 cases |

The cold and all-warm latency figures come from separate runs and are not combined. Quality values are macro averages over the 25 labeled cases. The endpoint reported `index_state=current_sources` for lexical results. This benchmark does not establish RAG or hybrid quality; those modes remain unmeasured against the live service while GPU admission is unresolved.

## Current-source benchmark: lexical and degraded hybrid — 2026-11-06

Expanded `tools/benchmark_real_search.py` with four exact-symbol cases and four manually source-anchored natural-language cases, including English/Czech installation and code-index requests. The benchmark runs isolated `LocalAIServices.repo_search` against this checkout with optional semantic backends disabled; it does not exercise HTTP/MCP or active preprocessing. Cold/warm lexical results below use two requests per case and the service cache.

| Measure | Lexical result |
| --- | ---: |
| Cases / requests | 8 / 16 |
| Expected file in top 10 | 5 / 8 |
| Mean reciprocal rank | 0.563 |
| Cold median / p95 | 1,840 / 4,535 ms (8 samples) |
| Warm median / p95 | 93 / 105 ms (8 samples) |
| Exact symbol targets at rank 1 | 4 / 4 |

Both installation queries and `Jak omezit velikost code indexu?` missed their labeled files; `Jak nastavit limit code indexu?` ranked its expected source second. A separate one-repeat hybrid run over those four natural queries, with RAG disabled in this isolated harness, returned `result_source=lexical_fallback`, `degraded=true`, and `degradation_reason=rag_disabled` for all four; all four labeled files were missed (0/4 top-10, MRR 0). Latency was 1.43–1.82 seconds. This is evidence about the degraded current-source fallback only, not a live RAG/hybrid or reranker comparison.

The holdout synthetic benchmark (`python tools/benchmark_search_quality.py --repeats 3 --noise-files 100 --suite holdout`) scored recall@10 1.0 and MRR 1.0 over seven cases. Its precision@10 was 0.5 on two broad positive cases and 1.0 on the remaining positives and negative case; per-case median latencies were 37–44 ms and nearest-rank p95 values 42–96 ms. This synthetic result is separate from the real-repository failures above and does not establish general quality.

### Hybrid fallback after candidate-priority changes — 2026-11-06

Repeated the isolated real-repository benchmark with eight manually anchored queries, three requests per query, and service caching enabled. The fallback found every labeled file in the top 10 (8/8, MRR 0.844). Exact-symbol cases and both installation queries ranked first; the Czech code-index queries ranked their labeled files second and fourth. The search now prioritizes query-matching paths before checking access and limits the remaining lexical scan to at most 320 files for installation intent and 256 otherwise; omitted paths report `candidate_file_limit`, so the fallback does not claim full coverage. Across eight cold and sixteen warm samples, cold median/p95 were 787/1,501 ms and warm median/p95 were 111/185 ms. Against the pre-cap same-harness run, cold median/p95 fell from 2,141/3,893 ms (about 63%/61%). Four natural-language cases explicitly degraded because RAG was disabled; the reranker ran zero times. This improves the earlier fallback relevance and cold latency result but does not measure live RAG, reranking, HTTP/MCP, or the running Hub.

## Live Hub RAG check — 2026-11-06

`local_ai_rag:list` reported 2,506 files and 20,592 chunks for this workspace. A live `Local AI Hub installation` query returned no candidates and explicitly reported `degraded=true`, `fallback=embedding_space_mismatch`, and `reindex_required=true` for index revision `f894d022ec08cc06964ebe62192df5fc8bd1cf7b5d9a982b51b3cf5dfc9b873f`. Two authorized index attempts returned retryable `gpu_reserved`. After the expired lease was reaped, a new 64-byte reservation fence appeared without lease metadata; Hub status then reported `gpu_admission_state=outcome_unknown`. This is an unavailable live-RAG measurement, not a relevance score. No reservation file was edited and no model was downloaded.

The operator explicitly authorized the supported orphan-fence recovery. The authorized release marker was recorded without directly editing or deleting a reservation file. After the authorized Hub restart, Doctor reported v5.1.3 online, an RTX 5070 Ti with 15 GB, SentenceTransformers installed, and active `qwen3.5:4b-nvfp4`. A live hybrid installation query returned `docs/INSTALLATION.md` first from current sources, but reported `degraded=true`, `degradation_reason=embedding_space_mismatch`, stale/partial RAG state, and no reranker use. A later default agent search returned `result_source=hybrid` with 14 RAG candidates and the same document first, while reporting a stale index, partially verified candidates, one fragment-mismatch candidate, and heuristic reranking (`used=false`). One RAG reindex request returned retryable `gpu_reserved`; the subsequent reservation check found no reservation file and `state=free`, while Hub readiness showed `gpu_admission_state=available` but active model null and VRAM telemetry stale/sample-pending. No identical reindex retry was started. Live index rebuild and reranker quality/latency therefore remain unverified; no model was downloaded.

## Synthetic vector-retrieval baseline — 2026-11-06

`RAG_BENCHMARK=1 python -m pytest -q tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline -s` scored all vectors once in bounded batches of 512, without HTTP/MCP, query embeddings, or reranking. Each corpus used three warm samples; p95 is nearest-rank and therefore equals the observed maximum at this sample size.

| Chunks | Median / p95 | Peak traced memory | Scoring batches |
| ---: | ---: | ---: | ---: |
| 1,024 | 7.462 / 7.660 ms | 2.429 MiB | 2 |
| 8,192 | 25.151 / 25.215 ms | 2.487 MiB | 16 |
| 16,384 | 55.700 / 58.919 ms | 2.440 MiB | 32 |

These timings measure the in-process vector scan only; they do not estimate embedding, reranker, cold-start, or live-service latency.

## Installed Hub after commit 860f953f — lexical recheck, 2026-11-06

After installing the clean commit with profile `high`, ran
`tools/benchmark_live_search.py --modes lexical --repeats 3 --timeout-seconds 15`
against the installed loopback service and this real repository. Of 25 labeled
cases, 24 completed all three HTTP 200 requests; `exact-rag-preprocess` timed
out after 15.011 s on its first request, so the benchmark stopped repeating
that case. The lexical mode did not request or use the reranker. The command
output was truncated before its complete relevance summary, so this recheck is
latency evidence only and its partial per-case quality must not be treated as a
macro score.

| Measure | Result |
| --- | ---: |
| Successful requests / timeout | 72 / 1 |
| Cold samples (one per completed case), median / p95 | 4,142 / 6,866 ms |
| Warm cache-hit samples, median / p95 | 209 / 607 ms |
| Cold / warm maximum | 9,632 / 3,010 ms |

Percentiles use nearest-rank over the successful samples and exclude the
15-second timeout. For `repo_search`, recall@10 was 1.0, precision@10 0.2,
MRR 1.0 and NDCG@10 0.920; this is one query, not broad quality evidence.

One read-only storage sample from the installed code-index database measured
418,532,528 physical bytes against the 536,870,912-byte cap. The database had
97,758 pages, 29,830 free pages and 122,183,680 reusable bytes; physical size
was under cap by 118,338,384 bytes. This single live snapshot can change while
the Hub writes; it is not a stable post-compaction measurement.
The RAG database's stored fingerprint matched the active configuration; no RAG
database rebuild was needed. Hub health and MCP returned online on 5.1.3 with
the `high` hardware profile. GPU reservation status then reported
`state=unknown`, so this run did not attempt CUDA embedding or reranker
inference.

## Synthetic code-index inventory benchmark — 2026-11-06

`tools/benchmark_code_index_inventory.py` used an in-memory SQLite database
with 50,000 synthetic file-reference rows, seven repeats and 45,454 eligible
rows. This isolates Python allocation and SQLite inventory iteration; it does
not measure project parsing, write contention, search relevance or live Hub
latency. The current real repository has 1,981 `file_refs` rows for this root,
all pointing to existing files, so the synthetic corpus is about 25 times
larger than the current per-root inventory.

| Batch size | Full materialization median / p95 | Peak Python memory | Bounded median / p95 | Peak Python memory |
| ---: | ---: | ---: | ---: | ---: |
| 256 | 242.52 / 267.60 ms | 15,149,929 B | 166.95 / 650.40 ms | 7,791,301 B |
| 512 | 219.72 / 413.78 ms | 15,149,929 B | 170.19 / 251.03 ms | 7,808,181 B |
| 1,024 | 223.92 / 256.25 ms | 15,149,929 B | 160.80 / 383.54 ms | 7,845,685 B |

The bounded iterator used roughly half the peak Python memory in this synthetic
run. Seven samples make p95 equal to the nearest-rank maximum and expose noisy
timings; no batch-size change is justified by this result. The live
preprocessor currently fetches 256 references at a time. This microbenchmark
does not establish end-to-end speedup or general scaling.
