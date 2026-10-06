# T02 artifact-backed model-free matrix plan

Date: 2026-10-01 (Europe/Prague)

## Purpose and gate

Prepare reproducible root/candidate artifacts for the six T02 synthetic workload cases. Do not launch the 100k cases until T20 grants the exclusive CPU slot. No root edits, GPU use, model inference, or live Hub/audio dependency in this model-free run.

The supported plan-grade sampler requires `1000` light samples, `30` comparison samples, and concurrency `1, 4, 16, 32`. The supported artifact path is one `--full-matrix` record per arm. It reruns the two smaller cases because the existing candidate-only records have three samples, lack a root pair, and cannot satisfy plan-grade sampling. Do not hand-assemble a matrix from smoke records.

## Frozen corpus identity

Preflight command, executed from the T02 candidate:

```powershell
C:\Python313\python.exe -B tools\prepare_t02_artifact_matrix.py --root C:\Users\Adam\.local-ai-hub --candidate C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub
```

Result: `status=ready_for_t20_slot`; root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; candidate HEAD `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`. Root and candidate benchmark scripts differ (SHA-256 `363FFAF81BFD2BE8567A4EC6EE76461E05756620EC924D5C48F71A4A6A520C96` vs `E93F2BBDA52B62018D8F2AE4C4F148F0CCB7E24C37F3A3C3F1EBEEB0D7412457`), as expected for implementation comparison. Their implementation fingerprints are pinned as `4622979dec2abacdd6e9f372b03643d5d8644a366592e0edf66d8ec25937c882` (root) and `2aff5d58ba7bdf933ea9bbb3f26049f529665e7dc2e64b9193a8b985c32741a7` (candidate). Their deterministic synthetic corpus generator identity matches: `0BDD678A79C06C96192FC8207B3A6FD385E0CC1FC469BEFFC0BFBF67DDEB0C96`.

Corpus is deterministic generated source plus deterministic `needle`/`filler` JSONL, pinned by generator SHA and case IDs below. Embeddings/model are `not_applicable_model_free_keyword_fixture`; do not label fixture relevance as semantic retrieval quality. Benchmark materializes data in each arm's external scratch directory only after T20 slot assignment; no 100k corpus was generated during preflight.

| Files | RAG chunks | Frozen corpus ID SHA-256 |
|---:|---:|---|
| 100 | 10,000 | `A9F649C37FDAE2123825AD6078AB2BD1BC16238EA98E13136E67506A82F3EC89` |
| 100 | 100,000 | `AE86AE9B31C12B78F51F31650EF2B65FD236D39D7521D01EB11B78BD6C680233` |
| 10,000 | 10,000 | `B48876C2F65110473AC88C74A64DB29C34671ABD46C2D359BB9221D12B87809D` |
| 10,000 | 100,000 | `43F6C841C3EB45AE43B14731A811132F7C8AC2559C6F5A3664BADA8A187FB4DB` |
| 100,000 | 10,000 | `B0A9208D53E58619F97E21EA3C37F9F62E5D2B7C2518D43135BE029EF33B12AF` |
| 100,000 | 100,000 | `78203AD25E2F9AE61B024BA5A7B1A8DCEF5700C9894C165C3DA4159988D5AEBC` |

## Slot execution

Run only after T20 assigns the slot. Execute root baseline first, candidate second, serially on the same host, Python, and hardware profile. Use a new directory outside both repositories. Preserve stdout JSON, stderr, all per-case JSON records, matrix record, and a SHA-256 manifest. Never overwrite a failed/timed-out attempt.

```powershell
$RunId = [guid]::NewGuid().ToString('N')
$ArtifactRoot = Join-Path $env:TEMP "t02-artifact-matrix-$RunId"
if (Test-Path -LiteralPath $ArtifactRoot) { throw "Artifact path already exists: $ArtifactRoot" }
$RootState = Join-Path $ArtifactRoot 'root\state'
$RootScratch = Join-Path $ArtifactRoot 'root\scratch'
$CandidateState = Join-Path $ArtifactRoot 'candidate\state'
$CandidateScratch = Join-Path $ArtifactRoot 'candidate\scratch'
$RootOut = Join-Path $ArtifactRoot 'root\stdout.json'
$RootErr = Join-Path $ArtifactRoot 'root\stderr.log'
$CandidateOut = Join-Path $ArtifactRoot 'candidate\stdout.json'
$CandidateErr = Join-Path $ArtifactRoot 'candidate\stderr.log'
New-Item -ItemType Directory -Path $RootState,$RootScratch,$CandidateState,$CandidateScratch | Out-Null

Push-Location 'C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub'
$PreflightLines = & 'C:\Python313\python.exe' -B tools\prepare_t02_artifact_matrix.py `
  --root 'C:\Users\Adam\.local-ai-hub' `
  --candidate 'C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub'
$PreflightExit = $LASTEXITCODE
Pop-Location
if ($PreflightExit -ne 0) { throw 'Frozen corpus preflight failed; do not start 100k work.' }
$PreflightRaw = [string]::Join([Environment]::NewLine, $PreflightLines)
$Preflight = $PreflightRaw | ConvertFrom-Json
if ($Preflight.status -ne 'ready_for_t20_slot') { throw 'Frozen corpus preflight is not ready.' }
$PreflightRaw | Set-Content -LiteralPath (Join-Path $ArtifactRoot 'preflight.json') -Encoding utf8

Push-Location 'C:\Users\Adam\.local-ai-hub'
& 'C:\Python313\python.exe' -B tools\benchmark_surfaces.py `
  --state-dir $RootState --scratch-dir $RootScratch --full-matrix `
  --light-repetitions 1000 --comparison-repetitions 30 `
  --concurrency 1 4 16 32 --timeout-seconds 3600 1> $RootOut 2> $RootErr
