# T15 benchmark runbook (prepared, not executed)

Status: measurement pending. T20 confirmed baseline candidate `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; no integrated candidate SHA, clean harness pin, or exclusive CPU slot yet. This file records exact safe workflow; it does not authorize root tests or a benchmark run.

## Why existing reports do not count

`handoff/t15-command-broker-baseline.json` and `...-candidate.json` are historical only. Both report `working_tree_dirty=true` and `source_worktree_dirty=true`; baseline HEAD is `a77562e3210a175765eba914baa753f1b6a07c67`, candidate HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. They record commands source SHA `5e3fd81c...` vs `12dde723...`, benchmark SHA `acf50690...`, while current harness SHA is `e8fad3f7...`. Do not use them for acceptance or cite their old latency claim.

## Required pins and layout

Confirmed baseline pin: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` (T15 manifest base_head; commit exists, equals current root merge-base; `commands.py` blob SHA-256 `fdcf5432b154ff1ea2690bfe01016785c6dea85bda2b2f9a002e1a5e88cbb9ad`). T20 must provide `INTEGRATED_CANDIDATE_SHA`, `HARNESS_SHA`, and exclusive CPU slot. Use one clean harness checkout at a commit containing the harness below. Use separate clean detached execution worktrees pinned to the baseline and candidate commits. Keep inherited T15 candidate, root, and other owners' worktrees untouched. Create output directory outside every checkout, such as a unique directory under `$env:TEMP`. Worktree creation mutates shared Git metadata, so run these commands only after T20 assigns pins and confirms no conflicting root operation:

```powershell
$Repo = 'C:\Users\Adam\.local-ai-hub'
$Baseline = Join-Path $env:TEMP 't15-benchmark-baseline'
$Candidate = Join-Path $env:TEMP 't15-benchmark-candidate'
$Harness = Join-Path $env:TEMP 't15-benchmark-harness'
foreach ($path in @($Baseline,$Candidate,$Harness)) { if (Test-Path -LiteralPath $path) { throw "Worktree path already exists: $path" } }
git -C $Repo worktree add --detach $Baseline '824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11'
git -C $Repo worktree add --detach $Candidate '<INTEGRATED_CANDIDATE_SHA>'
git -C $Repo worktree add --detach $Harness '<HARNESS_SHA>'
```

The harness SHA must contain `tools/benchmark_command_broker.py`; preserve all three checkouts after run for audit. Do not remove or clean them as part of this task.

The harness checks:

- execution/source checkout clean and pinned at same commit (`metadata.source_git_head == metadata.git_head`, both dirty flags false);
- harness checkout clean and unchanged during each run;
- `commands.py` SHA, benchmark script SHA, source/execution/harness identities before and after;
- each invocation's cache state is isolated in a fresh `TemporaryDirectory` SQLite state; paired seed is forced miss and excluded from totals;
- paired cache outcomes and concurrent warm-hit/single-flight counts are classified exactly; raw sample arrays and environment are saved in report.

Harness does not require its clean revision to equal execution SHA; it records both. Hold harness commit/file SHA/config fingerprint constant for every arm/profile.

## Measurement design

Use two separately identified physical hardware profiles approved by T20. Do not emulate a second profile by changing metadata. For each 100/10,000/100,000-file cohort on each profile, run 15 adjacent paired blocks. Per invocation use `--light-samples 67 --paired-runs 2`; pooled per cohort this yields 1,005 light samples per concurrency and 30 expensive paired runs per revision. Use same pair-order seed for baseline and candidate within each block. Alternate which revision runs first using recorded schedule below; this balances temporal drift. Pair order inside cache miss/hit pairs is seeded and recorded by harness.

The T15 candidate also removes the command-log dispatcher's 50 ms idle poll after both output readers finish. Treat `stages.dual_stream_capture.wall_ms` as the direct target. Compare paired baseline/candidate p50 and p95 across all blocks. Use `stages.dual_stream_capture_without_callback.wall_ms` as a same-arm control. Keep callback integrity gates: `dropped_chunks` must be zero, `dispatch_incomplete` false, and delivered callback bytes equal captured stdout/stderr bytes. This capture slice does not replace the cache-latency acceptance threshold below.

Profile A schedule, seed `20261001`, baseline-first/candidate-first by block:

