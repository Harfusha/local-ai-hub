# T10 Windows Tree-sitter runtime proposal — 2026-10-03

## Decision and boundary

Candidate pyproject now declares an optional, pinned ast-index extra. No parser/test/root change in this continuation. T20 explicitly denied test GO earlier: T02 root selector pending; T14 selector unverified. T04 is idle, but no fresh GO arrived. No test, install, or benchmark run.

Root remains C:\Users\Adam\.local-ai-hub, HEAD 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf. T10 candidate remains C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub, HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11. Root source stays dirty/owner-controlled and was not written.

## Supported vs unsupported

- Project metadata declares Python >=3.11 and classifiers 3.11–3.14.
- Root pyproject declares no Tree-sitter runtime or optional dependency; T10 candidate now adds the ast-index optional extra.
- This host: Python 3.12 exists, but its environment lacks both pytest and tree-sitter-language-pack. Python 3.11 and bundled 3.10 also lack them.
- Python 3.13 has pytest 9.0.2 and tree-sitter-language-pack 1.18.0; however, the Hub intentionally disables all Tree-sitter on Windows/Python >=3.13 due prior native access violations. Binary wheel compatibility does not establish Hub runtime safety.
- Upstream PyPI publishes a CPython 3.10+ abi3 Windows x64 wheel for tree-sitter-language-pack 1.18.0. This establishes package artifact compatibility, not this Hub's support on Windows/Python 3.13.
- Supported acceptance proposal: isolated Windows CPython 3.12 environment with exact optional dependency tree-sitter-language-pack==1.18.0 and dev extra. Keep Java/C++ tests asserting parser availability and callers/callees; no skips or weakened expectations. Python 3.13 Windows Tree-Sitter remains unsupported until separately crash-qualified. Python generic fallback behavior is not substituted for Java/C++ Tree-sitter proof.

## Root-current dependency proposal

T10 candidate diff: artifacts/handoff/t10-ast-index-runtime-candidate-20261003.patch, SHA-256 DB4AD1D56DB8F2492C8BC8C131FFCA7CA880C8FF0FC892C9221BFE73C3F6CF5F.
Candidate pyproject SHA-256: EFEF1A48BF8E5FCDC4B0016D3E3FB688B74904C5DA75E586E29D2C116D172EA7.
Patch adds only:
    ast-index = ["tree-sitter-language-pack==1.18.0"]

Proposal patch: artifacts/handoff/t10-ast-index-runtime-proposal-root-current-20261003.patch
SHA-256: DB4AD1D56DB8F2492C8BC8C131FFCA7CA880C8FF0FC892C9221BFE73C3F6CF5F.
The identical root-current patch is at artifacts/handoff/t10-ast-index-runtime-proposal-root-current-20261003.patch. Root pyproject.toml preimage is clean at HEAD blob 9c9942b50fd40c449ce7d1008ce6884c06f54850. git apply --check against current dirty root: PASS. Patch was not applied.

Root preimage SHA-256 at inspection:
- pyproject.toml: 4E03F365D97FD475A4DFF8169725BF0C999631F3F49612E06650BAAD172899C0
- code_index.py: 83CE5601D18435FB878818E33A305CAB82A6BE00DE09B02ECA0D7EFFE3095D10
- treesitter_parser.py: CAF3D81DFC5D464F08920357745B5340F61D116513BBB16495E21F029BC52BC5
- tests/test_t10_ast_impact_acceptance.py: 3561758392D545384D1AFAB15D732743D5297124FBC0A7C6E58DB43EAFDCA75A

## Reproducible validation after serial GO

No commands below were run; they require dependency installation and a released test slot.

    py -3.12 -m venv .venv-t10-ast
    .\.venv-t10-ast\Scripts\python.exe -m pip install -e ".[dev,ast-index]"
    $env:PYTHONPATH=(Join-Path (Get-Location).Path 'src')
    .\.venv-t10-ast\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_code_index_schema_rebuild.py tests/test_t10_treesitter_parser_thread_safety.py

Acceptance: zero failures; Java, C++ and TSX fixtures execute (no skips); exact callers/callees appear; existing crash guard unchanged. Capture root HEAD and all source/test hashes immediately before and after the one authorized run.

