# T10 resume handoff — 2026-10-02

Worktree: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`  
Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`  
Root was not edited. `/api/context/pack` and API-adjacent tracked files were unchanged.

## Candidate source diff

[`t10-source-acceptance-diff-20261002-r4.patch`](C:/Users/Adam/.codex/worktrees/t10-path-hints/.local-ai-hub/artifacts/handoff/t10-source-acceptance-diff-20261002-r4.patch)  
SHA-256: `C3EAFCFB24D065E567FF33407261FC792A9F4E1326781F35D739BB9A32CD0C13`. Candidate-only patch; not root-applicable. Contains five tracked source/default files and two untracked T10 regression modules.

## Self-review and fix

Review found `find_callers` and `find_callees` used unescaped SQLite `LIKE` suffix patterns. `_` in a symbol could match another character and return a false graph edge. Added `_escape_like_literal` for `!`, `%`, `_`, `ESCAPE '!'` on both queries. Regression `test_callgraph_suffix_queries_escape_sql_like_wildcards` now covers all three special characters with paired true and decoy namespaced edges, checking both query directions.

The regression failed before the fix with two caller edges instead of one (`1 failed in 0.81s`), then passed after the fix (`1 passed in 0.38s`). A first fixture draft did not reach the suffix branch; it was replaced before the confirming red run.

Impact review: `RepositoryServices.callers` consumes `find_callers` and returns a successful non-empty CodeIndex result unchanged; otherwise it falls back to deterministic search. The fix narrows false-positive SQL matches without changing response shape. No `find_callees` service consumer was found in the bounded T10 review scope.

## Verification receipts

Full candidate selector ran before the final wildcard fix: `50 passed in 11.05s`, exit 0, execution `fcbd606e78cc4c1ab4596be274bc1ff0`. It was not repeated after the fix. Exact command:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_code_index_schema_rebuild.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_python_fallback_budget.py tests/test_t10_repo_search_path_hints.py tests/test_t10_retrieval_fixture_matrix.py tests/test_adaptive_retrieval.py tests/test_repo_topology.py tests/test_affected_tests.py tests/test_cross_repo_federation.py
```

Post-fix regression command, exit 0, execution `fb1dbbb2de324048875e3d49ecdf14f1`:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_fallback_callgraph_parity.py::test_callgraph_suffix_queries_escape_sql_like_wildcards
```

Post-fix `git diff --check -- defaults.toml src/local_ai_hub/defaults.toml src/local_ai_hub/code_index.py src/local_ai_hub/preprocess.py src/local_ai_hub/repo_tools.py`: exit 0. No coverage percentage was collected.

## Source and regression hashes

| Path | SHA-256 |
| --- | --- |
| `defaults.toml` | `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B` |
| `src/local_ai_hub/defaults.toml` | `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B` |
| `src/local_ai_hub/code_index.py` | `23634057D2C4FA1EE4C737AD9F2AA1B04E8674FAE32ADAB282C00FECD1B33FF5` |
| `src/local_ai_hub/preprocess.py` | `3377491FFAA0A7150E2F8B5CC097E7CA1636449E77B8FF2C98A912368984ABD3` |
| `src/local_ai_hub/repo_tools.py` | `6C43F6FA7B067856E4543833EF79C2195FFEACC8C900EB0988AFDE16392E527B` |
| `tests/test_t10_ast_impact_acceptance.py` | `9EDA789CF61D320AF5221E78F0CC96C88CA2F0DEF6D7579F1A929A3BBD52C098` |
| `tests/test_t10_code_index_schema_rebuild.py` | `EE13096E48A9E209806928886D0070AD7045986A80DDD164B88231A2C6D8D887` |
| `tests/test_t10_fallback_callgraph_parity.py` | `EE59947DA77DC19911E68E3BD68C6CD6252450B4E7D99BE81621A5F7C83B5DB3` |
| `tests/test_t10_python_fallback_budget.py` | `33DF2F3730293C5C8962556268C6E3DB2C33F13BB661683DAB2632BDE786C075` |
| `tests/test_t10_repo_search_path_hints.py` | `06ED8143F5E6B62A3D9D945C6A451163398C3AEC48332923507885BA525C4E90` |
| `tests/test_t10_retrieval_fixture_matrix.py` | `4B843BA75C1092BB730404CD4E68B7C3AD1B03D4B74BB0999A26FB7C7E5C310C` |

