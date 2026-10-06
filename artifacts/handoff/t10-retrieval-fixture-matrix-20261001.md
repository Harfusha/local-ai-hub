# T10 retrieval fixture matrix handoff — 2026-10-01

## Newly covered gaps

- Dead-code fixture now checks one truly unreferenced symbol and excludes `main`, a called helper, and a test-file symbol.
- Affected-test fixture now covers all five frameworks detected by the current source: pytest, dotnet, npm, cargo, and go. It checks exact selected paths and commands.
- Lexical search fixtures cover an OpenAPI YAML operation and an invariant JSON statement, each with exact path results.
- Built-in fallback callgraph parity now includes Java and PHP, whose extensions map to the generic parser.

## Validation and handoff

- Focused command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_retrieval_fixture_matrix.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_ast_impact_acceptance.py tests/test_t10_python_fallback_budget.py tests/test_affected_tests.py`
- Result: **26 passed in 3.28s**.
- Root `git apply --check` passed for the attached patch. No root files were changed by this task.
- Patch SHA-256: `89F5EC77F0230E4AEB3C47B8E7A081441EC5451849CC334CB7D9B020BF8EE95B`
- Changed test file SHA-256 values are recorded in the JSON receipt.

## Remaining T10 limits

No 100k benchmark ran; T02 owns it. YAML/JSON coverage proves lexical search only, not semantic API or invariant graph extraction. The broader latency and optional-backend on/off/crash/timeout matrix remains open. T20 integrated commit `01df56605ccf484ebfe2808ac60d696c4e81dffc` (`test: add retrieval fixture coverage matrix`). Root `HEAD` and both postimage SHA-256 values were independently verified. T20 reports the same focused command passed **26/26 in 6.57s**. Root `git diff --check` passed.
