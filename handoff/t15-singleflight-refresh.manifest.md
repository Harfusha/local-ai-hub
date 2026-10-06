T15 stale in-flight fingerprint handoff

- Root: `C:\Users\Adam\.local-ai-hub`
- Root HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Base blob `src/local_ai_hub/commands.py`: `eda412c2504564d00ad854db300125b30ec3e30b`
- Allowlist: `src/local_ai_hub/commands.py`, `tests/test_command_singleflight_revision.py`
- Patch: `handoff/t15-singleflight-refresh.patch`; patch blob: `676c2b5d28bee6673cb3ad44af49717ac9e3f51a`
- Test blob: `tests/test_command_singleflight_revision.py` `50bcd445b73260b794f9aeaea603a97a697f433f`
- Behavior: when a command call finds a matching in-flight event, invalidate and recompute the repo key once before joining; changed tracked revision runs independently. Existing cache-hit and T06-owned cache-read sites are untouched.
- Root `git apply --check`: passed; root files unchanged.
- Authorized native regression run in fefe: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_singleflight_revision.py::test_changed_repository_does_not_join_stale_singleflight tests/test_command_concurrency_contract.py::test_overlapping_repeatable_calls_execute_once_and_return_same_result tests/test_command_concurrency_contract.py::test_inflight_waiter_is_not_reported_as_cache_hit tests/test_command_concurrency_contract.py::test_repeatable_cache_reuses_results_and_tracks_repository_revision tests/test_command_concurrency_contract.py::test_repo_state_cache_does_not_reuse_result_after_immediate_file_change` — `5 passed in 2.13s`.
- This test receipt exercised fefe's current candidate, not root integration. Root test not run.