Current callgraph regression test SHA-256: `E2461A2A597BFDE974250AFDB62AC10320A1C4933E5DA0E5A6D43C8AD62E890C`. Other T10 tests: `tests/test_t10_ast_impact_acceptance.py`, `tests/test_t10_code_index_schema_rebuild.py`, `tests/test_t10_python_fallback_budget.py`, `tests/test_t10_repo_search_path_hints.py`, `tests/test_t10_retrieval_fixture_matrix.py`.

Path-hint deny test now sends explicit request hints for `secret/blocked.php`, hard-denied `src/quarantined.php`, and `../outside.php`; mocked repo search returns all candidates; assertion allows only `src/allowed.php`. This closes prior test gap where excluded/outside candidates were present but no request hints were supplied. Current `tests/test_t10_repo_search_path_hints.py` SHA-256: `6541CDDE788936B14C311B4C4B9CF1D876CD1378E2C5F8A53BABDBC4182D0B88`. Not run; awaiting T20 GO.

Existing regression modules in the selector are also pinned: `tests/test_adaptive_retrieval.py` `BC8CB31549324CA38CC310E4D7ED8F82D303F0E86B3EC88EF18E44F0D75EDE60`; `tests/test_repo_topology.py` `F57CF34BAD744B5C7D5B57E8BA9D84BD0D9152F51444906529DB5562B1F8C73F`; `tests/test_affected_tests.py` `0A94EF9BD1BF81F733E216CE0A6A81F2741515F84990F17657AAC02D13152530`; `tests/test_cross_repo_federation.py` `567AC3C4DCE8479ABF93FA50D8E5B9BB966E523A1567F8F5E41080C66DC40434`.

## Open acceptance

The fresh 100k retrieval/callers/impact benchmark remains open. T02 owns `hub_impact_latency`; no valid paired 100k receipt, exact pins, p95, or separate memory result exists. No speedup claim made. T10 did not alter T02 sources or run a benchmark. T20 queue update: slot G is released `UNKNOWN` (not PASS), no T10 slot is assigned; queued slots are L=T06, M=T05 migration, N=T04 path-hints candidate. T20 says no tests or benchmark absent a later explicit slot. No tests were run in this continuation. Overall goal remains incomplete until owner-approved benchmark evidence is attached.

Test preflight (bounded native read; HUB explicitly skipped): all ten selector files exist; no imports, collection, or tests were run. Current candidate HEAD remains `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Current pins: `code_index.py` `23634057D2C4FA1EE4C737AD9F2AA1B04E8674FAE32ADAB282C00FECD1B33FF5`; `repo_tools.py` `6C43F6FA7B067856E4543833EF79C2195FFEACC8C900EB0988AFDE16392E527B`; `preprocess.py` `3377491FFAA0A7150E2F8B5CC097E7CA1636449E77B8FF2C98A912368984ABD3`; defaults (both) `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`; updated callgraph test `E2461A2A597BFDE974250AFDB62AC10320A1C4933E5DA0E5A6D43C8AD62E890C`; updated path-hint test `6541CDDE788936B14C311B4C4B9CF1D876CD1378E2C5F8A53BABDBC4182D0B88`; source patch r4 `C3EAFCFB24D065E567FF33407261FC792A9F4E1326781F35D739BB9A32CD0C13`. T20 matrix latest: T07 owns active serial slot; T12 waits next; T10 has no GO. Regression-expanded candidate has not been run due to the T20 slot restriction.
