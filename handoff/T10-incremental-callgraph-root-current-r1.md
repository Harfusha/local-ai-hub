# T10 incremental callgraph delta r1

## Scope

Candidate: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`. Root `C:\Users\Adam\.local-ai-hub` was read-only. No Hub, CodeGraph, 100k benchmark, GPU run, or preprocess edit.

## Finding and fix

`CodeIndex.update_files_batch` skipped paths whose files were absent. A batch containing a renamed or deleted file therefore left its old `files`, `symbols`, `refs`, and `edges` rows in SQLite. The T10 candidate now records absent in-root paths and removes those rows through `_remove_indexed_paths`.

Added focused tests for batch rename/delete cleanup across both `find_callers` and `find_callees`, and for stable path ordering plus SQL `LIMIT` in both graph queries. The bounded query test passed before the production fix; the first valid rename run failed on stale `old_target` caller evidence.

## Validation

- Fail-first command: `$env:PYTHONPATH='src'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_incremental_file_rename_and_delete_clear_caller_and_callee_edges tests/test_t10_retrieval_edges.py::test_caller_and_callee_queries_are_ordered_and_sql_bounded` — **1 failed, 1 passed**; stale caller edge after rename.
- Green command: `$env:PYTHONPATH='src'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_incremental_file_rename_and_delete_clear_caller_and_callee_edges tests/test_t10_retrieval_edges.py::test_caller_and_callee_queries_are_ordered_and_sql_bounded tests/test_t10_retrieval_edges.py::test_call_graph_queries_honor_large_explicit_result_limits` — **3 passed in 0.55s**.
- Root-current patch check: from `C:\Users\Adam\.local-ai-hub`, `git apply --check 'C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub\handoff\T10-incremental-callgraph-root-current-r1.patch'` — exit 0; no root files changed.
- Prior accepted evidence remains in `artifacts/t10-five-language-deterministic-callgraph-20261001-r2.md`: five language caller cases **5 passed**, preprocess selectors **2 passed**, root-current project-config overlay **1 passed**. Not repeated.

## Root-current origin and pins

The patch targets current root `src/local_ai_hub/code_index.py`, SHA-256 `6391647e32a21e0a20a0caa253f80eb62fe6e009158272cb08090fb1cc12a3a4`. It adds a new test file rather than overwriting root tests.

- Root-current delta: `handoff/T10-incremental-callgraph-root-current-r1.patch`, SHA-256 `e2896cdcfb95f64f19a34852dd246a38d31c0d2818c43a2999c324a1ad6b2610`.
- Candidate `src/local_ai_hub/code_index.py`, SHA-256 `85f86d79040d72e07d36b687f928b80ffe877a96909fba2a3019e007ab7753da`.
- Candidate `tests/test_t10_retrieval_edges.py`, SHA-256 `168fc8c38f9cd22ba416ce51989650a0437902739abe8c15053d1f93ef2263af`.

T13 coordination request was sent before the implementation edit. Its current work is operational-mode release coverage; no preprocess overlap was identified. Overall T10 acceptance and T20 root integration remain open.
