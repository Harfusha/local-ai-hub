# T10 AST / bounded impact acceptance r1

## Scope and provenance

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`, branch labels `codex/t21-project-config` / `codex/t16-orchestration-recovery`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Existing worktree had six dirty tracked files and two untracked paths before this T10 slice. The inherited manifest `artifacts/handoff/t10-repo-search-path-hints-manifest.json` distinguishes its prior T10 files from T21/config inheritance. This slice leaves `project_config.py`, `services.py`, `tool_agent.py`, `/api/context/pack`, T09 receipt tests, and benchmark suites untouched.

The prior `t10-repo-search-path-hints` handoff is excluded from this T10 slice: it edits public path-hint consumers in `services.py` / `tool_agent.py`, now assigned to T21. No T09 Agent OS verification or benchmark work was moved into the new T10 test.

## Acceptance tests and findings

New file `tests/test_t10_ast_impact_acceptance.py` covers:

- C#, TypeScript, JavaScript, Go, and Rust fixture source through parser → SQLite → `find_callers` and `find_callees`.
- `kind='calls'` filtering, so import edges cannot appear as caller/callee results.
- incremental batch rename and delete removing stale caller/callee edges.
- bounded impact for 1,200 changed paths: three path chunks of at most 400, 12 symbol rows, graph query limit 200, at most seven returned dependents.

The fail-first candidate run exposed two defects: call queries returned an `imports` edge, and a renamed file retained an old caller edge. Candidate `src/local_ai_hub/code_index.py` now adds the call-edge filter plus Rust `::` suffix matching and removes absent in-root paths from `files`, `symbols`, `refs`, and `edges` in the batch transaction.

## Validation receipts

- Candidate T10 selector: `python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py` — **8 passed in 0.87s**.
- Existing adjacent regressions: `python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_preprocessing_overhaul.py::test_code_index_find_callers_and_callees tests/test_reliability_integration.py::test_code_index_impact_batches_large_changed_file_sets tests/test_cross_repo_federation.py::test_cross_repo_symbol_find_and_impact` — **3 passed in 2.65s**.
- Current root source origin was printed as `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\code_index.py`. Copied only the candidate test into a temp directory, used root `pyproject.toml`, and ran it against root imports — **8 passed in 11.20s**. No root file was written.
- Root-current strict patch check: `git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub\artifacts\handoff\t10-ast-impact-acceptance-root-current-r1.patch` — exit 0.

## Root-current ownership and pins

Current root HEAD is `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; root is dirty and remains T20-owned. Its current `code_index.py` already contains the batch absent-path cleanup and callers/callees `kind='calls'` plus `::` suffix filters, so the handoff patch adds only the test file and does not duplicate production changes.

- Root `src/local_ai_hub/code_index.py`: SHA-256 `6eb54f264f156e1dcd7d4b8e1dab3eeb15227273a05a83b5b62cb3e8f43b7598`.
- Root `src/local_ai_hub/treesitter_parser.py`: SHA-256 `23c5f647ec3ba3fd545b7f8e8b5ae59b781f317287b1b539fe8e0a06345cc57f`.
- Candidate `src/local_ai_hub/code_index.py`: SHA-256 `10d5b9dc22ba7e73b4c85e2705445f96b5b180015f75035eb7ad705bc2b2b470`.
- Candidate `tests/test_t10_ast_impact_acceptance.py`: SHA-256 `54f22e3ae8d3d664b385b9ae6bb2c68c10e7eb3791af2a31626dea12422846ef`.
- Test-only root patch `artifacts/handoff/t10-ast-impact-acceptance-root-current-r1.patch`: SHA-256 `931c0e5388aa3dce114acc9681d0826e3f68d5419dcaa0970d8344fbafcd392a`.

Root/current source already supplies the behavior; T20 only needs to review/apply the test-only delta. Broader T10 latency/coverage matrix remains open.
