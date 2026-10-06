# T10 paired benchmark source pin audit

Candidate HEAD: `7a36be3b8b69531dccd9215515ac793369da0a44`.

Candidate pins independently recomputed from current worktree; exact match:
- Candidate-scoped patch fingerprint: `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc` (357864 bytes; includes consumer regression source).
- Package tree SHA-256: `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6`.
- Benchmark input SHA-256: `14d8f89f98588fecc426cad129c70c979c473f9b69b065d2bb18a6b4c7c3c11c`.

Baseline is `HEAD:src/local_ai_hub` at the same Git revision. Planned command exports source with `git archive`; archive applies Windows CRLF attributes. Therefore hash the bytes actually extracted and imported, not raw `git show` blobs.
- Extracted baseline package tree SHA-256: `06d72abb444acd036fb9fa42166d8a3bf07bfa0fbaca1f0cac57fb8e5d8f0d8c`.
- Extracted baseline benchmark input SHA-256: `aa604d041afb344ceda0ab55d6b927d2f4dc54e3aae0ff0ec082d6364873be80`.
- The previous input pin `2dcc...` matched raw HEAD blobs, not planned archive files. Previous package pin `2dabb...` matched neither raw Git blobs nor archive bytes. Schema, matrix, and reconciliation manifest now pin the bytes actually imported from archive.

Harness review: `_source_identity()` hashes exactly `tools/benchmark_t10_repository.py`, `src/local_ai_hub/code_index.py`, `repo_tools.py`, `retrieval.py`, and `treesitter_parser.py` in fixed order. Package tree pin uses `T10-PACKAGE-SOURCE-TREE-V1`, repository-relative `src/local_ai_hub/` paths, and source bytes; ignores generated `__pycache__`/`.pyc`. Candidate patch fingerprint also includes untracked `tests/test_t10_benchmark.py`. It leaves candidate patch fingerprint null when `T10_BENCH_SOURCE_ROOT` points to external baseline.

Receipt schema: Draft 2020-12; required pair identity/slot/no-competing-CPU fields, equal workload parameters, candidate and baseline source pins, complete coverage, metric samples, separate fallback and accelerator metrics, memory outside timed loops, and explicit separation from T02/T20 release acceptance. Meta-validation passes after pin correction.

Baseline import compatibility verified from extracted `HEAD:src`: legacy CodeIndex has no named cap constant and hard-codes `max_dependents` cap 100; harness reports cap 100 and still loads it. Baseline max-impact coverage is therefore expected incomplete at 100/99,999. Candidate cap is 100,000. Compare shared path-hint ranking latency and same-limit max-impact latency; do not claim full-impact speedup from the legacy-capped baseline.

Path-hint ranking now records 30-sample latency plus exact fixture ranking quality under `lookups.path_hint_ranking`; `retrieval.py` is included in both benchmark input hashes. Latest thread snapshot: T02 idle, T20 active. No 100k benchmark run; wait for T20 exclusive CPU slot. Root-current consumer package is at `handoff/t10-root-current-consumer-patch-20261001.md`.

## Exact receipt review

- Cross-checked all four candidate/baseline source pins against the JSON Schema; all match recomputation. Draft 2020-12 schema meta-validation passes.
- Required paired receipt records same workload and source pins, uncontended slot proof, exact 100k index/caller/impact coverage, every metric sample, distinct capped/full-coverage Python fallback and accelerator timeout/cooldown metrics, and memory outside timed loops. It cannot claim T02/T20 release acceptance from this local pair.
- Historical `t10-deterministic-benchmark-resumed-100k-20260930.json`: SHA-256 `687D72F9BF5550D4B7925562B3E3108DDDFCBF10A2ADBFB924C364644F9871C4`; input pin `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`, candidate fingerprint `b9caabfbd28e40d0591742a624079fd09b407a1266a7b24491617fba6a4c4700`, 281102 patch bytes.
- Historical `t10-deterministic-benchmark-resumed-p95-100k-20260930.json`: SHA-256 `B1F7AD2EF9F90E5707C8D79E23DC357255820EB3E352DC1410CF6672DE962FE8`; same old input/fingerprint, 100000/100000 indexed; not current-candidate evidence. Matrix marks old 100k timing run contaminated by concurrent T02/T15 CPU work.
- Fresh paired output files `t10-pair-candidate-100k-20261001.json` and `t10-pair-head-baseline-100k-20261001.json` do not exist. No benchmark run.

## Harness measurement review

- `_source_identity()` input order matches recomputation: current harness script, then `code_index.py`, `repo_tools.py`, `retrieval.py`, and `treesitter_parser.py`.
- Candidate auto-fingerprint covers documented tracked paths, untracked harness, benchmark test, and new project-config consumer regression; artifact-only edits do not change candidate fingerprint.
- Capped Python fallback and full-coverage Python fallback have separate calls, repeat sets, latency fields, and coverage fields. The accelerator probe is one separate call with separate timeout/cooldown counts.
- `_process_memory()` runs before the case and after all measurements; memory is outside timed loops. Cold index build has one sample, so schema requires `p95_meaningful=false` there.
- Review is static. No benchmark, pytest, or root write in this audit.
