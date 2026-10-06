# T15 root-current paired benchmark acceptance checklist

Status: `CORRECTNESS_SLOT_D_PASSED_158_3SKIPPED_RELEASED; SLOT_G_UNKNOWN_NO_RETRY; BENCHMARK_PENDING_T02_GREEN_AND_CLEAN_T20_CANDIDATE_PIN`.

## Latest correctness slot D — passed and released

T20 assigned `T20-SERIAL-20261002-D` for one correctness batch. Slot D was explicitly released after this run; no benchmark ran.

Exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_path_hints.py tests/test_project_config_service_integration.py tests/test_project_command_broker.py tests/test_command_cache_singleflight_contract.py tests/test_command_concurrency_contract.py tests/test_benchmark_command_broker.py tests/test_t15_paired_benchmark_contract.py
```

Broker receipt: request `req_c1fecef1dc79`, execution `b9951139e5a143f79b22f9a3927c25f2`, `success=true`, exit `0`, duration `38156.5 ms`; **158 passed, 3 skipped**. Skips require Linux `/proc` process identity or POSIX process groups. `log_chunks_dropped=0`; `log_dispatch_incomplete=false`. The broker omitted `terminal` and `retryable`; its repository revision fingerprint was `855ba3b8e465a8a98a89fd3afd04a89ba5631d7aa7eadb4c8253400ce91c9a2c`.

Pre-run root/HEAD: `C:\Users\Adam\.codex\worktrees\t15-command-config\.local-ai-hub`, `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Pre-run SHA-256: `src/local_ai_hub/project_config.py` `1F6885E8B5A6E5A0BD6524BC9B896D2BDFFBDDD756143CF0F24C40A8452A31DD`; `tests/test_project_config.py` `77FC230594A91ADE6D75F59DDC6FE60913011106ADCC6299A9DB7121203D1EB6`; T06-owned `src/local_ai_hub/commands.py` `8EE6ACA27FA1FF4EA4ADC2686A426EC469E9B35955D60E264027BAE735D5020A`. Post-run file hashes were not returned; no extra command was run to collect them.

T20 later reported slot G as `UNKNOWN`. Do not retry or infer a benchmark result from that slot. Next performance acceptance still requires a clean integrated candidate pin, T02's green paired-matrix gate, and a separate T20 serial benchmark slot.

## Source and harness pins

Verified pin manifest: `handoff/T15-pinned-source-manifest-20261002.json`, SHA-256 `F37C79640A65F01B564A844718EADEA87D8018CEF8CD7AEB81ECFD9F856687E2`.

| Role | Revision / file | SHA-256 | Readiness |
|---|---|---|---|
| Baseline | commit `01df56605ccf484ebfe2808ac60d696c4e81dffc`; `src/local_ai_hub/commands.py` raw SHA-256 | `5E3FD81C4AB55633A165237AE5C828CA2B73ACE353DA403DB67C98C65128E1D3` | Clean baseline checkout recorded; raw bytes verified |
| Candidate | scratch commit `b38981611868221755ff899e9f5e40aa68a6c88e`; `src/local_ai_hub/commands.py` raw SHA-256 | `845348F2E362852561AE2EBB1B3F5458C8915E0134B1EC884F47356132B9FECB` | Clean scratch checkout; integrated T20 candidate revision still required |
| Candidate dependency | `src/local_ai_hub/command_transactions.py` | `247E49200044B4ACF2A1B261412F187C4688DE3CF0C9672AE582FD14EA1F029D` | Candidate-only dependency; absent at baseline; candidate runtime not verified |
| Candidate dependency | `src/local_ai_hub/work_fencing.py` | `C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0` | Candidate-only dependency; absent at baseline; candidate runtime not verified |
| T15 harness | `tools/benchmark_command_broker.py` | `EBEB3CB11265BE699D0836E95564D2289AAE3093392AD698B82DDD50F6EBCB8F` | Requires `--expected-commands-sha256`, checked before source import; guard not yet tested; clean committed harness checkout still required |
| Fixture preparer | `tools/prepare_command_broker_fixtures.py` | `4C83E5472C55C790E8F767BF4F54AEADC5024BF76F4299CF0FDB581B70255A74` | Pin before run |

Before release, T20 must provide integrated candidate commit and a T15 serial slot. T02 slot 05 ended interrupted: baseline-only partial output was preserved and no paired receipt was produced, so the T02 green-matrix gate is not met. T11 used the released slot for 93 passing checks. T15 must not infer a green paired gate from earlier receipts.

