# Search benchmark

Run the labeled synthetic benchmark from the repository root:

```powershell
python tools/benchmark_search_quality.py --repeats 5 --noise-files 100
python tools/benchmark_search_quality.py --suite holdout --repeats 5 --noise-files 100
python tools/benchmark_search_quality.py --mode engine --suite holdout --repeats 5 --noise-files 100
```

The fixtures contain manually labeled exact symbols, natural-language terms,
near matches, unrelated noise files, and negative queries. The holdout labels
are separate from the development fixture. These runs measure the synthetic
service/engine only. They do **not** measure HTTP or MCP transport, a real
repository, preprocessing, RAG embeddings, reranking, or cold versus warm
application caches. Repeated samples have normal OS filesystem caching, so
they must not be called cold-cache results.

## Synthetic results — 2026-11-06

All runs used 100 unrelated files and five samples per query. Recall and MRR
are averaged across positive queries; latency ranges below are the ranges of
per-query medians and maximum per-query p95, respectively.

| Fixture and path | Queries | Recall@10 | MRR | Median range | Highest per-query p95 | Precision finding |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Development, `LocalAIServices.repo_search` | 8 | 1.00 | 1.00 | 36.46–44.40 ms | 79.50 ms | Lowest case 0.33; `restore session token` returned two distractors |
| Holdout, `LocalAIServices.repo_search` | 7 | 1.00 | 1.00 | 37.22–42.67 ms | 76.89 ms | Two natural queries had precision 0.50 |
| Holdout, `RepositoryTools.search` | 7 | 1.00 | 1.00 | 33.59–39.47 ms | 52.94 ms | Two natural queries had precision 0.50 |

Exact-symbol and negative cases passed in both fixtures. The natural-query
false positives show why recall alone is insufficient. These small synthetic
results do not establish general search quality or compare lexical, RAG,
hybrid, or reranker variants. The live Hub also needs a separate run after its
embedding backend and high-profile model finish preparing; the observed live
hybrid path previously degraded to a current-source lexical fallback.

## Remaining benchmark coverage

- A manually judged real-repository set, including Czech-to-English semantic
  queries such as `Local AI Hub installation`.
- Paired lexical, RAG, and hybrid runs, with reranker enabled and disabled.
- Actual cold and warm application-cache latency, median, and p95.
- Live HTTP/MCP boundary and running-install results, reported separately from
  synthetic fixtures.
