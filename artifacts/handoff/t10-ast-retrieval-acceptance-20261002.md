# T10 AST/retrieval acceptance — 2026-10-02

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

## Test receipt

Command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_python_fallback_budget.py tests/test_t10_repo_search_path_hints.py tests/test_t10_retrieval_fixture_matrix.py tests/test_adaptive_retrieval.py tests/test_repo_topology.py tests/test_affected_tests.py tests/test_cross_repo_federation.py
```

Result: **48 passed in 4.19s**, exit 0. Candidate only; no root tests. File and source hashes: [JSON receipt](t10-ast-retrieval-acceptance-20261002.json).

Coverage includes AST and fallback call edges across declared languages, stale-cache and rename/delete invalidation, bounded impact, adaptive backend timeout/degradation and evidence coverage, repo topology, affected tests, cross-repo symbols/impact, OpenAPI/invariant retrieval, dead-code exclusions, path-hint policy, Cargo and Go framework fixtures.

## Still open

T10 semantic AST/retrieval selectors now pass. Full T10 remains open: paired 100k performance receipt and p95/separate-memory matrix remain T02-owned; CodeGraph standalone runtime and clean-host checks remain T19-owned. No benchmark or CodeGraph runtime was run here. No source edits; inherited T10/T21 dirty changes preserved.
