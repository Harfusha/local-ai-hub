# T10 Java/C++ callers and callees — 2026-10-03

## Scope and pins

- Candidate only: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root unchanged: HEAD `360a58f90d0d6562641e62d15095410fc5dd044a`; existing dirty paths preserved.
- CodeGraph sources were not edited; the package-policy regression selector passed.

## Change

- `code_index.py`: map `.cpp` to `cpp`; keep `.tsx` mapped to `typescript`.
- `treesitter_parser.py`: report Java/C++ parser availability; dispatch Java/C++ grammars; extract Java type/method symbols and `method_invocation` edges; extract C++ namespace/class/function symbols and `call_expression` edges.
- `test_t10_ast_impact_acceptance.py`: add TSX, Java, and C++ caller/callee fixtures; pin `.cpp` and `.tsx` CodeIndex mappings.
- Existing schema, edge shape, and CodeGraph behavior unchanged.

## SHA-256

- Candidate `code_index.py`: `4E1705AFC4AD8E116F25619A520E7B14BE88F1FE4386F3D9DD2C2493085F7A31`.
- Candidate `treesitter_parser.py`: `A1EBABA873BA85408CAAE9AC7FF12CBABFB44E0D5EB190C991C7D18A7EF129C7`.
- Candidate acceptance test: `3E9367414B88A1753D22291EEE2A5823CDB1F77A03E8E588DF66AC6283EC37F2`.
- Candidate cumulative tracked-source diff: `artifacts/handoff/t10-java-cpp-candidate-source-20261003.patch`, SHA-256 `3F090E386F1476051718153BFAECB9C322704FF8CE2D0CA957DE7246D2620E96`. Includes inherited candidate edits; not a root-current patch.
- Acceptance-test delta: `artifacts/handoff/t10-java-cpp-acceptance-test-20261003.patch`, SHA-256 `1502FA7B2D23A3E3A1EDA83491E6EA8B654510D951A08871C476EED3E749C00A`.

## Verification

RED: `$env:PYTHONPATH=(Join-Path (Get-Location).Path 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py -k 'tree_sitter_language_edges or code_index_maps_cpp'` — 3 failed, 6 passed, 6 deselected. Failures exposed Java/C++ availability and `.cpp` mapping gaps.

GREEN: `$env:PYTHONPATH=(Join-Path (Get-Location).Path 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_code_index_schema_rebuild.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_ast_impact_acceptance.py tests/test_t10_treesitter_parser_thread_safety.py tests/test_t10_retrieval_fixture_matrix.py tests/test_t10_python_fallback_budget.py tests/test_t10_repo_search_path_hints.py` — **39 passed in 4.25s**.

CodeGraph guard: `$env:PYTHONPATH=(Join-Path (Get-Location).Path 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_codegraph_package_policy.py` — **3 passed in 0.21s**.

`git diff --check -- src/local_ai_hub/code_index.py src/local_ai_hub/treesitter_parser.py` — passed. All receipts are candidate-only; no root tests ran.

## Open acceptance

100k retrieval/callers/impact performance receipt remains T02-owned. T20 still has `systemError` and no fresh GO; latest T02 handoff reports no accessible managed checkout or authoritative benchmark pins. p95 and separately measured RSS remain unverified. No performance claim. Existing T10 goal remains blocked pending this evidence and integrated root acceptance.

## Root-current comparison — read-only

- Root HEAD at comparison: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root preimages: `code_index.py` `73BE2A44010E3EF9BA8367CAC7C99D1DBA4F2DEB7DFA3EACD4A2D4FE361BC00B`; `treesitter_parser.py` `B59385891568BDAC0D68D132ED193DAF7A0FFDE71905267896E7CB70A4A8FF2B`; acceptance test `B300FB05514EC5DAF7078AADDFE84235D20EC059104DF8323B4DAE6A8049219D`.
- Root lacks `.cpp` mapping and Java/C++ availability/dispatch/extractors. Existing Tree-sitter lock and Windows fallback remain untouched by this minimal root-current patch.
- [Root-current patch](/C:/Users/Adam/.codex/worktrees/t10-path-hints/.local-ai-hub/artifacts/handoff/t10-java-cpp-root-current-20261003.patch) SHA-256 `C69FBB2367C8347F043024F831F82FDBE82DDE7B05171D2C458937068F1BEC76`.
- `git -C C:\Users\Adam\.local-ai-hub apply --check ...` — **PASS** against the dirty root working tree and HEAD above. No patch applied; no root writes.
- Root acceptance tests were not run: T20 remains `systemError`, with no fresh GO. Candidate receipts above remain the only test evidence.

## Command execution IDs

- T10 regression/golden/impact: `exec-6356591a-32ea-4b79-88c6-83d071c318a1` — 39 passed / 4.25s.
- CodeGraph package policy: `exec-cf186040-8f2f-4308-b65b-93445ba8f40b` — 3 passed / 0.21s.
- Java/C++/TSX focused acceptance: `exec-28ad362d-dc55-4e42-ab67-eca025cfa01d` — 9 passed / 0.76s.
- TDD red baseline: `exec-8f0063b2-005d-4f93-ab8e-26301a91bb30` — 3 failed, 6 passed, 6 deselected / 0.83s.