$RootExit = $LASTEXITCODE
Pop-Location
$RootRecord = Get-Content -Raw -LiteralPath $RootOut | ConvertFrom-Json
if ($RootRecord.success -ne $true -or $RootRecord.failed_cases.Count -ne 0 -or $RootRecord.metadata.completed_matrix.Count -ne 6) {
  throw "Root artifact matrix invalid; exit=$RootExit; preserve $ArtifactRoot"
}
if ($RootRecord.metadata.revision -ne $Preflight.root.head -or
    $RootRecord.metadata.implementation_fingerprint -ne $Preflight.root.implementation_fingerprint) {
  throw "Root record source identity drift; preserve $ArtifactRoot"
}
if ($RootRecord.metadata.baseline_readiness -eq 'plan_grade') {
  throw 'Unexpected model-free root plan_grade; inspect gates before comparison.'
}

Push-Location 'C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub'
& 'C:\Python313\python.exe' -B tools\benchmark_surfaces.py `
  --state-dir $CandidateState --scratch-dir $CandidateScratch --full-matrix `
  --light-repetitions 1000 --comparison-repetitions 30 `
  --concurrency 1 4 16 32 --timeout-seconds 3600 `
  --compare-with $RootRecord.record_path 1> $CandidateOut 2> $CandidateErr
$CandidateExit = $LASTEXITCODE
Pop-Location
$CandidateRecord = Get-Content -Raw -LiteralPath $CandidateOut | ConvertFrom-Json
if ($CandidateRecord.success -ne $true -or $CandidateRecord.failed_cases.Count -ne 0 -or $CandidateRecord.metadata.completed_matrix.Count -ne 6) {
  throw "Candidate artifact matrix invalid; exit=$CandidateExit; preserve $ArtifactRoot"
}
if ($CandidateRecord.metadata.revision -ne $Preflight.candidate.head -or
    $CandidateRecord.metadata.implementation_fingerprint -ne $Preflight.candidate.implementation_fingerprint) {
  throw "Candidate record source identity drift; preserve $ArtifactRoot"
}
if ($CandidateRecord.comparison.status -ne 'inconclusive') {
  throw "Expected model-free comparison gate; got $($CandidateRecord.comparison.status). Preserve $ArtifactRoot"
}
$RequiredMatches = @('benchmark_scope','workload_fingerprint','config_fingerprint','hardware_fingerprint')
foreach ($field in $RequiredMatches) {
  if ($RootRecord.metadata.$field -ne $CandidateRecord.metadata.$field) {
    throw "Root/candidate fingerprint mismatch: $field. Preserve $ArtifactRoot"
  }
}
if ($RootRecord.metadata.revision -eq $CandidateRecord.metadata.revision -or
    $RootRecord.metadata.implementation_fingerprint -eq $CandidateRecord.metadata.implementation_fingerprint) {
  throw "Root/candidate implementation identities did not differ. Preserve $ArtifactRoot"
}
$ArtifactFiles = Get-ChildItem -LiteralPath $ArtifactRoot -File -Recurse | Where-Object Name -notin @('SHA256SUMS.txt')
$ManifestLines = $ArtifactFiles | ForEach-Object { $h=Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256; '{0} *{1}' -f $h.Hash,$_.FullName.Substring($ArtifactRoot.Length+1) }
$ManifestLines | Set-Content -LiteralPath (Join-Path $ArtifactRoot 'SHA256SUMS.txt') -Encoding ascii
"artifact_root=$ArtifactRoot"
"root_exit=$RootExit candidate_exit=$CandidateExit"
"root_record=$($RootRecord.record_path)"
"candidate_record=$($CandidateRecord.record_path)"
"model_free_comparison=$($CandidateRecord.comparison.status)"
```

Exit code `2` is expected for these model-free `--full-matrix` records: the CLI reserves plan-grade readiness for model-dependent code-generation, vision, and speech goldens. Accept artifacts only if JSON says `success=true`, all six matrix rows completed, `failed_cases=[]`, and root/candidate match `benchmark_scope`, `workload_fingerprint`, `config_fingerprint`, and `hardware_fingerprint`. `revision` and `implementation_fingerprint` must differ. The candidate comparison is expected to say `inconclusive` because the model-dependent gates remain open; preserve that status. Do not call this end-to-end acceptance or suppress the exit code.

## Remains open

This run produces complete model-free six-case workload artifacts and plan-grade sample counts, not model-quality acceptance. Actual 100k CPU execution waits for T20's slot. Real Hub configuration/audio/transcript remain separate. Original combined `2/25` list and cause remain unknown; this run does not modify or resolve that RCA.
