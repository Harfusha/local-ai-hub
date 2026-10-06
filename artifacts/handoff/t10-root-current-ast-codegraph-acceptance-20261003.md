# T10 root-current AST / CodeGraph handoff — 2026-10-03

## Scope and decision

Root: C:\Users\Adam\.local-ai-hub, HEAD 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf. Root has dirty T10/T19 owner paths; all preserved. No root writes.

Java/C++ extractors, .cpp CodeIndex map and strict Java/C++ caller/callee fixture already exist in the current dirty root. Windows/Python >=3.13 guard also exists and deliberately disables the native Tree-sitter package due prior access violations. Do not move/remove this guard or weaken/skip Java/C++ assertions. CodeGraph remains removed from Hub integrations; no source hunk needed for those existing root changes.

Only root-current patch needed to make supported-runtime acceptance reproducible: optional dependency pin.

## Exact root-current patch

File: C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub\artifacts\handoff\t10-ast-index-runtime-proposal-root-current-20261003.patch
SHA-256: DB4AD1D56DB8F2492C8BC8C131FFCA7CA880C8FF0FC892C9221BFE73C3F6CF5F

Hunk adds only:
    ast-index = ["tree-sitter-language-pack==1.18.0"]

Root pyproject preimage SHA-256: 4E03F365D97FD475A4DFF8169725BF0C999631F3F49612E06650BAAD172899C0
Root HEAD pyproject blob: 9c9942b50fd40c449ce7d1008ce6884c06f54850
git apply --check --whitespace=error: PASS. Patch not applied.

## Parser/index and guard evidence

- src/local_ai_hub/code_index.py SHA-256 83CE5601D18435FB878818E33A305CAB82A6BE00DE09B02ECA0D7EFFE3095D10. .cpp maps to cpp.
- src/local_ai_hub/treesitter_parser.py SHA-256 CAF3D81DFC5D464F08920357745B5340F61D116513BBB16495E21F029BC52BC5. Dispatches Java/C++; _extract_java and _extract_cpp present. Windows Python >=3.13 guard remains before native imports.
- tests/test_t10_ast_impact_acceptance.py SHA-256 3561758392D545384D1AFAB15D732743D5297124FBC0A7C6E58DB43EAFDCA75A. Contains Java, C++, TSX fixtures and hard availability assertions for Java/C++; no weakening or skip for those languages.
- Root source preimage hashes: defaults.toml 418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B; external_tools.py EF049FB78E1E2EBE117FD128C0993E03C46F3A6D8BE0EA808B5C3F2FC7CDC1C7; retrieval.py 98D900595EF238E9B21A9EB569B7C70E88BADF3290EF4B702174CAB5252A90AE.

## CodeGraph absence evidence

Read-only scan found no CodeGraph markers in root defaults.toml, external_tools.py, retrieval.py, config.py or pyproject.toml.
Existing unchanged test guards:
- tests/test_codegraph_package_policy.py SHA-256 0B6B3838A6FB946A36CBBD0496F43131CBF196CDE531E7FA5D6F9EB024C82818
- tests/test_t19_codegraph_removal.py SHA-256 1EEE87F9F7517A2AD35CA5D10F17D4CD3D47053C2129412896F5277611EE4A06

## Test handoff

No root tests run; no T20 GO in current evidence. Orchestrator-reported full root suite remains 108 passed, 8 skipped, 2 failed; Java/C++ failures correspond to parser unavailable under Windows Python 3.13. This is not an independent receipt.

After a dedicated Windows Python 3.12 venv with dependencies and explicit T20 GO, run:

    py -3.12 -m venv .venv-t10-ast
    .\.venv-t10-ast\Scripts\python.exe -m pip install -e ".[dev,ast-index]"
    $env:PYTHONPATH=(Join-Path (Get-Location).Path 'src')
    .\.venv-t10-ast\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_code_index_schema_rebuild.py tests/test_t10_treesitter_parser_thread_safety.py tests/test_codegraph_package_policy.py tests/test_t19_codegraph_removal.py

Acceptance: zero failures; Java/C++/TSX caller-callee cases execute, Java/C++ do not skip, CodeGraph removal selectors pass. Capture root HEAD and every listed preimage hash before/after.

No install, test, benchmark, root edit, or CodeGraph reintegration performed in this handoff.
