# T10 root-current integration handoff — 2026-10-02

Candidate: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Root not edited. Both worktrees have dirty state; hashes and ownership map are in [JSON manifest](t10-root-current-handoff-20261002.json).

## Integration finding

Current root already contains T10 behavior: analyzer/fallback call graph, cache freshness and stale-file cleanup, bounded impact queries, content-hash preprocess refresh, separate Python fallback file cap/metrics, independent ripgrep timeout, plus bounded path-hint priority. Root implementation has newer T20/T21 changes. No candidate-only behavior found in the bounded comparison. Do not apply archived T10 patches or overwrite root files with candidate copies.

Candidate/root defaults files match byte-for-byte. Candidate AST, fallback-callgraph, Python-budget, and retrieval fixtures match root after newline normalization; callgraph and retrieval tests are already tracked at root. Root has untracked AST and Python-budget test copies. Root path-hint test adds a positive default-scope fixture absent from candidate; preserve that root copy.

## Exact T10-owned paths

`defaults.toml`, `src/local_ai_hub/defaults.toml`, `src/local_ai_hub/code_index.py`, `src/local_ai_hub/preprocess.py`, `src/local_ai_hub/repo_tools.py`, `tests/test_t10_ast_impact_acceptance.py`, `tests/test_t10_fallback_callgraph_parity.py`, `tests/test_t10_python_fallback_budget.py`, `tests/test_t10_repo_search_path_hints.py`, `tests/test_t10_retrieval_fixture_matrix.py`.

T21-owned project configuration, service, agent, and project-path test edits are excluded. Test path-hint coverage overlaps T21 service consumers; root copy has broader fixture coverage.

## Evidence and open acceptance

Candidate-only T10 selector set passed **28/28 in 3.37s**. No root tests run for this handoff. Performance acceptance stays **RED**: T02/T15 paired 100k command and slot not yet validated; no benchmark run here. CodeGraph standalone runtime and clean-host release checks remain unverified under T19 ownership. HUB not used per user direction.
