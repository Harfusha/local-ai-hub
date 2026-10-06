# T15 acceptance handoff

Date: 2026-10-01 (Europe/Prague)

## Candidate and root integration

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t15-command-config\.local-ai-hub`
- Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` (detached, dirty; inherited work preserved)
- Root HEAD observed: `98a9a1a7611af574caf20a88620c4aa3eb2e918a` (`master`, dirty shared integration tree)
- No T15 root writes, merges, cherry-picks, cleanup, or root test runs in this continuation.
- No T15 root-test or CPU benchmark slot assigned by T20; no T15 root test or benchmark launched.
- Root ancestry: root is four commits ahead of candidate; candidate has no unique commit.

T20 reports integration of the eight-guard `bypass_cache` patch and root result **2 passed in 0.38s** for the two bypass selectors. Patch: [`t15-root-cache-bypass-guards.patch`](t15-root-cache-bypass-guards.patch), SHA-256 `93ddaa9b6175108e9e52e17146f31330a301fcdffb9c592faef4044a2f713c02`.

## Fresh candidate verification

Commands ran in T15 worktree at candidate HEAD above. Tracked source/test hashes and HEAD stayed unchanged.

Config/path/affected-test suite:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config_service_integration.py tests/test_project_config.py tests/test_project_path_hints.py tests/test_affected_tests.py
```

Result: **89 passed in 3.85s**, exit 0. Log SHA-256 `6b87f80bce4a7f4cfaaad69fc6ef1de2835176e3864405d987a908d506452bcb`.

Cache/broker/harness/streaming/transport suite:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_benchmark_command_broker.py tests/test_command_cache_singleflight_contract.py tests/test_project_command_broker.py::test_ordinary_command_cache_key_omits_empty_project_context tests/test_project_command_broker.py::test_resolve_project_command_uses_explicit_typed_alias_without_execution tests/test_project_command_broker.py::test_run_project_command_executes_exact_argv_with_safe_env_reference tests/test_project_command_broker.py::test_project_command_environment_values_change_cache_context tests/test_project_command_broker.py::test_unknown_project_command_alias_fails_before_execution tests/test_project_command_broker.py::test_project_command_rejects_unsafe_environment_override_before_execution tests/test_project_command_broker.py::test_string_project_command_is_resolved_exactly_without_runner_guessing tests/test_project_command_broker.py::test_project_command_still_obeys_broker_policy tests/test_command_concurrency_contract.py::test_slow_log_consumer_does_not_block_child_pipes tests/test_command_concurrency_contract.py::test_python_preflight_does_not_write_bytecode tests/test_command_concurrency_contract.py::test_python_preflight_still_reports_syntax_errors tests/test_command_concurrency_contract.py::test_mock_server_port_collision_does_not_claim_running tests/test_command_streaming.py tests/test_command_transport.py tests/test_command_timeout_cache_contract.py tests/test_command_suppression.py
```

Result: **45 passed in 11.46s**, exit 0. Log SHA-256 `55b3021a09ddeb068b58ff59e02c907c7a2902059baf95a561ce42834b1cff3b`.

`git diff --check` and handoff JSON validation passed. These candidate runs do not prove root integration or POSIX process-group behavior.

## Security broker review (separate from performance)

Read-only static review of the T15 candidate found no issue in the reviewed project-command ingress and cache-bypass paths. Alias and argument bounds, project-root containment, validated `shell=False` argv, blocked environment keys and size limits, normal broker policy routing, and cache-context binding are present. This is not full security acceptance: POSIX process-group/`PermissionError` behavior remains T06-owned and unverified on this Windows host.

Existing candidate receipts (not rerun in this continuation): config/path/affected tests **89 passed in 3.85s**, log SHA-256 `6b87f80bce4a7f4cfaaad69fc6ef1de2835176e3864405d987a908d506452bcb`; scoped command-broker/cache tests **45 passed in 11.46s**, log SHA-256 `55b3021a09ddeb068b58ff59e02c907c7a2902059baf95a561ce42834b1cff3b`. The 45-test selection covers unsafe environment overrides, project policy routing, cache bypass, and bounded streaming selectors. It does not prove POSIX group recovery.

