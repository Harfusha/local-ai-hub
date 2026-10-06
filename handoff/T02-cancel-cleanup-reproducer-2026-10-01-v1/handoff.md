# T02 cancel/cleanup reproducer — 2026-10-01

## Pinned roots

- Protected root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a` before and `98a9a1a7611af574caf20a88620c4aa3eb2e918a` after. Test command ran only in candidate.
- Candidate: `C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub`, HEAD `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`.
- Candidate source SHA-256: `{"src/local_ai_hub/async_jobs.py": "6c245f4a52c4d1fd2a0d5ac50dfa6ce3e018b9cd2a400f27241690cc8bc97f0a", "tests/test_t02_repeated_benchmark_cleanup.py": "62d82421215849e538a302fc187c0343f8054949cedd78dfc1be94531dfee758", "tools/benchmark_surfaces.py": "e93f2bbda52b62018d8f2ae4c4f148f0ccb7e24c37f3a3c3f1ebeeb0d7412457"}`.

## RED evidence

Prior bounded full-size selector run reached the first test and completed its initial baseline (`success=true`), then timed out after 120 seconds during its second comparison call. Evidence: [prior attribution](T02-timeout-attribution-2026-10-01-v1.md), [prior receipt/logs](T02-sqlite-warning-runner-2026-10-01-v1/receipt.json). This is a timeout receipt, not a traceback or a reproduced SQLite warning.

## Exact minimal test and GREEN evidence

Test: `tests/test_t02_repeated_benchmark_cleanup.py::test_minimal_baseline_comparison_cancels_and_closes_runtime`.

It invokes `run_benchmark` twice on the same isolated roots with `baseline_record` passed to the second call. Workload is 1 file, 1 RAG chunk, 1 repetition, 1 light repetition, 1 comparison repetition, concurrency `(1,)`. At each `AsyncJobManager.close`, it checks shutdown, live threads, registered live child processes, queued/running SQLite states, and `BEGIN IMMEDIATE` acquisition. It also checks second comparison persistence and empty scratch tree.

Command:

`C:\Python313\python.exe -X tracemalloc=5 -W error::ResourceWarning -m pytest -vv --tb=long -s -p no:cacheprovider tests/test_t02_repeated_benchmark_cleanup.py::test_minimal_baseline_comparison_cancels_and_closes_runtime`

Result: `passed`, exit `0`, `15.396s`; pytest reports `1 passed`. Two close snapshots each showed `job_states={"cancelled":1}`, `shutdown=true`, `live_threads=[]`, `live_processes=[]`, and `sqlite_write_lock_acquired=true`. Scratch tree ended empty. No `ResourceWarning` appeared.

## Conclusion

The minimal second-comparison path did not reproduce a live worker, child, queued job, or SQLite write transaction. The 12-file/20-chunk full test timeout remains unexplained; minimal GREEN does not prove that larger case healthy. No product change or expectation change made. Added only this bounded regression/diagnostic test. No performance claim.

## Evidence hashes

- pytest stdout SHA-256 `b2fb97c25e5443f57c086651961592e83e4fd25e49afc853d75fa8a9c56d6d38`
- pytest stderr SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- receipt SHA-256 `a82686f22606dcc5b804eae1e0ae96d13c5a2f1341d3966b8b95061ee2eeeaac`
