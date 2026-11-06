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

## Exact lexical search — 2026-11-06

Command:
`python tools/benchmark_search_quality.py --mode engine --suite holdout --repeats 3 --noise-files 1000`.
This synthetic `RepositoryTools.search(exact_count=True)` run measured recall@10
0.89 and MRR 0.89. `Local AI Hub installation` had a 169 ms median and 177 ms
p95; translation-only `How to configure the software` still had recall 0.
The fixture is not a Git checkout, so these timings do not measure Git
inventory pruning or real-repository performance.

A focused Git-backed regression fixture enumerates 1001 paths but retains and
sorts only the single ripgrep match. Git enumeration remains complete and
bounded, preserving exact counts, force-includes, and stable path ordering.
This verifies reduced candidate memory and sorting work; it does not establish
a live latency gain.

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

## Live MCP mode smoke — 2026-11-06

One actual-checkout MCP smoke queried `repo_search` lexically and
`Local AI Hub installation` in RAG and hybrid modes. The lexical response
reported 164 exact current-source matches. RAG returned 15 semantic candidates
with an explicitly inexact count. Hybrid returned a 39-item candidate union;
its 64 lexical-preprocessed candidates and 15 RAG candidates were both
explicitly inexact. `docs/INSTALLATION.md` ranked first for the natural
installation query in both RAG and hybrid output. Hybrid also surfaced test and
project metadata files, so this single query does not establish broad relevance.

Index coverage was `unknown_or_partial`; returned candidates were verified
against current sources. The reranker was requested but unavailable, and the
endpoint reported `heuristic_rerank` degradation. No latency was captured for
these calls, so this is an endpoint behavior smoke only, not a timing benchmark
or paired reranker comparison.

## GPU admission recovery and focused lifecycle checks — 2026-11-06

A live RAG index request was rejected with `gpu_reserved`. The subsequent Hub
status remained `gpu_admission_state=outcome_unknown`; no index rebuild completed.
The Ollama process reported no loaded models, which does not rule out a Torch
embedding operation.

The reservation audit records a `consented_release_current_reservation` event
at 04:50:04 UTC for owner `embedding:25292:24256`; its stored reason says the
release was authorized without owner checks. After that event, a new lease was
observed for `embedding:25292:27256` with `state=active`, a generation and an
expiry. PID 25292 was still running as a Hub Python process. The fresh active
lease and `outcome_unknown` status fail the safe GPU-admission gate. No further
release or rebuild was attempted.

Focused workspace tests passed: `tests/test_external_gpu_reservation_lifecycle.py`
(36 passed) and `tests/unit/test_mcp_gpu_reservation_release_contract.py`
(2 passed). These temporary-directory tests verify lifecycle and response
contracts; they do not establish that the installed service can safely release
or admit a live GPU reservation.

## Isolated HTTP holdout benchmark — 2026-11-06

Reproduce with:

```powershell
.\.venv\Scripts\python.exe tools/benchmark_http_search.py --repeats 7 --noise-files 1000 --suite holdout
```

This run used the script's temporary CPU-only supervisor, 1,000 synthetic noise
files, and ten manually labeled queries. The first request per query missed the
application cache; the remaining 60 requests hit it. Across cold requests,
median latency was 365.28 ms and nearest-rank p95 was 625.13 ms. Across warm
cache hits, median latency was 160.18 ms and p95 was 194.67 ms.

Eight of nine queries with relevant labels had recall@10 and MRR of 1.0. Exact
symbols `C#`, `widget::render`, and `namespace.name`, plus `while`, ranked the
expected source first. Both installation queries in English and Czech ranked
correctly. `How to configure the software` missed its expected result. The
negative `missing_quantum_driver` query had no relevant label and returned no
relevant match. This is isolated HTTP integration evidence over a synthetic
fixture; preprocessing was disabled, and it does not measure the installed
service, RAG, or reranking.
