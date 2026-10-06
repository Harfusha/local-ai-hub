# T15/T29 `commands.run` paired performance and review method — 2026-10-03

## Scope and ownership

T15 performance acceptance for `CommandBroker.run()` only. No `commands.py` edits in this handoff. T06 owns command execution/rollback changes and must provide the exact frozen baseline/candidate preimages before measurement. Current T15 worktree is `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`, HEAD `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`; `src/local_ai_hub/commands.py` is dirty by 3 insertions/4 deletions. Do not treat that unreviewed dirty source as a comparable branch. T06 task is active; command semantics and slot release remain pending owner confirmation. No message sent to T06 from this task.

## Workloads

Run three deterministic `CommandInvocation(argv=..., cwd=..., shell=False)` workloads inside a disposable, initialized Git worktree with a dedicated scratch directory. Exact workload argv shapes:

1. **No-op:** `[sys.executable, "-B", "-c", "pass"]`; success, exit 0, empty stdout/stderr, no file changes.
2. **Read:** `[sys.executable, "-B", "-c", "from pathlib import Path; import hashlib,sys; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())", str(read_fixture)]`; fixture is fixed at 4096 bytes; digest and repo revision must match each run.
3. **Write:** `[sys.executable, "-B", "-c", "from pathlib import Path; import hashlib,sys; p=Path(sys.argv[1]); p.write_bytes(b'x'*4096); print(hashlib.sha256(p.read_bytes()).hexdigest())", str(write_output)]`; each branch receives identical clean scratch state. Verify 4096 bytes and exact digest. Writes are disposable and must not target the user checkout. Construct each as `CommandInvocation(argv=argv, cwd=str(worktree), shell=False)`.

Keep command payload, cwd shape, config, tenant, timeout, Python executable, fixture bytes, filesystem location, and broker options identical between versions. Use one fresh scratch worktree per frozen source version. Do not run concurrent benchmark workers.

Reproducible setup and exact argv construction (runner uses the existing test helper `_command_broker(state_root)`, tenant `t29-bench`, timeout `30`, `force=True` for execution samples):

```python
import hashlib
import sys
from pathlib import Path
from local_ai_hub.commands import CommandInvocation

scratch = worktree / ".t29-bench"  # add only this path to the disposable worktree's .git/info/exclude
scratch.mkdir(exist_ok=True)
read_fixture = scratch / "read-4096.bin"
read_fixture.write_bytes(bytes(range(256)) * 16)
write_output = scratch / "write-4096.bin"

cases = {
    "noop": [sys.executable, "-B", "-c", "pass"],
    "read4096": [sys.executable, "-B", "-c",
        "from pathlib import Path; import hashlib,sys; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())",
        str(read_fixture)],
    "write4096": [sys.executable, "-B", "-c",
        "from pathlib import Path; import hashlib,sys; p=Path(sys.argv[1]); p.write_bytes(b'x'*4096); print(hashlib.sha256(p.read_bytes()).hexdigest())",
        str(write_output)],
}
invocations = {
    name: CommandInvocation(argv=argv, cwd=str(worktree), shell=False)
    for name, argv in cases.items()
}
# Before EACH write observation: write_output.unlink(missing_ok=True)
# Then: result = broker.run(invocations[name], str(worktree), "t29-bench", timeout=30, force=True)
# Cache-mode no-op/read: run once force=True, then once force=False on same broker.
```

Both worktrees use the same relative ignored scratch paths and fixture bytes. The exact read-fixture SHA-256 for `bytes(range(256)) * 16` is `c8f5d0341d54d951a71b136e6e2afcb14d11ed8489a7ae126a8fee0df6ecf193`; recompute and assert this value during setup. Write expected digest is computed as `hashlib.sha256(b"x" * 4096).hexdigest()`.

## Pairing and metrics

- Freeze immutable baseline and candidate commit IDs plus hashes for `commands.py`, harness, config, and workload scripts. T06 confirms semantic owner boundary before any run.
- Measure the public `CommandBroker.run()` wall time with `time.perf_counter_ns()`; collect existing `phase_timings_ms` separately. Do not infer total latency by summing phases.
- For each workload and each execution mode, collect 30 matched pairs per block across 3 independent blocks (90 pairs total). Each pair runs both source versions once; alternate order AB/BA, with a fixed recorded seed. Restart the Python process between versions and blocks. Record raw pair values.
- **Forced execution:** `force=True` for no-op/read; writer always executes and must report `cache_hit=False`. **Cache path:** separate no-op/read immediate repeatable-cache-hit pairs; verify cold miss/warm hit and output/exit/revision parity. Never combine cached and executed timings.
- Report per workload/mode p50, p95, median paired delta, relative change, bootstrap 95% CI of the paired median delta (10,000 resamples; seed recorded), all raw observations, and host/toolchain/source fingerprints.
- Correctness gate: success, exit code, stdout, stderr, repository revision, and post-command scratch state must match between versions; no-op/read warm calls must be cache hits only in the cache mode; write calls must never be cache hits.

