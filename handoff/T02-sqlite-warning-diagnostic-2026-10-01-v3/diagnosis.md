# T02 SQLite warning diagnostic — 2026-10-01, v3

## Scope and snapshot

Ran only the two historical selectors below, once, in an isolated clone of the current root working tree. No 25-case loop or separate performance run.

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Snapshot: tracked working diff SHA-256 `5f252285a71211c7f2ea5850175d8fb48aa7b85f4a1a2174907100e84d428add`; 140 non-ignored untracked files copied from `src/local_ai_hub`, `tests`, and `tools`.
- Added T13 lifecycle plugin only inside overlay; SHA-256 `1d8d70277576270722e57d833251b45f8a466254573b5a9c6eae86b31682bb11`.
- Root HEAD and hashes for five relevant source files matched before and after. See `receipt.json` for hashes, command, overlay path, and output hashes.

## Command

`C:\Python313\python.exe -X tracemalloc=5 -W error::ResourceWarning -m pytest -q --tb=long -p no:cacheprovider -p tools.t02_lifecycle_pytest_plugin <two selectors>`

Selectors:

1. `tests/test_surface_benchmarks.py::test_run_benchmark_is_isolated_and_preserves_existing_scratch_data`
2. `tests/test_surface_benchmarks.py::test_component_baselines_measure_graph_rag_batch_parent_seed_and_serena`

Environment: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH=<isolated overlay>`.

## Result

Exit 1 after 34.30 seconds; both selectors failed their baseline assertions. First selector's captured summary reports only `hub_rag_search` failed, with two `RuntimeError` errors and no reason text. Second selector asserts `hub_rag_search.status == passed`, but observed `failed`.

No `ResourceWarning` mention occurred in captured stdout or stderr. `sqlite_operational_errors` was empty. T13 teardown snapshots reported no open managers; manager worker was not alive after close or at teardown. This run did not reproduce the historical unclosed-connection warning. It also does not prove the historical warning fixed: the baseline stage failure limits the reproduction.

## Artifacts

- `receipt.json`: exact command, snapshot metadata, status, hashes.
- `stdout.txt`, `stderr.txt`: captured logs. SHA-256 values are in `receipt.json`.
- Initial v1/v2 overlays were incomplete and failed on absent untracked import modules; v3 copied all relevant untracked root files and is the diagnostic result above.