The candidate imports two files absent from baseline. Baseline and candidate must each pass a non-measuring import/preflight using only their pinned source trees, or the comparison is invalid and must stop for owner review. Do not copy candidate dependencies into baseline. The raw baseline/candidate `commands.py` hashes above must be passed as `--expected-commands-sha256`; the runner checks the pin before source import and records it in result metadata. Minimum source-contract selectors (not run): `tests/test_benchmark_command_broker.py::test_run_benchmark_rejects_wrong_commands_pin_before_loading_api` and `tests/test_benchmark_command_broker.py::test_revision_gate_requires_clean_matching_checkouts`. Run these as a short correctness slot, separately from any paired benchmark slot.

## Correctness slot 08 — outcome unknown

T20 assigned slot `T20-CPU-SLOT-20261002-08` after T04 released slot 07. The two contract selectors were submitted once through `local_ai_command`:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_benchmark_command_broker.py::test_run_benchmark_rejects_wrong_commands_pin_before_loading_api tests/test_benchmark_command_broker.py::test_revision_gate_requires_clean_matching_checkouts
```

Record exact command, exit code, output, and source/test hashes. Paired benchmark remains separate and requires its own later T20 slot plus integrated clean candidate pin; do not combine correctness and performance run.

Broker returned `outcome_unknown=true`, request ID `req_c346aa085510`; `terminal` and `retryable` were absent. No verifiable test result exists. No retry or native fallback. One read-only process check identified only its own `pwsh.exe` shell as a selector-text self-match; no pytest runner was identified and nothing was terminated. T20 was explicitly notified that slot 08 is released. Hash-bound receipt: `handoff/t15-correctness-slot08-receipt-20261002.json`; final SHA-256 recorded in the manifest.

## Coverage and parity

- Use identical committed harness, Python, Git, broker-selected shell, OS, benchmark options, tenant, command set, and fixture preparation for both revisions.
- Pair cache-hit and forced-cache-miss samples using the same `git status --short` command and same tenant. Use balanced randomized hit-first/miss-first order; preserve per-pair outcomes and both order strata.
- Capture the harness's full planned coverage: cache hit/miss, warm-cache concurrency, single-flight owner/waiter/execution counts, structured and shell startup, dual-stream capture with callback on/off, output bytes, callback drops, and memory/platform metadata. Any missing scenario, classification, sample, or fixture outcome invalidates the pair.
- Require exactly 30 hit/miss pairs, 30 of each outcome; require 1,000 warm hits and zero misses at every concurrency level, with the separately recorded seed miss excluded. Record every returned sample index and elapsed time.
- Record source/execution HEAD, `commands.py` hash, harness hash, fixture command/tenant/seed, clean status, and before/after hashes for both checkouts. Record repository tracked-file count and worktree cleanliness for corpus context; do not claim identical source corpus across different commits.

## Warm-cache hotspot hypothesis and next measurement

Source review locates fixed work before a command-cache hit: `CommandBroker.run` constructs `_key`; `_key` calls `repo_state.fingerprint(cwd)` and includes environment, tool identity, policy, and cache context before `success_cache.get` (`src/local_ai_hub/commands.py`, current T15 lines 2641-2672 and 3591-3600). This is a hotspot hypothesis, not a measured bottleneck. The current harness reports end-to-end samples, not isolated key-construction time.

Measure this path with the existing paired `git status --short` fixture. Keep the 30 balanced hit/miss pairs and 1,000 warm hits per concurrency level; compare warm-hit p50/p95/p99 and cold/forced-miss p50/p95/p99 separately. Use the already specified order seed, tenant, source pins, and identical host profile. Treat a warm-hit change as end-to-end evidence only; do not attribute it to key construction without separate instrumentation. Preserve the existing 25% improvement target and 10% regression guard above.

No cache-key shortcut is proposed: skipping repository/tool/environment fingerprints could reuse stale results. Any instrumentation or optimization in `_key`, `CommandBroker.run`, or `RepoStateTracker` overlaps T06 ownership and needs T06 coordination before editing. Current safe next step is the paired measurement after the integrated clean candidate pin, T02 green paired-matrix gate, and a separate T20 benchmark slot are available. Slot G is `UNKNOWN`; do not retry it or treat it as a measurement.

## Measurement and acceptance

- Run `--light-samples 1000 --paired-runs 30 --pair-order-seed 731` unchanged for both members of the pair. Save separate fresh JSON outputs outside every repository. This is one paired measurement: one baseline invocation plus one candidate invocation.
- Report cold/forced-miss and warm-hit p50, p95, and p99 separately; report raw order strata and explain material order effects. No unexplained warm or cold p95/p99 regression above 10%.
- Demonstrate at least 25% p95 or peak-memory improvement on the identified bottleneck. Keep peak RSS and peak VRAM separate; include availability and units. Command-broker runs without a GPU adapter must record VRAM as not measured, never as zero.
- Record OS, CPU model/architecture/core count, RAM, GPU/VRAM availability, Python, Git, shell, and system load for each run. Baseline/candidate pair must use same CPU/hardware profile. T20 must enumerate required profiles; one machine cannot stand in for all profiles. GPU is not a command-broker acceptance requirement unless T20 assigns a GPU profile.
- Compare peak-memory values only within matching platform/profile and measurement method. Do not combine RSS and VRAM into one metric or use prior v1 receipts as current acceptance evidence.

## Prepared runner invocations (not executed)

After T02 green, T20's explicit serial-slot release, integrated candidate pin, and successful source-only preflight, invoke the committed harness twice with fresh output names outside all repositories:

```powershell
python -B tools/benchmark_command_broker.py --root C:\Users\Adam\.codex\worktrees\t15-pin-baseline-20261002 --expected-commands-sha256 5E3FD81C4AB55633A165237AE5C828CA2B73ACE353DA403DB67C98C65128E1D3 --light-samples 1000 --paired-runs 30 --pair-order-seed 731 --output <outside-repositories>\t15-<run-id>-baseline.json
python -B tools/benchmark_command_broker.py --root <integrated-clean-candidate-checkout> --expected-commands-sha256 <integrated-candidate-commands.py-sha256> --light-samples 1000 --paired-runs 30 --pair-order-seed 731 --output <outside-repositories>\t15-<run-id>-candidate.json
```

Use the same unique run ID, harness checkout, and output parent for the pair. Never reuse output paths. Candidate hash placeholder must be replaced only after T20 supplies the clean integrated candidate pin.

## Gate and pin-guard attempt

T02 slot 05 ended interrupted during its baseline matrix. Partial output retained; no paired receipt and no candidate run. T02 released the slot to T11; this does not satisfy the T02 green paired-matrix gate.

Before the test request, process snapshot reported `NO_TEST_OR_BENCHMARK_PROCESS`. Pin-guard test source SHA-256: `EF6694A482A2ADCA37CD6824F74CA492166C1F698F01BBD1F71FB16483753909`; runner SHA-256: `8AEF9B315B44B1A15BAD0A52B79213F2F4A319E6BCD84DDA240778F2C32930AB`.

Requested once through `local_ai_command`:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_benchmark_command_broker.py::test_run_benchmark_rejects_wrong_commands_pin_before_loading_api
```