## Current receipts and blockers

Orchestrator reports root suite 108 passed, 8 skipped, 2 failed, Java/C++ failures from parser unavailable on Windows/Python 3.13. This is parent-reported evidence; no execution ID/command supplied in this turn.

Earlier T10 candidate receipt remains distinct: 39 passed / 4.25s plus CodeGraph policy 3 passed / 0.21s, execution IDs in t10-java-cpp-callgraph-acceptance-20261003.md. It does not prove the proposed Python 3.12 runtime or root acceptance.

Official package facts: PyPI 1.18.0 lists Windows x64 cp310-abi3 (CPython 3.10+) wheel; upstream install docs require Python 3.10+. The Hub's Python 3.13 Windows guard is a stricter application safety limit.

## Fresh runtime recheck — 2026-10-03

Command:
    py -3.12 -c "import sys, importlib.util; print('python='+sys.version.split()[0]); print('pytest='+str(importlib.util.find_spec('pytest'))); print('tree_sitter_language_pack='+str(importlib.util.find_spec('tree_sitter_language_pack')))"

Result:
    python=3.12.10
    pytest=None
    tree_sitter_language_pack=None

T20's last explicit response denied GO: T02 root selector pending and T14 selector unverified. T20 is active now, but no fresh authorization has arrived. No repo-wide or venv installation; no tests run.

Exact deferred T10 selector after isolated env setup and explicit GO:
    $env:PYTHONPATH=(Join-Path (Get-Location).Path 'src'); .\.venv-t10-ast\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_code_index_schema_rebuild.py tests/test_t10_treesitter_parser_thread_safety.py

Expected acceptance remains strict: Java/C++/TSX parser fixtures execute, callers/callees match, zero failures, no skip substitution.

## Current root baseline and CodeGraph removal — read-only

Current root remains HEAD 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf; dirty owner paths preserved. Root working-source hashes:
- code_index.py: 83CE5601D18435FB878818E33A305CAB82A6BE00DE09B02ECA0D7EFFE3095D10
- treesitter_parser.py: CAF3D81DFC5D464F08920357745B5340F61D116513BBB16495E21F029BC52BC5
- defaults.toml: 418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B
- external_tools.py: EF049FB78E1E2EBE117FD128C0993E03C46F3A6D8BE0EA808B5C3F2FC7CDC1C7
- retrieval.py: 98D900595EF238E9B21A9EB569B7C70E88BADF3290EF4B702174CAB5252A90AE
- tests/test_t10_ast_impact_acceptance.py: 3561758392D545384D1AFAB15D732743D5297124FBC0A7C6E58DB43EAFDCA75A

Source markers in that same root snapshot: code_index.py maps .cpp to cpp; treesitter_parser.py has Java/C++ parser dispatch and extractors; its Windows/Python >=3.13 safety guard disables Tree-sitter. Root Java/C++ fixture asserts parser availability; it is not skip-based.

CodeGraph removal source scan: no CodeGraph markers in root defaults.toml, external_tools.py, retrieval.py, config.py or pyproject.toml. Existing guards:
- tests/test_codegraph_package_policy.py SHA-256 0B6B3838A6FB946A36CBBD0496F43131CBF196CDE531E7FA5D6F9EB024C82818
- tests/test_t19_codegraph_removal.py SHA-256 1EEE87F9F7517A2AD35CA5D10F17D4CD3D47053C2129412896F5277611EE4A06

Root acceptance suite outcome (parent-reported, not rerun here): 108 passed, 8 skipped, 2 failed; failures Java/C++ parser unavailable on Windows/Python 3.13. T20 last explicit decision denied GO; its current turn is active without a fresh GO. No root or CodeGraph test run in this continuation.

Prior candidate-only receipts remain: 39 passed / 4.25s across the seven T10 selectors; 3 passed / 0.21s for tests/test_codegraph_package_policy.py. These do not prove current root/Python 3.12 acceptance.

Root-current proposal remains dependency-only because AST/parser code and strict fixtures are already in dirty root. Exact patch DB4AD1D56DB8F2492C8BC8C131FFCA7CA880C8FF0FC892C9221BFE73C3F6CF5F, apply-check PASS, not applied.