Root-current snapshot (read-only, 2026-10-01): root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, dirty paths `256`. Candidate HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`, dirty paths `14`. Current root file SHA-256: `commands.py` `a242c5571f8bf75037b9d621a6f81a84d8ae046634694a460527292868318a8a`, `project_config.py` `6050453fa90c83f0282c4dd2588cac4454b5187f9c85521cf7aabf089e41c832`, `services.py` `3396d00de2ae5e382c70244243ca979efc40d2a8f8b4683dd0a61099e245d346`, command concurrency test `92d841f2b22d8d9480df0cf3189164ed86a4981cf8d4492f5735c73236e219a7`, project-command test `169f086607ccd725c6514b15bc6a54baf66e9f6c096395801b6f0beaa23b8728`, benchmark harness `ad99e187f625eeebac64ff7d71be34ca63e850959e7ea4879ab62eb65b55aff0`. Root harness tracked: `false`, SHA-256 `ad99e187f625eeebac64ff7d71be34ca63e850959e7ea4879ab62eb65b55aff0`. Its CRLF-normalized bytes match candidate harness `e8fad3f7fa40c8472b14c71ae1b9999e9a68dc9a801294cf5db17305101f67eb` (candidate LF, root CRLF). Root files are dirty/untracked; earlier root test receipts do not validate these current bytes. T02 reports its exclusive slot is still pending; T15 ran no tests or benchmarks and holds no slot. T15 made no root writes.


## T15 callback dispatch optimization

Prior capture receipts showed candidate-only dual-stream p50/p95 `109.013/110.824 ms` versus historical baseline `65.529/69.158 ms`; full historical reports remain invalid because both checkouts were dirty and used a stale harness. The dispatcher used `Queue.get(timeout=0.05)` to notice reader completion. T15 now uses a stop sentinel and blocking queue reads; when the bounded queue is full, the dispatcher drains pending chunks and exits after `readers_done` plus an empty queue. This removes the idle poll without blocking pipe readers or losing queued logs.

Added regression test `test_log_dispatcher_waits_for_queue_signal_without_polling`. It instruments the real queue used by `CommandBroker._execute` and requires blocking reads plus complete dispatch. Test is **not run** because T02 owns the pending shared slot. Existing 45-test receipt predates this patch and does not verify it. Existing slow-consumer test remains unchanged. No POSIX recovery or T06 hunk touched.

## Master-plan audit (T15 scope)

- **Correctness:** existing scoped tests cover valid aliases/argv, unknown aliases, unsafe environment overrides, policy blocking, Python syntax success/errors, callback delivery, bounded output, cancellation, timeout, and cache/single-flight contracts. No direct command-broker feature-disabled test was found. That 100% operation-contract gate remains open.
- **p95/p99:** benchmark schema v3 reports raw p50/p95/p99 and throughput. It adds fixed valid/invalid Python preflight fixtures. The runbook now calls for 100/10,000/100,000-file Git cohorts on two physical profiles. No fresh paired measurement exists; old dirty reports remain invalid. No 25% improvement or <=10% p95/p99 regression claim is proven.
- **Validation:** prior candidate-only classification result was p95 0.024 ms (n=500); it predates the dispatcher patch and has no valid paired baseline. The new positive/invalid preflight metrics are prepared, not measured.
- **Streaming:** the harness requires full callback byte equality, zero drops, and `dispatch_incomplete=false`; it records p50/p95/p99. Prior dual-stream p95 93.061 ms (n=4) predates the dispatcher patch and is not acceptance evidence. New queue-signal test is not run.
- **Resource measurements:** harness records throughput and stream bytes, not peak RSS. T15 makes no memory-improvement claim.
- **Execution gate:** T20 has not assigned clean source/harness pins or dedicated slot. T02 owns shared test capacity. No test, benchmark, fixture generation, or root write occurred in this continuation.

## Benchmark/preflight (separate from security)

No comparative benchmark ran in this continuation. Existing candidate-only microtimings: cache hit n=6 p50/p95 **17.259/18.137 ms**; miss n=6 **86.294/103.769 ms**; classification n=500 **0.020/0.024 ms**; warm fingerprint n=50 **0.120/0.144 ms**; forced fingerprint n=5 **136.599/157.864 ms**; dual-stream 2,000 lines per stream n=4 **92.493/93.061 ms**, 0 drops and no incomplete dispatch. These are not paired acceptance measurements.

Receipt preflight used synthetic fixtures only: 30 report/log pairs per profile, validator exit 0 for profile A and B. This validates receipt schema only. Full performance acceptance remains **NOT VERIFIED**: candidate and harness are dirty/untracked, root harness is untracked, exclusive benchmark slot and second hardware profile remain unassigned. Historical full reports remain invalid for acceptance.

## Root comparison and ownership

- `_key`, `_attempt_key`, `_git_primary_worktree_root`, `_path_override_for_candidates`, config/path-hint tests, three affected-test integration tests, and T15 benchmark/cache test/harness ASTs are already present in root. No duplicate patch needed.
- Root `LocalAIServices.affected_tests` has newer dispatch code; preserve root body. Config/service files have T21 overlap; concurrency process-group/rollback selectors belong to T06.
- Current combined artifact [`t15-root-compatible.patch`](t15-root-compatible.patch), SHA-256 `fcce360431c14d5e608946d792847cb9b7700ccff11fd5edcb8b9169e8cb198c`, is historical and no longer applicable: current root has newer `commands.py`/project broker context and the other patch files already exist. It was not applied by T15. No safe missing T15 patch remains.
- T06 timeout outcome remains owner-controlled; root waiter may return an uncertain generic result. T15 did not change that safety contract.

## Acceptance still open

Prepared exact gated workflow in [`t15-benchmark-runbook.md`](t15-benchmark-runbook.md). Static audit confirmed per-invocation isolated cache state and identity/hash receipts. Historical baseline/candidate reports are dirty and use stale harness SHA; invalid as proof. T20 confirmed baseline pin `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; integrated candidate/harness pins and root-test/CPU slots remain pending.