## Decision tolerance

Pre-register before run:

- Performance improvement only if candidate median latency is at least `max(1.0 ms, 5% of baseline median)` lower, the paired bootstrap 95% CI is entirely below zero, and the direction is faster in at least 2 of 3 blocks.
- Non-regression on each workload: candidate p95 may not exceed baseline p95 by more than `max(2.0 ms, 10%)`; no correctness, cache identity, authorization, or rollback regression is tolerated.
- If the measurement falls within tolerance, report **inconclusive/no material change**, not a win. If blocks disagree or host fingerprint changes, rerun only after T06 releases the slot and capture a new full 3-block set; never cherry-pick pairs.

## Independent review

Review the exact frozen branch diff against its parent, not only benchmark output. Verify `CommandBroker.run()` retains authorization, mutation classification, cache identity/invalidation, timeout/cancel, output truncation, repository revision, and rollback behavior. Check that benchmark workloads do not bypass the broker or mutate outside disposable scratch. Review outcome is separate from performance result.

## Report schema

Serialize UTF-8 JSON with sorted keys and compact separators; preserve raw observations (no rounded-only report). Required top-level keys and types:

```json
{
  "schema_version": 1,
  "task_id": "T29",
  "method": "paired_command_broker_run",
  "source": {
    "baseline": {"commit": "40-hex", "commands_sha256": "64-hex", "harness_sha256": "64-hex"},
    "candidate": {"commit": "40-hex", "commands_sha256": "64-hex", "harness_sha256": "64-hex"}
  },
  "environment": {"os": "string", "python": "string", "executable": "absolute path", "cpu": "string", "seed": 7341},
  "parameters": {"blocks": 3, "pairs_per_block": 30, "bootstrap_resamples": 10000, "modes": ["forced", "cache_hit"]},
  "observations": [{
    "workload": "noop|read4096|write4096", "mode": "forced|cache_hit",
    "block": 1, "pair": 1, "order": "AB|BA",
    "baseline_ms": 0.0, "candidate_ms": 0.0,
    "baseline_phases_ms": {}, "candidate_phases_ms": {},
    "baseline_success": true, "candidate_success": true,
    "baseline_exit_code": 0, "candidate_exit_code": 0,
    "baseline_stdout_sha256": "64-hex", "candidate_stdout_sha256": "64-hex",
    "baseline_stderr_sha256": "64-hex", "candidate_stderr_sha256": "64-hex",
    "baseline_repository_revision": "string", "candidate_repository_revision": "string",
    "baseline_cache_hit": false, "candidate_cache_hit": false,
    "baseline_scratch_sha256": "64-hex", "candidate_scratch_sha256": "64-hex"
  }],
  "summaries": [{
    "workload": "noop|read4096|write4096", "mode": "forced|cache_hit", "n": 90,
    "baseline_p50_ms": 0.0, "baseline_p95_ms": 0.0,
    "candidate_p50_ms": 0.0, "candidate_p95_ms": 0.0,
    "paired_median_delta_ms": 0.0, "relative_delta_pct": 0.0,
    "bootstrap_ci95_ms": [0.0, 0.0], "faster_blocks": 0,
    "parity": {"success": true, "exit_code": true, "stdout": true, "stderr": true,
                "repository_revision": true, "scratch_state": true, "cache_policy": true}
  }],
  "decision": {"performance_win": false, "non_regression": false,
                "result": "pass|fail|inconclusive", "reasons": []}
}
```

Numbers above are schema examples only, not measured results. `baseline_ms`/`candidate_ms` are unrounded wall durations in milliseconds; hashes bind outputs and scratch state without placing file contents in the report. One summary row per workload/mode; parity booleans must be computed from raw observations.

## Exact commands

Historical T15 command and result (Windows, 2026-09-29):

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_performance_acceptance.py
```

Result: `1 failed, 2 passed in 28.84s`. Failure: warm p50 was not lower than cold p50. Existing paired report had 30 shell-string and 30 structured-argv pairs; parity for output, exit code, and repository revision was true. Shell p50 cold/warm `125.221/145.743 ms`, p95 `260.887/194.943 ms`; structured argv p50 `124.397/151.391 ms`, p95 `392.820/201.915 ms`. Fingerprint p50/p95 cold `0.189/0.285 ms`, warm `143.065/191.750 ms`. Receipt `%TEMP%\t15-command-performance-restored-freshness-20260929.json`, SHA-256 `c89cdc0a80efb661950b4b246669fd27f9a815267593527e20bc32aa42f6f6ab`.

Existing no-op cold/warm diagnostic selector:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_command_concurrency_contract.py::test_cold_warm_command_benchmark_reports_paired_phase_percentiles
```

It runs 30 alternating cold/warm pairs but does not cover read/write or immutable branch-to-branch comparison. Do not run until T06 confirms source pins and the serial benchmark slot.

T29 branch-paired no-op/read/write measurements: **NOT RUN**. No comparable T06-frozen source pair or measured results available; no performance claim is made.
