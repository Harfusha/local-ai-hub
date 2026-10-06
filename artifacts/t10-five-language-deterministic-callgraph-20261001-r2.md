# T10 five-extractor AST/callgraph audit r2

## Scope and static audit

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`. Root was not modified. Audit limited to five language extractors and T10 preprocess acceptance; search-owned files excluded.

| Language | Tree-sitter extraction | CodeIndex mapping | Calls edge |
|---|---|---|---|
| C# | `_extract_csharp`, `invocation_expression`, `treesitter_parser.py:268,400` | `.cs` → `csharp`, `code_index.py:1036-1050` | line 415 |
| TypeScript / JavaScript | `_extract_js_ts`, `call_expression`, `treesitter_parser.py:426,543` | `.ts` → `typescript`; `.js` → `javascript`, `code_index.py:1036-1050` | line 557 |
| Python | `_extract_python`, `call`, `treesitter_parser.py:568,664` | `.py` → `python`, `code_index.py:1036-1050` | line 678 |
| Go | `_extract_go`, `call_expression`, `treesitter_parser.py:689,798` | `.go` → `go`, `code_index.py:1036-1050` | line 812 |
| Rust | `_extract_rust`, `call_expression` / `macro_invocation`, `treesitter_parser.py:823,898` | `.rs` → `rust`, `code_index.py:1036-1050` | line 912 |

`parse_treesitter_with_status` dispatches by normalized language (`treesitter_parser.py:165-250`). `CodeIndex._parse_file_content_report` retains parser output with symbols or call edges (`code_index.py:1473-1493`). `find_callers` reads `kind='calls'` rows (`code_index.py:2972-2990`). `DeterministicEngine.query` selects the target and calls `CodeIndex.find_callers` for caller intent (`deterministic.py:1986-2006`).

## Fresh acceptance receipts

- Added `test_deterministic_caller_query_resolves_tree_sitter_edges_across_languages` at `tests/test_t10_retrieval_edges.py:107`, parametrized over C#, TypeScript, JavaScript, Go, and Rust. It indexes real fixture files and verifies deterministic caller/callee/path results.
- Command: `$env:PYTHONPATH='src'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_deterministic_caller_query_resolves_tree_sitter_edges_across_languages` — exit 0, **5 passed in 1.34s**.
- Command: `$env:PYTHONPATH='src'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_project_config_consumers.py::test_preprocess_policy_filters_inventory_and_config_digest_invalidates_cache tests/test_t10_project_config_consumers.py::test_skipped_call_graph_and_modules_resume_at_next_durable_phase` — exit 0, **2 passed in 0.58s**.
- Root-current overlay command: `$env:PYTHONPATH='src'; $env:T10_ROOT_REPOSITORY='C:\Users\Adam\.local-ai-hub'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_project_config_consumers.py::test_candidate_consumers_with_real_root_project_config` — exit 0, **1 passed in 3.74s**. Initial attempt exposed an outdated candidate test double signature; updated only the T10 test double to accept `project_settings`, then reran the same selector successfully.
- Overlay receipt imports the actual root `project_config.py` (SHA-256 `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`) and root `services.py` (SHA-256 `170a483c71e81376637a99fcb8385aa4e737e5866ba87954e1c418ebfce674aa`). Assertions confirm config digest invalidation, full inventory, blocked excluded hints, stale hint rejection, `.pyx` language selection, stale incremental-ref removal, parent and linked Gemini seed retention, and persisted linked diagnostics baseline.
- No production source, root file, search-owned file, 100k benchmark, or GPU workload changed or ran in this slice.

## SHA-256 pins

- `treesitter_parser.py`: `11a7749a8b6855bba0ced07d077ca02504d1d9d2a8bd4af5d5f13fc7a8de3382`.
- `code_index.py`: `58083fba1d64e706ac14490f04754c0e2fc765c846678dfce3005a5c5325124f`.
- `deterministic.py`: `6773cf468ced18a37b60bf5533a926924dec2f0c9480966c0dd69d27b649da99`.
- `preprocess.py`: `66b169b3de477d7074beab4bd90a52ec99ab8aa837079eca6965886200cb38e5f`.
- `tests/test_t10_retrieval_edges.py`: `326a704e4effa6785e54b442ea66cc04f9bb946638b968c58981c4776919ad5d`.
- Updated `tests/test_t10_project_config_consumers.py`: `0e1eaa31817fe21ddfa4b6cda646a7fd98a59b038216ec8dac284fa1133c918`.

T10 AST/caller and preprocess slices have fresh candidate receipts. Root T20 integration and overall T10 performance acceptance remain open.
