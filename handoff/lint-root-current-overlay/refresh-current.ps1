param([ValidateSet('refresh1', 'refresh2', 'refresh3')][string]$SnapshotName = 'refresh1')
$ErrorActionPreference = 'Stop'
$taskOverlay = 'C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\lint-root-current-overlay'
$taskRefresh = Join-Path $taskOverlay $SnapshotName
$taskCapture = Get-Content -LiteralPath (Join-Path $taskOverlay 'capture.json') -Raw | ConvertFrom-Json
$taskEntries = foreach ($taskEntry in $taskCapture.files) {
    $taskFile = $taskEntry.path
    $taskSource = Join-Path $taskCapture.root $taskFile
    $taskPreimage = Join-Path (Join-Path $taskRefresh 'preimage') $taskFile
    $taskOwned = Join-Path (Join-Path $taskRefresh 'owned') $taskFile
    if ((Test-Path -LiteralPath $taskPreimage) -or (Test-Path -LiteralPath $taskOwned)) { throw "Refusing overwrite: $taskFile" }
    $taskBefore = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant()
    New-Item -ItemType Directory -Path (Split-Path -Parent $taskPreimage) -Force | Out-Null
    New-Item -ItemType Directory -Path (Split-Path -Parent $taskOwned) -Force | Out-Null
    Copy-Item -LiteralPath $taskSource -Destination $taskPreimage
    Copy-Item -LiteralPath $taskPreimage -Destination $taskOwned
    $taskCopy = (Get-FileHash -LiteralPath $taskPreimage -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskAfter = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant()
    if (($taskBefore -ne $taskCopy) -or ($taskBefore -ne $taskAfter)) { throw "Source drift during copy: $taskFile" }
    [pscustomobject]@{ path = $taskFile; pre_sha256 = $taskBefore; bytes = (Get-Item -LiteralPath $taskPreimage).Length }
}
[ordered]@{
    root = $taskCapture.root
    overlay = $taskRefresh
    captured_utc = [DateTime]::UtcNow.ToString('o')
    command = "& '$taskOverlay\refresh-current.ps1' -SnapshotName $SnapshotName"
    copy_method = 'PowerShell Copy-Item, exact bytes; hashes before/copy/after equal'
    baseline = $taskCapture.baseline
    replaces = 'publish-20261001T160429863497Z; root preimage drift before sealing'
    files = @($taskEntries)
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskRefresh 'capture.json') -Encoding utf8
$taskEntries | Select-Object path,pre_sha256 | ConvertTo-Json -Depth 3
