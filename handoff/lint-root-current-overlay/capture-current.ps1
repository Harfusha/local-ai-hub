$ErrorActionPreference = 'Stop'
$taskRoot = 'C:\Users\Adam\.local-ai-hub'
$taskOverlay = 'C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\lint-root-current-overlay'
$taskFiles = @(
    'src/local_ai_hub/agent_incidents.py',
    'src/local_ai_hub/benchmark.py',
    'src/local_ai_hub/browser_bridge.py',
    'src/local_ai_hub/client.py',
    'src/local_ai_hub/deterministic.py',
    'src/local_ai_hub/generator.py',
    'src/local_ai_hub/pipeline.py',
    'src/local_ai_hub/response_protocol.py',
    'src/local_ai_hub/scheduler.py',
    'src/local_ai_hub/supervisor.py',
    'src/local_ai_hub/token_economy.py',
    'src/local_ai_hub/repo_tools.py',
    'tools/benchmark_command_broker.py',
    'tools/benchmark_surfaces.py'
)
$taskEntries = foreach ($taskFile in $taskFiles) {
    $taskSource = Join-Path $taskRoot $taskFile
    $taskPreimage = Join-Path (Join-Path $taskOverlay 'preimage') $taskFile
    $taskOwned = Join-Path (Join-Path $taskOverlay 'owned') $taskFile
    if ((Test-Path -LiteralPath $taskPreimage) -or (Test-Path -LiteralPath $taskOwned)) {
        throw "Existing snapshot; refusing overwrite: $taskFile"
    }
    $taskBefore = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant()
    New-Item -ItemType Directory -Path (Split-Path -Parent $taskPreimage) -Force | Out-Null
    New-Item -ItemType Directory -Path (Split-Path -Parent $taskOwned) -Force | Out-Null
    Copy-Item -LiteralPath $taskSource -Destination $taskPreimage
    Copy-Item -LiteralPath $taskPreimage -Destination $taskOwned
    $taskCopy = (Get-FileHash -LiteralPath $taskPreimage -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskAfter = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant()
    if (($taskBefore -ne $taskCopy) -or ($taskBefore -ne $taskAfter)) {
        throw "Root changed during snapshot: $taskFile"
    }
    [pscustomobject]@{ path = $taskFile; pre_sha256 = $taskBefore; bytes = (Get-Item -LiteralPath $taskPreimage).Length }
}
$taskManifest = [ordered]@{
    root = $taskRoot
    overlay = $taskOverlay
    captured_utc = [DateTime]::UtcNow.ToString('o')
    command = "& '$taskOverlay\capture-current.ps1'"
    copy_method = 'PowerShell Copy-Item, exact bytes; hashes before/copy/after equal'
    baseline = 'User-provided genuine full-root Pyflakes exit 1, 31 diagnostics; not rerun'
    files = @($taskEntries)
}
$taskManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskOverlay 'capture.json') -Encoding utf8
$taskEntries | Format-Table -AutoSize