Receipt validator passed synthetic-only profile A and B fixtures (30 report/log pairs each, exit 0); schema checks only, not performance measurements. Pin preflight artifact: [`t15-benchmark-pin-preflight.json`](t15-benchmark-pin-preflight.json), SHA-256 `5f8ce6d7751c76fba19fa906d49a7844f60cb12a27174e2f8b26ead080553dc7`. T20 confirmed baseline candidate `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; its immutable tree equals root merge-base, `commands.py` blob SHA-256 `fdcf5432b154ff1ea2690bfe01016785c6dea85bda2b2f9a002e1a5e88cbb9ad`. Historical report HEAD `a77562e` is absent. No clean baseline worktree was created. Latest snapshot: root `98a9a1a7` dirty paths=251; candidate `824c9eb9` dirty paths=13; current harness dirty/untracked, SHA-256 `e8fad3f7fa40c8472b14c71ae1b9999e9a68dc9a801294cf5db17305101f67eb`; no active T15 benchmark process. T20 has not assigned clean integrated candidate/harness pins, exclusive CPU/root test slots, or second hardware profile.

Actual performance acceptance remains **NOT VERIFIED**. Baseline pin confirmed. Clean integrated candidate/harness pins, two approved hardware profiles, and explicit T20 CPU slot still required. Do not use prior dirty benchmark reports or synthetic receipts as performance proof.

T06 POSIX/write-set acceptance remains separate and owner-controlled. Handoff does not claim full release acceptance.
