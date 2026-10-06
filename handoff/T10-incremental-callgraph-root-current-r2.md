# T10 callgraph delta r2: root-current proof

## Scope

Candidate worktree `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`. Root remained read-only. No Hub, search-policy/T21 edits, CodeGraph, 100k benchmark, or GPU run.

## Tests and results

New self-contained `tests/test_t10_incremental_callgraph_edges.py` covers five Tree-sitter languages (C#, TypeScript, JavaScript, Go, Rust) through `CodeIndex.update_files_batch` and both callers/callees APIs, stale-edge removal after batch rename/delete, plus deterministic SQL ordering and `LIMIT` bounds.

- Candidate green: `python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_incremental_callgraph_edges.py` — **7 passed in 0.63s**.
- Root-current baseline: copied only the new test file to `%LOCALAPPDATA%\Temp\t10-root-current-acceptance`; ran `python -B -m pytest -q -s -p no:cacheprovider --tb=short -c C:\Users\Adam\.local-ai-hub\pyproject.toml C:\Users\Adam\AppData\Local\Temp\t10-root-current-acceptance\test_t10_incremental_callgraph_edges.py` from the root. Root `local_ai_hub.code_index` origin was independently printed as `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\code_index.py`. Result: **6 passed, 1 failed**. Failure is the regression: after batch rename, `find_callers("old_target")` still returns the old edge. Five language caller/callee cases and SQL-bound test pass on root baseline.
- Root-current handoff: `git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub\handoff\T10-incremental-callgraph-root-current-r1.patch` — exit 0; check did not write root files.
- Earlier accepted evidence: [five-language/preprocess audit r2](../artifacts/t10-five-language-deterministic-callgraph-20261001-r2.md) has 5 caller selector passes, 2 preprocess selector passes, and 1 root-current config overlay pass. Those selectors were not repeated.

## Fix and origin

Candidate `CodeIndex.update_files_batch` now removes absent in-root paths from `files`, `symbols`, `refs`, and `edges` through the existing bounded cleanup helper. Patch targets actual current root `src/local_ai_hub/code_index.py`, SHA-256 `6391647e32a21e0a20a0caa253f80eb62fe6e009158272cb08090fb1cc12a3a4`; root's batch implementation currently skips nonexistent paths without cleanup. T13 was informed; this does not modify `preprocess.py`.

- Root-current patch `handoff/T10-incremental-callgraph-root-current-r1.patch`: SHA-256 `6353cd4e47bdfa5a1a128b345ea2c9f83e5eb055c5b40b2a3a375df6ffb14483`.
- Candidate `src/local_ai_hub/code_index.py`: SHA-256 `85f86d79040d72e07d36b687f928b80ffe877a96909fba2a3019e007ab7753da`.
- Candidate new test `tests/test_t10_incremental_callgraph_edges.py`: SHA-256 `43d58634da5762e060db1e7d321f4949163e85f37c6eb91da8d25ca4cbc010a8`.

T20 owns applying/integrating this delta. Overall T10 and root release acceptance remain open.
