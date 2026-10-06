# T02 SQLite warning runner — 2026-10-01, v1

## Runner

Added `tools/run_t02_sqlite_warning_diagnostic.py`. It hard-codes exactly two historical selectors and runs them once. It uses Python `-X tracemalloc=5`, `-W error::ResourceWarning`, pytest `--tb=long`, `-s`, a new explicit `--basetemp` under the output directory, a 120-second timeout, and separate raw stdout/stderr files. It strips `T02_TRACE` from the child environment and keeps runner stdout to one JSON summary line.

Runner SHA-256: `41aeb9fbf7edef8cbd421f6471e227a6d7e2c09b55f5b0de2cfb959915a90026`

## Candidate run

- HEAD: `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`
- Started: `2026-10-01T17:31:42.395253+00:00`
- Command status: `timeout` after `121.285` seconds; bounded timeout (`exit_code=124`).
- Pytest collected two selectors. First selector started and emitted `T02_BASELINE_RESULT` with `success=true`; it had no completion marker before timeout. Second selector did not start.
- Captured stdout/stderr contain zero `ResourceWarning` mentions. `T02_TRACE` was absent from child output and was removed from child environment. No complete warning traceback captured.
- No passing test result claimed. Warning reproduction remains inconclusive because process timed out.
- Explicit pytest state root: `C:\Users\Adam\AppData\Local\Temp\t02-sqlite-diagnostic-candidate-20261001-v2\pytest-state-root`.

Receipt pins source hashes and exact command. Logs preserved separately; receipt SHA-256 `286eb1689a28c573598a00efcc398862ae7ecd092c75b25844decec392d29955`.
