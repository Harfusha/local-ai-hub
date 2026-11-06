# Search benchmark results — 2026-11-05

## Live installed Hub: lexical baseline

Measured against the configured loopback HTTP `/api/search` endpoint in the real `C:\Users\Adam\.local-ai-hub` checkout. The runner used manually labeled case set `agent-search-manual-2026-11-05-v2`, 25 cases, and two requests per case (50 requests). Labels are source-anchored and manually judged; they are not exhaustive corpus truth.

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
