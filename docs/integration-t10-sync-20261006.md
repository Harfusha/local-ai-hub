# T10 committed synchronization handoff

Scope: only `C:/Users/Adam/.codex/worktrees/t10-path-hints/.local-ai-hub`.
Branch: `codex/sync-t10-path-hints-20261006`.
Exact changed-file manifest versus pinned master: [integration-t10-sync-20261006-files.txt](integration-t10-sync-20261006-files.txt).
Native fallback explicitly authorized by the user after a terminal Hub failure;
no Hub retry, polling, new worktree, root checkout edit, master update, or push.

## Recovery and pinned merge input

- Original dirty checkpoint / original HEAD: `4e34d3a9cc35aa6638bf09c64e2718c7b5ac122f`.
- Original recovery ref: `refs/checkpoints/t10-sync-original-20261006`.
- Remaining ordinary untracked checkpoint: `19a97f4c`; 75 files, including eight
  unfinished test files and 67 handoff documents, receipts, and patches.
- Complete pre-merge recovery ref: `refs/checkpoints/t10-sync-dirty-20261006`.
- Master inspected once and pinned: `3c23c33d76c43043d839642c7b0d3e10ea444d67`.
- Pinned ref: `refs/checkpoints/t10-sync-master-20261006`.
- User-supplied `419474e4` is an ancestor of this pinned master.
- Concurrent master movement is deliberately not chased. Central fast-forward
  remains for the central owner; this task does not modify master.

## Merge decisions

Ten conflicted paths were reviewed by behavior. No blanket ours/theirs merge.
Keep master project receipt validation, project-aware bounded search, literal
SQL wildcard escaping, SQL table whitelists, and Windows Python 3.13 native
Tree-sitter import prohibition. Retain T10 constructor call ownership, parser
initialization lock, Java/C++ extractors, optional pinned AST dependency, and
additional concurrency/wildcard/negative-hint tests. Use master's `repo_search`
default scope, confirmed by the focused test rerun.

Master preprocessing and HTTP app source are unchanged relative to the pin;
the requested newer preprocessing is imported intact. Retired CodeGraph runtime
is not reintroduced. Historical CodeGraph-named handoffs are recovery evidence,
not active runtime code. Install/update prompts are also unchanged versus pin.
No `/api/context/pack` redesign; T14 retains ownership.

## Actual targeted checks

Python: `C:/Python313/python.exe`. Initial targeted pytest command:

```text
python -m pytest -q --tb=short -p no:cacheprovider --basetemp=.t10-sync-validation/pytest-temp tests/test_t10_ast_impact_acceptance.py tests/test_t10_code_index_schema_rebuild.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_python_fallback_budget.py tests/test_t10_repo_search_path_hints.py tests/test_t10_retrieval_fixture_matrix.py tests/test_t10_treesitter_parser_thread_safety.py tests/test_t10_treesitter_runtime_contract.py tests/test_project_config.py tests/test_project_path_hints.py tests/test_repo_tools_path_hints.py tests/test_project_verification_rules.py tests/test_agent_verification.py tests/test_preprocess_operational_mode.py tests/test_t10_preprocessor_index_version.py
```

Result: **225 passed, 6 failed, 10 skipped, 47.07 s**. One failure was the merge
scope choice, corrected to master behavior. Focused recheck of
`tests/test_t10_repo_search_path_hints.py`: **5 passed, 0.86 s**. The entire
selection was not rerun after that correction; do not claim a new aggregate.
AST syntax parsing passed for the three source files reviewed during the merge.
Pinned-master diff whitespace check passed with `core.whitespace=cr-at-eol`.
An earlier whole-merge cached check reported inherited whitespace noise; it is
not a clean release receipt. No full release suite, installation, or live model
validation. Validation temp/state and bytecode stayed inside the assigned
checkout (bytecode disabled); `.t10-sync-validation` contents are ignored.
Token-economizer bounded reads influenced the review; its setup helper was
missing, so no packages or PATH were changed. Subagent capacity was exhausted;
all integration remained with the main agent.

## Remaining incomplete behavior

1. `test_windows_python_313_uses_available_language_pack_for_java_and_cpp`
   contradicts retained master safety guard. Preserve unfinished test; Windows
   native Java/C++ AST acceptance is not proved. Ten native-parser cases skipped.
2. `test_context_pack_expands_only_bounded_hint_directory_with_exclusions`:
   expected allowed PHP evidence absent; ignored-directory evidence present.
3. `test_context_pack_directory_expansion_obeys_file_cap`: scanned count 0, expected 2.
   Both context-pack regressions remain T14-owned; no redesign here.
4. `test_project_completion_forwards_config_and_task_generation_to_t09_store`:
   fixture rejects `configured_commands` with `TypeError`.
5. `test_http_task_completion_uses_persisted_project_receipts`: HTTP 400.
   Verification adapter and HTTP app match pinned master; no gate weakening.

Old handoff receipts are preserved but are not fresh acceptance. This branch is
prepared for central integration with the explicit incomplete checks above.
