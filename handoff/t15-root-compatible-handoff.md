# T15 root-compatible handoff

Snapshot date: 2026-10-01. Read-only comparison; no root changes.

## Trees

- T15 worktree: `C:\Users\Adam\.codex\worktrees\t15-command-config\.local-ai-hub`
- T15 HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` (detached)
- Root: `C:\Users\Adam\.local-ai-hub`
- Root branch/HEAD: `master` / `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
- Current root `commands.py` SHA-256: `4aa82d2abdd876b7aade9fd55b13ec1d62fbd6cbeedf783975bc32894c2834a2`

## Missing T15-owned patch

- Patch: `handoff/t15-root-compatible.patch`
- SHA-256: `fcce360431c14d5e608946d792847cb9b7700ccff11fd5edcb8b9169e8cb198c`
- Size: 47,944 bytes; diff stat: 5 files, 1,116 insertions, 7 deletions.
- Current-root `git apply --check` at HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`: PASS; patch was not applied.
- Paths: `src/local_ai_hub/commands.py` (`CommandBroker._key`, `_attempt_key` only), `tests/test_project_command_broker.py` (one missing empty-context test), `tests/test_command_cache_singleflight_contract.py`, `tools/benchmark_command_broker.py`, `tests/test_benchmark_command_broker.py`.
- Patch excludes T06 process-group, daemon recovery, rollback, and write-set hunks.

## Root comparison

- `CommandBroker._key` and `_attempt_key` are not root-equivalent. T15 includes policy settings in cache identity and omits empty context; current root lacks policy settings and always includes context. T15 AST hashes: `_key` `3bdc8c18bb04330dc8a335b4c4f05da238f23e3a33a08965ef5c21227ba7664c`, `_attempt_key` `7af1495ab8ef0b81c622552d9a230bdd197d1c9be20d551297c0248278a88954`; root hashes: `_key` `a9069bd42f86b96b95b1b8abda127c9056412202b0639bccfee9cbc502ab2266`, `_attempt_key` `f6f736d7a9d7bf5b2d0a2ffb580de52750f7089627d65f70e9484bc7d1f05d0a`.
- `CommandBroker._execute`, `_resolve_project_command`, and `run_project_command` match current root by AST source hash.
- All three T15 `run_affected` regression tests match root byte-for-byte. Root `affected_tests` now dispatches through `_repository_test_impact_service`; root `command` has an additional `record_verification` argument. Those service files are excluded from this patch.
- Benchmark harness/tests and cache/singleflight contract test are absent from root.

Current source hashes:

| File | T15 | Root |
|---|---|---|
| `src/local_ai_hub/commands.py` | `12dde723016cc9d278b03cf0831898af449a766eaa2159f0471cc4fa7457f3b1` | `e234c45cc437f9f2271867457ab1bf12ed9fb145ce05668700ab26514e7b5c1a` |
| `src/local_ai_hub/services.py` | `7394f38919b5f3b421110c6cb88e841d386cc8b6c848c410b501549ab4029add` | `1c0656d6256d87d8e360034782db97d04a401b6ed1a8db421e77f249f44319b9` |
| `tests/test_project_command_broker.py` | `c59054823d3b6b6189463c870e707b827ce4c2872c4e1758505095f5832c818c` | `d2659cb47205acd6daa73001b01e0891e0f2b75f83416508e811ab6c38737182` |
| `tests/test_project_config_service_integration.py` | `6af5dc8ac6d575ad4600c7bc9ca6ca01e8a5e039cc52359336d6e19c7a5a1c42` | `a06522f19772744730045dfed9f46564bdaf26936e518082103798ff6b3d52a2` |
| `tests/test_command_cache_singleflight_contract.py` | `9ed6fb58426b4665e6aa25b5ed8a348dddb24b080dd0d7823d8d52ba2a71209d` | absent |
| `tools/benchmark_command_broker.py` | `e8fad3f7fa40c8472b14c71ae1b9999e9a68dc9a801294cf5db17305101f67eb` | absent |
| `tests/test_benchmark_command_broker.py` | `8a3f2d0358b784a398c0bbd8257af9b0dbfb290f65a840ad13b87f75c19ce35c` | absent |

## CPU test receipt

- Command (PowerShell; `PYTHONPATH` set to `src`):

```text
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_benchmark_command_broker.py tests/test_command_cache_singleflight_contract.py tests/test_project_command_broker.py::test_ordinary_command_cache_key_omits_empty_project_context tests/test_project_command_broker.py::test_resolve_project_command_uses_explicit_typed_alias_without_execution tests/test_project_command_broker.py::test_run_project_command_executes_exact_argv_with_safe_env_reference tests/test_project_command_broker.py::test_project_command_environment_values_change_cache_context tests/test_project_command_broker.py::test_unknown_project_command_alias_fails_before_execution tests/test_project_command_broker.py::test_project_command_rejects_unsafe_environment_override_before_execution tests/test_project_command_broker.py::test_string_project_command_is_resolved_exactly_without_runner_guessing tests/test_project_command_broker.py::test_project_command_still_obeys_broker_policy tests/test_command_concurrency_contract.py::test_slow_log_consumer_does_not_block_child_pipes tests/test_command_concurrency_contract.py::test_python_preflight_does_not_write_bytecode tests/test_command_concurrency_contract.py::test_python_preflight_still_reports_syntax_errors tests/test_command_concurrency_contract.py::test_mock_server_port_collision_does_not_claim_running tests/test_command_streaming.py tests/test_command_transport.py tests/test_command_timeout_cache_contract.py tests/test_command_suppression.py
```
- Result: `45 passed in 9.86s`; exit 0. T06 daemon/process-group/rollback selectors excluded.
- Log: `C:\Users\Adam\AppData\Local\Temp\t15-cpu-acceptance-2d195aebc2e447ca937163bf584c0154.log`
- Log SHA-256: `141c4549da7c4871e19f6188002f8464c70ad42f4c0ba4fee146c6a56c53f64f`

The test invocation covered `tests/test_benchmark_command_broker.py`, `tests/test_command_cache_singleflight_contract.py`, eight project-command selectors (excluding rollback delegation), four non-T06 concurrency selectors, plus `tests/test_command_streaming.py`, `tests/test_command_transport.py`, `tests/test_command_timeout_cache_contract.py`, and `tests/test_command_suppression.py`.

Root-side config receipt on the same root snapshot: seven root-present project-command selectors passed as `9 passed in 1.07s`, exit 0. `commands.py` and `tests/test_project_command_broker.py` hashes were unchanged before/after. Log: `C:\Users\Adam\AppData\Local\Temp\t15-root-config-cf381fa616844de79143a21755cd17b0.log`; SHA-256 `2a5f40a51f3b456978916781716548bb83d33d0bf6d748a1a48638100756b5b1`.

Exact root test command:

```text
$env:PYTHONPATH=(Join-Path $root 'src')
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_command_broker.py::test_resolve_project_command_uses_explicit_typed_alias_without_execution tests/test_project_command_broker.py::test_run_project_command_executes_exact_argv_with_safe_env_reference tests/test_project_command_broker.py::test_project_command_environment_values_change_cache_context tests/test_project_command_broker.py::test_unknown_project_command_alias_fails_before_execution tests/test_project_command_broker.py::test_project_command_rejects_unsafe_environment_override_before_execution tests/test_project_command_broker.py::test_string_project_command_is_resolved_exactly_without_runner_guessing tests/test_project_command_broker.py::test_project_command_still_obeys_broker_policy
```

## Remaining acceptance gap

No performance benchmark was run. T15 and root worktrees are dirty; no clean, revision-matched baseline/candidate performance receipt exists. Historical dirty v1 receipts do not establish a current performance win. Root remains unchanged by this handoff.
