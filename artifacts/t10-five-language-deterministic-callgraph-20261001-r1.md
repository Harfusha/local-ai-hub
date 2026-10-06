# T10 five-extractor AST/callgraph audit r1

## Static audit

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`. Root was not modified.

Five Tree-sitter extractor paths converge on `calls` edges:

| Language | Parser extraction | CodeIndex extension | Evidence |
|---|---|---|---|
| C# | `_extract_csharp`, `invocation_expression`, `treesitter_parser.py:268,400` | `.cs` → `csharp`, `code_index.py:1036-1050` | emits `kind="calls"` at parser line 415 |
| TypeScript / JavaScript | `_extract_js_ts`, `call_expression`, `treesitter_parser.py:426,543` | `.ts` → `typescript`; `.js` → `javascript`, `code_index.py:1036-1050` | emits call edge at parser line 557 |
| Python | `_extract_python`, `call`, `treesitter_parser.py:568,664` | `.py` → `python`, `code_index.py:1036-1050` | emits call edge at parser line 678 |
| Go | `_extract_go`, `call_expression`, `treesitter_parser.py:689,798` | `.go` → `go`, `code_index.py:1036-1050` | emits call edge at parser line 812 |
| Rust | `_extract_rust`, `call_expression` / `macro_invocation`, `treesitter_parser.py:823,898` | `.rs` → `rust`, `code_index.py:1036-1050` | emits call edge at parser line 912 |

`parse_treesitter_with_status` dispatches by normalized language key (`treesitter_parser.py:165-250`). `CodeIndex._parse_file_content_report` keeps parser output when it contains symbols **or** call edges (`code_index.py:1473-1493`). `find_callers` queries only `kind='calls'` rows (`code_index.py:2972-2990`). `DeterministicEngine.query` selects the target symbol and calls `CodeIndex.find_callers` for caller intent (`deterministic.py:1986-2006`).

Existing direct Tree-sitter edge fixture covers all five extractors, TSX variants, and Java/C++ fallback cases (`tests/test_t10_retrieval_edges.py:160-200`). Before this delta, the end-to-end deterministic caller fixture exercised Python only (`tests/test_t10_retrieval_edges.py:59-94`).

## Added regression and validation

- Added `test_deterministic_caller_query_resolves_tree_sitter_edges_across_languages` at `tests/test_t10_retrieval_edges.py:107`, parameterized for C#, TypeScript, JavaScript, Go, and Rust. It indexes real fixture files, queries deterministic caller intent, and checks the returned caller/callee/path edge.
- Exact selector command: `$env:PYTHONPATH='src'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_deterministic_caller_query_resolves_tree_sitter_edges_across_languages`.
- Result: exit 0; **5 passed in 1.34s**.
- Preprocess selectors: `test_preprocess_policy_filters_inventory_and_config_digest_invalidates_cache` and `test_skipped_call_graph_and_modules_resume_at_next_durable_phase`; exit 0, **2 passed in 0.58s**.
- No production source edits, root tests, 100k benchmark, or GPU work in this slice.

## SHA-256 pins

- `treesitter_parser.py`: `11a7749a8b6855bba0ced07d077ca02504d1d9d2a8bd4af5d5f13fc7a8de3382`.
- `code_index.py`: `58083fba1d64e706ac14490f04754c0e2fc765c846678dfce3005a5c5325124f`.
- `deterministic.py`: `6773cf468ced18a37b60bf5533a926924dec2f0c9480966c0dd69d27b649da99`.
- Updated `tests/test_t10_retrieval_edges.py`: `326a704e4effa6785e54b442ea66cc04f9bb946638b968c58981c4776919ad5d`.
- `tests/test_t10_project_config_consumers.py`: `478aac65426603f0bca73eaff96121f4b6ab8edc93d1478431e83b39dcc7dff0`.

This closes the missing candidate deterministic e2e slice. Root T20 integration and full T10 performance acceptance remain open.