```text
candidate-first, baseline-first, baseline-first, candidate-first, baseline-first,
candidate-first, candidate-first, baseline-first, baseline-first, baseline-first,
candidate-first, candidate-first, candidate-first, baseline-first, baseline-first
```

Generate and save a separate balanced schedule for profile B with recorded seed before measurement. Save schedule and report receipts beside JSON reports in the unique external output directory.

## Master-plan fixtures and audit scope

The harness schema is `t15-command-broker-benchmark-v3`. It reports p50/p95/p99, raw latencies, and throughput for positive and invalid Python preflight fixtures. These fixtures are created inside the harness's temporary directory and do not dirty execution checkouts. The dual-stream fixture writes 2,000 lines to stdout and stderr; the harness checks exact callback byte totals, zero drops, and complete dispatch. The no-callback run is a control.

Master plan §2 requires p95/p99 regression checks and at least 25% p95 or peak-memory improvement on a proven bottleneck. It also requires correctness contracts for positive, invalid, and feature-disabled operations. T15 benchmark currently has no direct feature-disabled `CommandBroker.run` test; keep this as an open correctness gate. Existing classification p95 and old capture numbers are candidate-only or from dirty historical reports; they do not prove a paired improvement.

Master plan §3.1 asks for synthetic repositories with 100, 10,000, and 100,000 files. Prepare six disposable fixture worktrees per hardware profile: baseline and candidate source pin at each size. Generate each fixture only after T20 assigns source pins and the dedicated T02 slot. The fixture helper commits only `.t15-benchmark-fixture/`, records the original source pin in its manifest, and leaves a clean fixture commit whose parent is that pin.

