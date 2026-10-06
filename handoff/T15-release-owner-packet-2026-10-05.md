# T15 release-owner checkpoint — 2026-10-05

## Registered checkout and pre-existing state

- Registered, attached T15 worktree: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`.
- Verified Git root: `C:/Users/Adam/.codex/worktrees/fefe/.local-ai-hub`.
- HEAD/base: `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`.
- Repository revision fingerprint: `e7aeddb903616d95427f32c1a238463e6e3b3a2ba4e1e16395d531f83c390172`.
- Scoped status at resume: one modified source path and six untracked T15 handoff artifacts. No T15 source/test edits made during this continuation.
- Root, other worktrees, and T14 `/api/context/pack` were not opened for mutation or changed.

## Exact dirty inventory and hashes

For each untracked artifact, base at HEAD is absent; the listed value is its current worktree Git blob. `commands.py` HEAD and worktree blobs differ due to the pre-existing T06-owned hunk.

| Path | Owner/state | HEAD blob | Worktree blob |
|---|---|---|---|
| `src/local_ai_hub/commands.py` | Modified; existing T06 `_snapshot_patch_targets` hunk; T06 protocol owns all `commands.py::run` | `a9e927362f21fd3b381c30d771dd0059a124937f` | `5fc5c1144574b74523816c4bba76ec8b751907b2` |
| `handoff/T15-T29-command-run-paired-benchmark.py` | T15 handoff harness | absent | `ed8d23f4b19a98d8c59107e2c9738683511dd80b` |
| `handoff/T15-T29-commands-run-paired-methodology-2026-10-03.md` | T15 methodology | absent | `da759b63534a0d62edce05ec8ce035123ad0e5d6` |
| `handoff/T15-T29-readonly-benchmark-protocol-2026-10-04.md` | T15 pin/ownership protocol | absent | `f4d030fa770b3c10c109c63ac430c13cecd385d5` |
| `handoff/T15-T29-root-current-packet-2026-10-04.md` | T15 prior checkpoint | absent | `d5eb78853bfd76a4da1d6f2709cd6139bc12b098` |
| `handoff/T15-process-group-recovery-receipt-2026-10-05.md` | T15 focused recovery receipt | absent | `2353ffc9f1dc4cb11024227ac46605b13345e686` |
| `handoff/t15-patch-snapshot-stat-20261003.patch` | T15 handoff patch artifact; not applied because it overlaps T06 rollback scope | absent | `f01c105eec8b6318fa6eb862ecad250590e22c2d` |
| `handoff/T15-release-owner-packet-2026-10-05.md` | This packet; created in this continuation | absent | Record final post-write blob after verification |

`commands.py` current SHA-256: `ed97e7220030b4fc181bca02e5281d677e683d6038c5ce6748101a3e37ccea17`; diff is `+3/-4` in `_snapshot_patch_targets`, owned by T06. `commands.py::run` was not edited. `tests/test_command_concurrency_contract.py` is clean at HEAD/worktree blob `421c43a77d1adb404cffe466586f05a8721fab10`, SHA-256 `180be8930a40d81cf470fd92b590bc25757414d89c1e67fad28fdad4d36e3be6`.

## T15 verified test results

1. Command:

   ```text
   python -B -m pytest -q -p no:cacheprovider tests/test_command_concurrency_contract.py -k "recovered_daemon or leaderless" --tb=short
   ```

   Broker request `req_4d254b56b4dd`, execution `7282e0169f184fc48bf60674e4af7361`, repository revision `f9e3dfa0b1cdc7f9e7ec7f909fc394b2a275bfe654c7f4ef8436f99f65fb229f`; exit 0, `3 passed, 3 skipped, 78 deselected in 0.11s`. Three POSIX-only process-group cases skipped on Windows. This is focused recovery evidence, not full T15 acceptance.

2. Command:

   ```text
   python -B -m pytest -q -vv -p no:cacheprovider tests/test_command_concurrency_contract.py -k "daemon or process_group or ownership_token" --tb=short
   ```

   Broker request `req_982556b15507`, execution `c4a050f8e7494899983495a71a96337d`, exit 0, nine selected. Returned stdout was truncated after two named pass lines; diagnostics reported three POSIX-only skips. Not counted as a complete receipt.

No benchmark ran in this continuation. The prior T15 paired probe remains `acceptance=false`; it does not satisfy current acceptance.

### Fresh core release regression receipt (2026-10-05)

Command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_concurrency_contract.py::test_overlapping_repeatable_calls_execute_once_and_return_same_result tests/test_command_concurrency_contract.py::test_run_reuses_tool_identity_and_reports_command_phase_timings tests/test_command_concurrency_contract.py::test_stdout_and_stderr_flood_are_drained_without_blocking tests/test_command_concurrency_contract.py::test_slow_log_callback_does_not_block_command_pipe_drain
```

