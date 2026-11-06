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
RAG, hybrid, or reranker variants. The live Hub currently has high-profile
configuration and reranking enabled, but no models are loaded and GPU
admission is unknown. A healthy RAG/reranker run remains pending.

## Bounded hybrid fallback — 2026-11-06

Command:
`python tools/benchmark_search_quality.py --suite holdout --repeats 3 --noise-files 1000`.
This synthetic `LocalAIServices.repo_search` run disabled optional backends and
exercised the lexical fallback. The fallback now searches the project-policy
allowlist instead of stopping at an alphabetically early path prefix.

| Queries | Recall@10 | MRR | Natural-query median range | Highest per-query p95 |
| ---: | ---: | ---: | ---: | ---: |
| 10 (9 positive) | 0.89 | 0.83 | 1.14–1.28 s | 2.30 s |

The target behind unrelated paths was found. `retry sqlite` still ranked a
distractor first, and the translation-only `How to configure the software`
case still missed. This is a synthetic fallback result, not healthy RAG,
HTTP/MCP, or a real-repository measurement. The natural-query latency is a
known regression cost of searching the full allowed candidate set; further
optimization is still required.

## Remaining benchmark coverage

- A manually judged real-repository set, including Czech-to-English semantic
  queries such as `Local AI Hub installation`.
- Paired lexical, RAG, and hybrid runs, with reranker enabled and disabled.
- Actual cold and warm application-cache latency, median, and p95.
- Live HTTP/MCP boundary and running-install results, reported separately from
  synthetic fixtures.

## Live repository MCP samples — 2026-11-06

At measurement time, two single lexical requests ran against the actual checkout at
`C:\Users\Adam\.local-ai-hub` through Local AI Hub MCP. The Hub was online,
but its status reported `active_model=null` and
`gpu_admission_state=preparing_model`.

| Query | Exact matches | First relevant result | Observed MCP call time |
| --- | ---: | --- | ---: |
| `Local AI Hub installation` | 3,907 | `docs/INSTALLATION.md` | 11.77 s |
| `repo_search` | 162 | `src/local_ai_hub/services.py` | 1.00 s |

These are single observations, not latency percentiles. They do not measure the
raw HTTP route, healthy RAG, reranking, or cold/warm application-cache pairs.
The natural query's high exact-match count and latency need a repeated
controlled run after GPU admission is reconciled.

## Current runtime readiness — 2026-11-06

Hub status reports v5.1.3, NVIDIA RTX 5070 Ti with 16,303 MiB VRAM, active
hardware profile `high`, and no loaded models. The active Hub config enables
`BAAI/bge-reranker-v2-m3` through Torch on CUDA; its local Hugging Face cache
contains the config and 2.27 GB of model weights. Status reports the reranker
unloaded, and the GPU reservation is `unknown`. No model was loaded for this
benchmark. The reranker-on/off comparison remains unmeasured until admission
is safe.
