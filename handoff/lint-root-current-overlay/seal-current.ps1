$ErrorActionPreference = 'Stop'
$taskOverlay = 'C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\lint-root-current-overlay'
$taskPublish = Join-Path $taskOverlay 'publish-20261001T160429863497Z'
$taskReceipt = Get-Content -LiteralPath (Join-Path $taskPublish 'receipt.json') -Raw | ConvertFrom-Json
foreach ($taskFile in $taskReceipt.files) {
    $taskRootHash = (Get-FileHash -LiteralPath (Join-Path $taskReceipt.root $taskFile.path) -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskOwnedHash = (Get-FileHash -LiteralPath (Join-Path (Join-Path $taskOverlay 'owned') $taskFile.path) -Algorithm SHA256).Hash.ToLowerInvariant()
    if (($taskRootHash -ne $taskFile.pre_sha256) -or ($taskOwnedHash -ne $taskFile.post_sha256)) {
        throw "Source drift before sealing: $($taskFile.path)"
    }
}
foreach ($taskName in @('capture.json', 'capture-current.ps1', 'verify-publish.py', 'first-overlay-pyflakes.txt')) {
    $taskDestination = Join-Path $taskPublish $taskName
    if (Test-Path -LiteralPath $taskDestination) { throw "Refusing overwrite: $taskDestination" }
    Copy-Item -LiteralPath (Join-Path $taskOverlay $taskName) -Destination $taskDestination
}
$taskIndexPath = Join-Path $taskPublish 'bundle-index.json'
if (Test-Path -LiteralPath $taskIndexPath) { throw 'Refusing to reseal immutable publication' }
$taskArtifacts = @(Get-ChildItem -LiteralPath $taskPublish -File | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{ name = $_.Name; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
})
[ordered]@{
    status = 'SEALED_SOURCE_STATIC_PASS'
    root_preimages_match = $true
    overlay_postimages_match = $true
    sealed_utc = [DateTime]::UtcNow.ToString('o')
    command = "& '$taskOverlay\seal-current.ps1'"
    main_review_required_before_T20_integration = $true
    files = $taskArtifacts
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $taskIndexPath -Encoding utf8
Get-ChildItem -LiteralPath $taskPublish -File | ForEach-Object { $_.IsReadOnly = $true }
[pscustomobject]@{
    status = 'SEALED_SOURCE_STATIC_PASS'
    publication = $taskPublish
    artifacts = $taskArtifacts.Count + 1
    root_preimages_match = $true
    overlay_postimages_match = $true
    patch_sha256 = (Get-FileHash -LiteralPath (Join-Path $taskPublish 'misc-pyflakes-current-root.patch') -Algorithm SHA256).Hash.ToLowerInvariant()
    receipt_sha256 = (Get-FileHash -LiteralPath (Join-Path $taskPublish 'receipt.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    bundle_index_sha256 = (Get-FileHash -LiteralPath $taskIndexPath -Algorithm SHA256).Hash.ToLowerInvariant()
    read_only_artifacts = @(Get-ChildItem -LiteralPath $taskPublish -File | Where-Object IsReadOnly).Count
} | ConvertTo-Json
