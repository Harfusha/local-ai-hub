# T10 root-safe call-suffix escape handoff

## Scope

Patch contains only:

- `src/local_ai_hub/code_index.py`: `CodeIndex.find_callers` and `CodeIndex.find_callees`; literal escaping for SQL LIKE metacharacters (`!`, `%`, `_`), call-edge filter, and `/` plus Rust `::` suffix lookup.
- `tests/test_t10_like_suffix_escape.py`: regression for literal `_`, `%`, and `!` suffixes, including false-positive rows.

No project config, resolver, service, RAG, `/api/context/pack`, or other T21/T11-owned path is included.

## Patch identity

- Patch: `artifacts/t10-like-suffix-escape-root.patch`
- SHA-256: `FE6C42977860205E43115CDB2370132920BD5F6D387F9FF097712DCE7A20F227`
- Candidate branch/HEAD: `codex/t10-resume-20260926` / `7a36be3b8b69531dccd9215515ac793369da0a44`
- Historical T10 commits: `08bca282d2ada4ec34bd29b5761ea00ea996c87f` and `5aa3fe0761361ae74dbfe3f7f6b6b5875a6088f0` (commit identities recorded from branch history; patch is isolated from full commits).

## Current root preconditions

- Root: `C:/Users/Adam/.local-ai-hub`, branch `master`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- `src/local_ai_hub/code_index.py` is already dirty in root; working-tree blob at handoff: `e5b61a91d3bbf222db077cdc3fa8208bf99804c4`.
- Current root `find_callers`/`find_callees` use unescaped `LIKE` suffixes and lack the T10 literal wildcard regression.
- `git apply --check` against current root working tree succeeded; no root files changed.

## Existing validation receipt

- T10 focused regression is parameterized over `_`, `%`, and `!`; it is part of the final T10 acceptance command in `artifacts/t10-acceptance-reconciliation.manifest.md`.
- Exact command:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_acceptance.py tests/test_t10_retrieval_edges.py tests/test_adaptive_retrieval.py tests/test_affected_tests.py tests/test_repo_topology.py tests/test_t10_transitive_dependencies.py tests/test_t10_benchmark.py tests/test_t10_snapshot_cache_capacity.py tests/test_affected_tests_no_code_index.py tests/test_preprocess_operational_mode.py tests/test_codegraph_package_policy.py tests/test_cross_repo_federation.py tests/test_performance.py tests/test_repo_tools.py
  ```

- Result: `216 passed, 2 skipped in 40.44s`; skips are unavailable Java/C++ Tree-sitter grammars. The SQL wildcard regression is in `tests/test_t10_retrieval_edges.py`. No raw `.log` was retained; reconciliation manifest SHA-256 `2A2FB9CF5DE55244E615FB8B257B62FF2B5A720A0F87E726A56359535FB7AAB3` binds this receipt.
- User-reported root path-hint suites: `32/32` green; separate coverage, not this SQL regression.

## Integration boundary

Patch is a source-level net hunk only; do not cherry-pick the full historical T10 commits because they overlap already-covered root AST/CodeGraph changes. T10 CodeGraph replacement/removal behavior is already covered in current root content. This SQL suffix escaping remains missing. No patch has been applied to root.

