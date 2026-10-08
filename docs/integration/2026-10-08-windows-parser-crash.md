# Windows native parser crash: bounded stabilization

Owner: primary agent. Existing T10 parser/runtime safety scope; no new task,
branch, worktree, memory system, or context-pack implementation.

## Observed failure

Windows Application events 1000 repeatedly recorded Python 3.13.2 native access
violations (`0xc0000005`, `python313.dll`, offset `0x89711`). The failing worker
was the supervisor-owned `local_ai_hub.http_server`, not unrelated Python jobs.
Supervisor recovery repeatedly restarted the failing worker and produced dialogs.

An explicitly bounded supervised diagnostic with faulthandler identified the
current crashing thread in `treesitter_parser.py::_extract_python`, reading
`node.children`, called by background preprocessing's code-index batch.
The language-pack backend was loaded despite the existing Windows/Python 3.13
legacy-binding guard. Native parsing and traversal already shared a lock.
Changing the hidden interpreter to python.exe also crashed; that diagnostic
change and the temporary faulthandler launch argument were reverted precisely.
Other concurrent supervisor edits were retained.

## Change and limitation

Move the existing Windows/Python 3.13+ guard before either native backend import.
CodeIndex continues through existing deterministic fallbacks. A regression test
proves Python symbols, references, and call edges survive the guard.
Other platforms retain language-pack support; a mocked Windows/Python 3.12
contract preserves the supported-platform initialization path, not runtime proof.

This is crash containment, not a repaired native binding or full cross-language
quality acceptance. Native non-Python traversal is unavailable on this runtime.
Follow-up: isolate/verify a supported native-parser runtime before re-enabling it;
do not restore the language-pack bypass based only on mocked import tests.

## Verification

- RED: `python -B -m pytest -q -p no:cacheprovider --tb=short
  tests/test_treesitter_windows_crash_guard.py`: 1 failed, 0.21 s;
  dangerous language-pack import occurred before the guard.
- Parser cohort: same pytest flags with `tests/test_treesitter_windows_crash_guard.py`,
  `tests/test_t10_treesitter_parser_thread_safety.py`, and
  `tests/test_t10_treesitter_runtime_contract.py`: 7 passed, 2 skipped, 0.76 s.
- Fallback cohort: same flags with `tests/test_t10_python_fallback_budget.py`,
  `tests/test_t10_fallback_callgraph_parity.py`,
  `tests/test_t10_incremental_callgraph_edges.py`,
  `tests/test_t10_retrieval_fixture_matrix.py`, `tests/test_t10_acceptance.py`:
  119 passed, 20 skipped, 13.99 s. Skips are unavailable native parsers.
- `python -m compileall -q src tools tests`: exit 0.
- Standard service start at 13:57:52; 20 authenticated `/health` requests at
  three-second intervals, timeout 2 s: all HTTP 200, 0.9–24.4 ms.
  `/dashboard`: HTTP 200. No fresh Application event 1000 in that observation.
  Health JSON omitted PID, so samples alone do not prove a constant process ID.

Full-suite, long-duration, model quality, and final release acceptance remain open.
No durable databases or user worktrees were deleted or reset.

## Post-fix service reload

- Fix commit `193b601e` landed at 2026-10-08 13:59:49 +02:00. The observed
  Python 3.13.2 access violation at 13:55:28 preceded that fix.
- `python -B -m pytest -q -p no:cacheprovider --tb=short
  tests/test_treesitter_windows_crash_guard.py`: 2 passed, 0.20 s.
- The supervisor-owned HTTP worker was still pre-fix (PID 44640, started
  13:57:58). `python -B tools/hubctl.py restart` returned `restarted`; the
  replacement worker was PID 37964, started 14:20:57.
- `local_ai_status(action="brief")` after restart: success, v4.0.0,
  `degraded=false`. Windows Application Error query found 0 Python crashes
  from 14:20:57 through 14:22:26 (89-second observation only).
- A cached `hubctl status` response still named old PID 44640; do not treat
  that cached PID as fresh process evidence. A later direct process query
  confirmed PID 44640 was gone and the replacement worker was present.
- This proves the new worker loaded after the fix and survived the bounded
  observation, not long-duration stability or final release acceptance.