Broker request `req_23c15b41df8d`, execution `66526d47c947435e9fbc0ef35b8ad0d3`, repository revision `167a71c3175c9c6d5fa4aac4882f1d44696e141417aef80b737853df841f55c2`; exit 0, stdout `.... [100%]` and `4 passed in 1.67s`. This is functional regression coverage for concurrency, phase timing output, pipe drainage, and callback isolation. It is not a benchmark and makes no performance claim.

Pre/post source remains unchanged at T15 HEAD `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`, `commands.py` HEAD blob `a9e927362f21fd3b381c30d771dd0059a124937f`, worktree blob `5fc5c1144574b74523816c4bba76ec8b751907b2`; the inherited T06 hunk remains outside this test receipt's changes.

### Fresh cache identity receipt (2026-10-05)

Command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_concurrency_contract.py::test_repeatable_cache_reuses_results_and_tracks_repository_revision tests/test_command_singleflight_revision.py::test_changed_repository_does_not_join_stale_singleflight
```

Broker request `req_04f727613bba`, execution `7d83858c06b34ab2ae078d8bd275ba80`, repository revision `77cd0cb8d4b5737342c180796d48c09684568827b922b180a8466202d875671d`; exit 0, stdout `.. [100%]` and `2 passed in 1.24s`. Confirms cache reuse/revision invalidation and stale single-flight separation on the current T15 worktree. This is functional coverage, not a speed measurement.

## Performance safety decision and T20 dependency

- T15 acceptance matrix includes command cache/concurrency/phase performance.
- T15 paired harness exercises `noop`, `read4096`, and `write4096`, measuring planning/execution/result recovery through `CommandBroker.run()`.
- Protocol `handoff/T15-T29-readonly-benchmark-protocol-2026-10-04.md` assigns the entire `commands.py::run` method plus rollback/write-set safety to T06; T15 owns only harness/reporting after T06 supplies a clean pinned candidate.
- Current worktree cannot be candidate: the only dirty source hunk is T06-owned; no T06 clean handoff/pin is available.
- T20 was asked for a serial slot or a distinct T15-owned benchmark subject. T20 replied: “T15 slot neschvaluji: chybí T06 handoff i čisté immutable pins. Release zůstává NO-GO.” No slot/GO granted. No benchmark started.
- Therefore no benchmark of non-T06-owned code satisfies current T15 acceptance. Do not substitute the dirty worktree or reclassify `CommandBroker.run` as disjoint.

## Release checkpoint

- T15 minimum functional regression slice is green: the four focused core selectors above plus the prior three-pass recovery slice; POSIX process-group integration remains skipped/unverified on this Windows host.
- T15 overall release acceptance: **BLOCKED / NOT COMPLETE** by missing T06 clean handoff and T20 GO/slot. Performance improvement has not been measured or accepted.
- Latest T06 report still confirms assigned `57e3` worktree is filesystem-only, archived snapshot missing; foreign `t06-write-set-resume` ownership transfer was refused. No T06 source/receipt is available to pin.
- T20 remains explicit NO-GO for T15 paired measurement until T06 clean handoff and exact immutable pins exist; no serial slot ID granted. This was previously asked against the same unchanged pins; no duplicate request issued.

### Paired harness safety audit (2026-10-05)

- Runner `handoff/T15-T29-command-run-paired-benchmark.py` declares that it requires T20's explicit serial slot, runs each source observation in a fresh worker sequentially, creates temporary clones at pinned commits, and leaves source worktrees untouched.
- The harness creates a disposable scratch directory in each temporary clone and writes the report only to its explicit `--report` path (protocol requires this outside both roots). No daemon/Hub startup is part of the described driver. Therefore its intended mutations are temporary clone/workload writes plus the explicit report; root and source worktrees are designed to remain untouched.
- This safety design does not remove the gate: the current `fefe` checkout has 8 dirty entries (one modified T06-owned `commands.py` and seven T15 handoff artifacts); its dirty `commands.py` cannot be used as an immutable candidate. The committed HEAD candidate would require a clean pinned baseline/candidate pair and a current T20 slot. Neither exists.
- Decision: do not run. No raw benchmark observations, p50/p95, or performance acceptance receipt were produced.
- T15 release-level performance acceptance is not deferred as polish. No non-release polish was deferred. No broader security/install/runtime claim is made outside T15 ownership.
- Next concrete step: obtain T06 clean candidate and exact immutable pins; reconcile against T15 baseline, then request T20 serial GO/slot tied to that pair. Run the paired harness only after explicit grant.
