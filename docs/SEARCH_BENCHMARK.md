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
| Holdout, service default with optional backends absent | 10 | 0.89 | 0.89 | 36.79–54.40 ms | 94.68 ms | Two natural queries had precision 0.50; translation-only paraphrase recall 0 |
| Holdout, RepositoryTools.search lexical | 10 | 0.89 | 0.89 | 34.91–39.55 ms | 53.37 ms | Same false positives and translation-only miss |

Exact-symbol and negative cases passed in both fixtures. The service-default
holdout includes "Local AI Hub installation" and a Czech query against a Czech
document; both match through shared "Local AI Hub" words and do not prove
cross-lingual semantics. "How to configure the software" has no lexical overlap
with that document and correctly exposes the missing semantic recall while the
RAG backend is disabled. Natural-query false positives show why recall alone
is insufficient. These small synthetic results do not compare healthy lexical,
RAG, hybrid, or reranker variants. The live Hub still needs a separate run
after its embedding backend and high-profile model finish preparing; the
observed live hybrid path degraded to a current-source lexical fallback.

## Remaining benchmark coverage

- A manually judged real-repository set, including Czech-to-English semantic
  queries such as `Local AI Hub installation`.
- Paired lexical, RAG, and hybrid runs, with reranker enabled and disabled.
- Actual cold and warm application-cache latency, median, and p95.
- Live HTTP/MCP boundary and running-install results, reported separately from
  synthetic fixtures.