Result: not run. Hub returned `request_not_sent=true`, `outcome_unknown=false`, request ID `req_514745573c2e`; `terminal` and `retryable` were absent. Native test fallback therefore remains unavailable. No benchmark ran. T20 integrated candidate pin is still required before any paired benchmark.

## Configuration safety receipt — 2026-10-02

Static review of the T15-owned loader confirms:

- `_safe_config_file` resolves the config path and rejects targets outside the layer's containment root before open (`src/local_ai_hub/project_config.py:771-787`).
- `_read_layer` opens with `O_NOFOLLOW` where available, then checks regular-file mode and matching device/inode before reading; it caps input at `_MAX_CONFIG_BYTES` (`:727-768`).
- `_resolve_project_config` validates each layer before merge and returns defaults atomically on an invalid layer (`:802-844`).

Regression selectors in `tests/test_project_config.py` cover invalid lower-layer masking, verification alias defined in a lower layer, and opening the resolved path that passed containment. They were included in T20 serial slot D batch. Aggregate receipt: request `req_c1fecef1dc79`, execution `b9951139e5a143f79b22f9a3927c25f2`, exit 0, 158 passed / 3 platform skips, 38.1565 s. The broker did not provide per-module counts; no targeted rerun is claimed. Slot D was explicitly released. No test ran in this update.
