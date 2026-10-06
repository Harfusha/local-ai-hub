# T10 continuation evidence — 2026-10-03

## Ownership and pins

- Candidate: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `360a58f90d0d6562641e62d15095410fc5dd044a`; dirty tree preserved.
- Root working-file SHA-256: `repo_tools.py` `360734CEB316A8A9FC698C19C1098D88FC591170DBBF5F3B67DB6608CD3A6A36`; `defaults.toml` `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`; `code_index.py` `73BE2A44010E3EF9BA8367CAC7C99D1DBA4F2DEB7DFA3EACD4A2D4FE361BC00B`.
- Candidate working-file SHA-256: `repo_tools.py` `6C43F6FA7B067856E4543833EF79C2195FFEACC8C900EB0988AFDE16392E527B`; `defaults.toml` matches root; `code_index.py` `23634057D2C4FA1EE4C737AD9F2AA1B04E8674FAE32ADAB282C00FECD1B33FF5`.

## Root-current decision

No source patch needed for this request: root already has `python_fallback_max_files`, `python_fallback_files_scanned`, `python_fallback_file_limit`, and separate `ripgrep_timeout_seconds`. Candidate/root defaults are byte-identical. Root `code_index.py` differs and is dirty; candidate copy must not replace it. No root writes made.

## Acceptance evidence

- Existing deny/exclude fixture: `tests/test_t10_repo_search_path_hints.py::test_repo_search_prioritizes_request_and_config_hints_without_narrowing` checks that a configured include override and request hint do not restore `secret/**` excluded content.
- `::test_repo_search_hints_cannot_restore_excluded_or_outside_results` feeds allowed, hard-denied, excluded, and `../outside.php` rows through hints; only the allowed path survives.
- Callers/callees selectors exist in `tests/test_t10_ast_impact_acceptance.py` and `tests/test_t10_fallback_callgraph_parity.py`.
- Historical candidate-only receipt: 26 passed in 11.53s for `test_t10_code_index_schema_rebuild.py`, `test_t10_fallback_callgraph_parity.py`, `test_t10_ast_impact_acceptance.py`, and `test_t10_treesitter_parser_thread_safety.py`. Not a current root receipt; Python-budget and path-hint modules were not in that command.

## Open acceptance

- No tests or benchmark run in this continuation.
- T20 remains `systemError`; message dispatch failed because no active turn; no fresh serial GO.
- T02 owns the 100k `hub_impact_latency` benchmark. Latest T02 handoff reports no accessible managed checkout; no authoritative pins or assigned slot. p95 and separately measured memory remain unverified.
- No speedup claim. Goal remains blocked.