```powershell
$FixtureSpecs = @(
    @{ Arm = 'baseline'; SourceSha = $BaselineSha; Count = 100 },
    @{ Arm = 'baseline'; SourceSha = $BaselineSha; Count = 10000 },
    @{ Arm = 'baseline'; SourceSha = $BaselineSha; Count = 100000 },
    @{ Arm = 'candidate'; SourceSha = $CandidateSha; Count = 100 },
    @{ Arm = 'candidate'; SourceSha = $CandidateSha; Count = 10000 },
    @{ Arm = 'candidate'; SourceSha = $CandidateSha; Count = 100000 }
)
foreach ($spec in $FixtureSpecs) {
    $fixture = Join-Path $env:TEMP "t15-benchmark-$Profile-$($spec.Arm)-$($spec.Count)"
    git -C $Repo worktree add --detach $fixture $spec.SourceSha
    python (Join-Path $Harness 'tools/prepare_command_broker_fixtures.py') `
        --worktree $fixture --source-pin-sha $spec.SourceSha --file-count $spec.Count
}
```

Run each matched block with `$Baseline`/`$Candidate` set to the matching fixture worktrees. Record fixture manifest SHA, fixture HEAD, source-pin parent, file count, and content-tree SHA in each receipt. Keep fixture generation outside measured time. T15 does not measure peak RSS; do not claim memory improvement. Thirty capture samples per arm/profile/cohort produce an empirical p99 with low tail confidence; report sample count and raw values.

For each count, set `$Baseline` and `$Candidate` to the corresponding generated worktrees. `$BaselineSha` and `$CandidateSha` remain the source pins supplied by T20; fixture commits must have those SHAs as parents. Set `$Profile` to the assigned physical profile name before running the generator block.

## Exact PowerShell template (execute only after T20 assignment)

```powershell
$Repo = 'C:\Users\Adam\.local-ai-hub'
$Harness = '<clean harness worktree containing tools/benchmark_command_broker.py>'
$Baseline = Join-Path $env:TEMP 't15-benchmark-baseline'
$Candidate = '<clean detached worktree at INTEGRATED_CANDIDATE_SHA>'
$Evidence = Join-Path $env:TEMP ('t15-benchmark-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Evidence | Out-Null

# Pin and prove each checkout before running. Stop if any status output is nonempty.
$Expected = @(@{Path=$Harness; Sha='<HARNESS_SHA>'}, @{Path=$Baseline; Sha='824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11'}, @{Path=$Candidate; Sha='<INTEGRATED_CANDIDATE_SHA>'})
foreach ($item in $Expected) {
    $head = (git -C $item.Path rev-parse HEAD).Trim()
    $dirty = @(git -C $item.Path status --porcelain)
    if ($head -ne $item.Sha -or $dirty.Count -ne 0) { throw "Checkout pin/cleanliness failed: $($item.Path)" }
}

# Profile A schedule. Profile B substitutes its recorded seed/order from above.
$Profile = 'profile-a'
$First = @('candidate-first','baseline-first','baseline-first','candidate-first','baseline-first','candidate-first','candidate-first','baseline-first','baseline-first','baseline-first','candidate-first','candidate-first','candidate-first','baseline-first','baseline-first')
$PairSeedBase = 41000
Push-Location $Harness
try {
    foreach ($Block in 1..15) {
        $PairSeed = $PairSeedBase + $Block
        $Arms = if ($First[$Block - 1] -eq 'baseline-first') { @('baseline','candidate') } else { @('candidate','baseline') }
        foreach ($Arm in $Arms) {
            $ExecutionRoot = if ($Arm -eq 'baseline') { $Baseline } else { $Candidate }
            $Stem = "$Profile-block-$('{0:D2}' -f $Block)-$Arm"
            $Output = Join-Path $Evidence ($Stem + '.json')
            $Log = Join-Path $Evidence ($Stem + '.log')
            if ((Test-Path -LiteralPath $Output) -or (Test-Path -LiteralPath $Log)) { throw "Evidence already exists: $Stem" }
            "python -B tools/benchmark_command_broker.py --root $ExecutionRoot --light-samples 67 --paired-runs 2 --pair-order-seed $PairSeed --output $Output" | Set-Content -LiteralPath $Log -Encoding utf8
            python -B tools/benchmark_command_broker.py --root $ExecutionRoot --light-samples 67 --paired-runs 2 --pair-order-seed $PairSeed --output $Output 2>&1 | Tee-Object -FilePath $Log -Append
            if ($LASTEXITCODE -ne 0) { throw "Benchmark failed: profile=$Profile block=$Block arm=$Arm" }
            Get-FileHash -Algorithm SHA256 -LiteralPath $Output,$Log
        }
    }
} finally { Pop-Location }
```

Exact first candidate command for profile A, block 1 (schedule is candidate-first; run from pinned `$Harness`):

```powershell
python -B tools/benchmark_command_broker.py --root $Candidate --light-samples 67 --paired-runs 2 --pair-order-seed 41001 --output (Join-Path $Evidence 'profile-a-block-01-candidate.json')
```

Its paired baseline command substitutes `--root $Baseline` and output `profile-a-block-01-baseline.json`; both use same harness/config/seed.

## Receipt validation after each profile

Run from the profile output directory after all blocks. Set the expected pins exactly; fail closed on any report or cache mismatch. The script records each JSON/log SHA plus identities/config in `receipt.json`.

```powershell
$Evidence = '<same unique output directory used above>'
$Profile = 'profile-a'
$First = @('candidate-first','baseline-first','baseline-first','candidate-first','baseline-first','candidate-first','candidate-first','baseline-first','baseline-first','baseline-first','candidate-first','candidate-first','candidate-first','baseline-first','baseline-first')
$ExpectedHarness = '<HARNESS_SHA>'
$ExpectedHarnessScript = '<HARNESS_SCRIPT_SHA>'
$ExpectedBaseline = '824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11'
$ExpectedCandidate = '<INTEGRATED_CANDIDATE_SHA>'
$PairSeedBase = 41000
$Files = @(Get-ChildItem -LiteralPath $Evidence -Filter "$Profile-block-*.json" | Sort-Object Name)
if ($Files.Count -ne 30) { throw "Expected 30 reports, got $($Files.Count)" }
$Receipts = foreach ($file in $Files) {
    $report = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
    $arm = if ($file.BaseName.EndsWith('-baseline')) { 'baseline' } elseif ($file.BaseName.EndsWith('-candidate')) { 'candidate' } else { throw "Unknown arm: $($file.Name)" }
    $expected = if ($arm -eq 'baseline') { $ExpectedBaseline } else { $ExpectedCandidate }
    if ($file.BaseName -notmatch '-block-(\d{2})-') { throw "Bad block name: $($file.Name)" }
    $Block = [int]$Matches[1]
    $ScheduledFirst = $First[$Block - 1]
    $LogPath = Join-Path $Evidence ($file.BaseName + '.log')
    if (-not (Test-Path -LiteralPath $LogPath)) { throw "Log receipt missing: $LogPath" }
    $m = $report.metadata
    $a = $report.stages.cache_pair_order.accounting
    if (-not $report.success -or $m.git_head -ne $expected -or $m.source_git_head -ne $expected -or $m.source_worktree_dirty -or $m.working_tree_dirty -or $m.harness_worktree_dirty -or $m.harness_git_head -ne $ExpectedHarness -or $m.benchmark_script_sha256 -ne $ExpectedHarnessScript -or $m.harness_identity_unchanged -ne $true -or $m.source_identity_unchanged -ne $true -or $m.execution_root_identity_unchanged -ne $true -or $m.pair_order_seed -ne ($PairSeedBase + $Block)) { throw "Revision/cleanliness receipt failed: $($file.Name)" }
    if ($a.paired_operations -ne 4 -or $a.expected_hits -ne 2 -or $a.observed_hits -ne 2 -or $a.expected_misses -ne 2 -or $a.observed_misses -ne 2 -or -not $a.classification_complete) { throw "Cache pair receipt failed: $($file.Name)" }
    foreach ($entry in $report.stages.concurrent_warm_cache_hits.PSObject.Properties) {
        if ($entry.Value.calls.n -ne 67 -or $entry.Value.observed_cache_hits -ne 67 -or $entry.Value.observed_cache_misses -ne 0 -or $entry.Value.seed_cache_hit -ne $false -or $entry.Value.classified_calls -ne 67) { throw "Warm-cache receipt failed: $($file.Name), workers=$($entry.Name)" }
    }
    [pscustomobject]@{ report=$file.Name; report_sha256=(Get-FileHash -Algorithm SHA256 $file.FullName).Hash.ToLower(); log=$LogPath; log_sha256=(Get-FileHash -Algorithm SHA256 $LogPath).Hash.ToLower(); profile=$Profile; block=$Block; created_at_utc=$report.created_at_utc; scheduled_first=$ScheduledFirst; pair_order_seed=$m.pair_order_seed; arm=$arm; head=$m.git_head; commands_sha256=$m.working_tree_commands_sha256; harness_head=$m.harness_git_head; harness_sha256=$m.benchmark_script_sha256; config_fingerprint=$m.config_fingerprint; platform=$m.platform; cpu=$m.cpu; logical_cpus=$m.logical_cpus; memory_bytes=$m.total_memory_bytes; python=$m.python; shell=$m.shell_version; git=$m.git_version; paired_runs=$m.paired_expensive_runs }
}
foreach ($arm in @('baseline','candidate')) {
    $group = @($Receipts | Where-Object arm -eq $arm)
    if ($group.Count -ne 15 -or (($group | Measure-Object -Property paired_runs -Sum).Sum -ne 30)) { throw "Pooled sample count failed: $arm" }
    if (@($group.config_fingerprint | Select-Object -Unique).Count -ne 1 -or @($group.harness_sha256 | Select-Object -Unique).Count -ne 1 -or @($group.commands_sha256 | Select-Object -Unique).Count -ne 1) { throw "Config/source/harness drift: $arm" }
    foreach ($field in @('platform','cpu','logical_cpus','memory_bytes','python','shell','git')) {
        if (@($group | Select-Object -ExpandProperty $field | Select-Object -Unique).Count -ne 1) { throw "Environment drift: $arm/$field" }
    }
}
if (@($Receipts.config_fingerprint | Select-Object -Unique).Count -ne 1 -or @($Receipts.harness_sha256 | Select-Object -Unique).Count -ne 1) { throw 'Baseline/candidate config or harness mismatch' }
foreach ($field in @('platform','cpu','logical_cpus','memory_bytes','python','shell','git')) {
    if (@($Receipts | Select-Object -ExpandProperty $field | Select-Object -Unique).Count -ne 1) { throw "Baseline/candidate environment mismatch: $field" }
}
foreach ($Block in 1..15) {
    $paired = @($Receipts | Where-Object block -eq $Block)
    if ($paired.Count -ne 2 -or @($paired.arm | Select-Object -Unique).Count -ne 2 -or @($paired.pair_order_seed | Select-Object -Unique).Count -ne 1) { throw "Incomplete matched block: $Block" }
    $expectedFirst = if ($paired[0].scheduled_first -eq 'baseline-first') { 'baseline' } else { 'candidate' }
    $actualFirst = ($paired | Sort-Object created_at_utc)[0].arm
    if ($actualFirst -ne $expectedFirst) { throw "Arm order receipt failed: block=$Block" }
}
$ReceiptPath = Join-Path $Evidence 'receipt.json'
if (Test-Path -LiteralPath $ReceiptPath) { throw "Receipt already exists: $ReceiptPath" }
$Receipts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8
Get-FileHash -Algorithm SHA256 -LiteralPath $ReceiptPath
```

Run identical workflow on profile B with separate output directory, `$Profile = 'profile-b'`, schedule seed `20261002`, and this saved 15-block order: `baseline-first, candidate-first, baseline-first, baseline-first, candidate-first, baseline-first, candidate-first, baseline-first, candidate-first, baseline-first, baseline-first, candidate-first, candidate-first, candidate-first, baseline-first`. For profile B use its profile-specific fresh worktree/output paths; set `$First` to profile B order in both run and receipt snippets. Update `$ExpectedHarnessScript` to the pinned script SHA. Each profile requires its own clean worktrees/hardware; run from the same pinned harness commit/file SHA. Preserve each immutable JSON report and record its SHA-256 in a receipt manifest; also record slot owner, profile identity, schedule seed/order, block, arm, all three SHAs, config fingerprint, exact command, exit code, and log SHA. Output path is outside harness and both execution roots, satisfying harness guard.

## Acceptance calculation / stop rules

Aggregate raw arrays by file-count cohort and arm/profile; report nearest-rank p50, p95, and p99 plus sample counts and raw values. Verify exactly 30 paired hit/miss rows per arm/cohort, 1,005 classified warm samples at each concurrency, zero warm misses, forced seed miss, and expected single-flight execution/waiter totals. Report positive and invalid preflight p50/p95/p99 separately. All identity/cleanliness unchanged flags must be true. Baseline/candidate within a profile must match Python, OS, CPU, memory, shell/Git versions, harness SHA, fixture content-tree SHA, and config fingerprint; any mismatch invalidates that profile pair.

Apply release threshold from acceptance contract per cohort: demonstrate at least 25% p95 improvement on a measured bottleneck, with no unexplained warm/cold p95/p99 regression above 10%. This harness does not measure peak RSS, so do not claim memory improvement. Report raw distributions and paired deltas; do not collapse hardware profiles. Stop on any dirty checkout, identity/hash drift, unclassified cache result, incomplete sample count, failed process/capture, or missing profile. T20 must separately assign root pytest slot before root selectors run.

## Selector, warm-up, counters, and rollback boundary

Request one T20 performance selector only: `tools/benchmark_command_broker.py`, target stage `stages.dual_stream_capture.wall_ms`, paired baseline vs integrated candidate. Use the exact invocation above with `--root $ExecutionRoot --light-samples 67 --paired-runs 2 --pair-order-seed $PairSeed --output $Output`; run once for each arm in each matched block with the same seed and pinned harness. This selector measures callback-enabled stream capture; `stages.dual_stream_capture_without_callback.wall_ms` is its same-arm control. Do not request or run pytest selectors in this CPU slot.

There is no separate discarded warm-up loop. Each invocation uses fresh temporary SQLite state. Cache-pair measurement makes one forced seed miss, excluded from pair totals, then records two pairs (`2` hits, `2` misses). Concurrent warm-hit measurement makes one normal seed miss, then records `67` classified calls at each concurrency `(1, 4, 16, 32)`; all must hit. Each invocation also records 67 valid and 67 invalid preflight samples, 67 warm fingerprint samples, two timed forced-fingerprint samples, and two callback-enabled plus two callback-disabled capture samples. Across 15 blocks, each arm/profile/cohort therefore has 30 stream samples, 30 paired hits, 30 paired misses, and 1,005 warm-hit samples at each concurrency. Forced seed misses are reported but excluded from paired cache counts.

Existing `t15-command-broker-baseline.json` and `t15-command-broker-candidate.json` are not valid paired receipts: both report dirty execution/source trees, use stale harness SHA `acf506907113e17f8fd39de282c5e7e9394d8f6e3c553ebc3dc251145da93c2f`, and contain no `stages.cache_pair_order.accounting`. Their historical timings cannot establish acceptance. No clean integrated-candidate receipt exists.

Security scope: this performance change only replaces the command-log dispatcher's 50 ms idle polling with blocking queue wait and sentinel shutdown. Bounded queue, validated command argv, `shell=False`, broker policy, environment filtering, cache identity, and output-byte integrity gates remain in force. POSIX process-group, `PermissionError`, and daemon recovery behavior stay T06-owned and are outside this selector.

Rollback scope: isolate the queue-dispatcher hunk in its own T15 commit after T20 supplies a clean integrated pin. If acceptance fails, revert only that isolated commit, restoring timeout polling; do not reset `commands.py` or revert mixed T06 recovery, cache, policy, or other owner's hunks. Current dirty candidate is not a safe whole-file rollback unit. Preserve failed benchmark JSON/log receipts.

## Root-current consumer parity gate

Read-only root snapshot and bounded behavior receipts are recorded in `t15-root-current-parity-receipt.json`; T15-owned test patch is `t15-root-current-parity-tests.patch` for `tests/test_t15_root_parity_acceptance.py`. T15 candidate ran its four selectors with isolated temporary fixtures; root source received four bounded direct behavior probes. Root pytest was not run. After T20 integrates the test file and assigns the root pytest slot, run exactly:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t15_root_parity_acceptance.py
```

This acceptance test covers explicit aliases, literal/reference env handling, linked-worktree overrides, affected mapping plus complete uncertain fallback under path hints, public streaming cancellation, and bounded stdout artifact. It does not replace the paired performance run above. The reported `+16.7%` p95 remains unverified until clean baseline/candidate receipts exist.

## Bounded command-config CPU microbenchmark

Run only this small model-free comparison while the large T15 performance slot is pending:

```powershell
python -B tools/t15_config_parity_microbench.py
```

The harness imports the actual `CommandBroker` from the recorded root and candidate source trees. Both arms use one identical temporary project config, explicit `bench` alias, isolated state directories, and the same fixed `sum(i*i for i in range(20000))` child command. It runs seven randomized paired blocks, times with `perf_counter_ns`, and uses no tracing, GPU, network, or shared port. It records source hashes before and after and saves `handoff/t15-config-parity-microbench.json`.

Pre-cache snapshot result: root median 130.5709 ms; candidate median 153.1228 ms across seven pairs. Candidate was slower in this small sample; this is descriptive only and `acceptance=false`. It does not satisfy or replace the large paired performance acceptance. The recorded candidate source SHA is in the microbenchmark receipt; a later candidate-only resolver cache changed `commands.py`, so this result is historical for the pre-cache candidate and is stale for current candidate performance. Do not rerun paired timing until T20 grants the exclusive slot.

The one-shot source probe found one `git rev-parse --git-common-dir` taking 127.9788 ms wall on a non-Git fixture; config-layer resolution took 0.893 ms and eight `Path.resolve` calls took 1.171 ms. T15 added an in-memory, 64-entry project-config resolution cache in the owned command wrapper. Its key hashes the canonical project-root identity, actual config-file signatures, and exact Git HEAD; host environment references are read on every invocation. Cache data is not written to disk. Config-signature and Git-revision invalidation tests plus the owned parity modules pass 114 tests. No post-cache benchmark was run; the full slot remains T20-owned.

Current root `project_config.py` SHA is `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`; earlier direct root alias/worktree probe used SHA `6050453fa90c83f0282c4dd2588cac4454b5187f9c85521cf7aabf089e41c832` and is stale for that path. T16 producer diff adds `ProjectContext.coordination_id` and `_git_primary_worktree_root`; do not count the earlier receipt as current-root parity. T20 was asked for a concrete exclusive large-performance slot through the main handoff; root pytest remains unrun.

## Static benchmark preflight review — 2026-10-02

Read-only review of `tools/benchmark_command_broker.py` confirms these acceptance guards:

- `run_benchmark` requires a 64-character SHA-256 and matches it to the selected `commands.py` before importing the command API (lines 414-433).
- Source and execution checkouts must be clean and share one HEAD; harness checkout must also be clean (lines 104-108, 207-214, 431-433).
- Source, execution checkout, and harness identity are compared again after sampling; any change aborts the report (lines 605-612).
- CLI rejects output inside either checkout and rejects reused output paths (lines 703-723).

This is static guard review only. No test or benchmark ran. It does not establish a clean integrated candidate, T02 paired-matrix pass, exclusive T20 benchmark slot, or performance result. Preserve these gates before execution.
