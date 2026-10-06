param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = 'C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub'
if ((Get-Location).Path -ne $taskRoot) { throw 'Run only inside assigned T03 checkout' }
$archivePath = Join-Path $taskRoot 'handoff/T03-preservation-20261006.zip'
$manifestPath = Join-Path $taskRoot 'handoff/T03-preservation-20261006.json'
$excludedPath = Join-Path $taskRoot 'handoff/T03-preservation-excluded-20261006.json'
Add-Type -AssemblyName System.IO.Compression

function Relative-Path([string]$absolute) {
    if (-not $absolute.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside assigned checkout' }
    return $absolute.Substring($taskRoot.Length + 1).Replace('\', '/')
}
function Exclusion-Reason([string]$path) {
    if ($path.StartsWith('.t03-sync-checks/') -and $path -notin @('.t03-sync-checks/check.py', '.t03-sync-checks/pytest.log')) { return 'Generated validation temporary/runtime state or local configuration' }
    if ($path -match '(^|/)(__pycache__|\.pytest_cache|\.serena)(/|$)' -or $path -match '\.py[co]$') { return 'Runtime/index/test cache' }
    if ($path -match '(^|/)state(/|$)|\.(sqlite3|db)(-|$)|\.(lock|pid|unavailable)$') { return 'Runtime DB/process state' }
    if ($path -match '(^|/)config(\.runtime)?\.toml$') { return 'Generated/user-local configuration excluded by AGENTS and gitignore' }
    return ''
}
function Verify-Archive {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        foreach ($row in $manifest.included) {
            $entry = $zip.GetEntry($row.path)
            if ($null -eq $entry) { throw "Missing archive entry: $($row.path)" }
            $stream = $entry.Open()
            try { $sha = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)) } finally { $stream.Dispose() }
            if ($sha -ne $row.sha256 -or $entry.Length -ne $row.bytes) { throw "Archive mismatch: $($row.path)" }
            if ((Get-FileHash -LiteralPath (Join-Path $taskRoot $row.path) -Algorithm SHA256).Hash -ne $row.sha256) { throw "Original changed: $($row.path)" }
        }
    } finally { $zip.Dispose() }
    Write-Output "Exact-byte archive/original verification: PASS ($($manifest.included.Count) files)"
}
if ($VerifyOnly) { Verify-Archive; exit }
if ((Test-Path -LiteralPath $archivePath) -or (Test-Path -LiteralPath $manifestPath)) { throw 'Preservation outputs already exist; use -VerifyOnly' }
$paths = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($path in @(git ls-files --others --exclude-standard)) { if (-not $path.EndsWith('/')) { [void]$paths.Add($path) } }
foreach ($dir in @('.t03-main-preflight-overlay', '.t03-root-current-overlay')) {
    foreach ($item in Get-ChildItem -LiteralPath $dir -Recurse -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point requires explicit handling: $($item.FullName)" }
        if (-not $item.PSIsContainer) { [void]$paths.Add((Relative-Path $item.FullName)) }
    }
}
foreach ($path in @(git ls-files --others --ignored --exclude-standard)) { [void]$paths.Add($path) }
foreach ($item in Get-ChildItem -LiteralPath 'handoff' -File) {
    if ($item.Name -match '^(T03|t03)[-\.]' -and $item.Name -notmatch '^T03-preservation-') { [void]$paths.Add((Relative-Path $item.FullName)) }
}
$included = @(); $excluded = @()
foreach ($path in $paths | Sort-Object) {
    if ($path -eq 'handoff/Preserve-T03-OriginalArtifacts.ps1') { continue }
    $absolute = [IO.Path]::GetFullPath((Join-Path $taskRoot $path))
    [void](Relative-Path $absolute)
    $item = Get-Item -LiteralPath $absolute
    if ($item.PSIsContainer) { throw "Unexpanded directory: $path" }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $path" }
    $reason = Exclusion-Reason $path
    $row = [ordered]@{path=$path; bytes=$item.Length; sha256=(Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash}
    if ($reason) { $row.reason=$reason; $excluded += $row }
    else { $row.storage = if ($path -match '/\.git/') { 'archive-only nested Git snapshot metadata' } else { 'ordinary Git path plus exact-byte archive' }; $included += $row }
}
$zip = [IO.Compression.ZipFile]::Open($archivePath, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($row in $included) {
        $entry = $zip.CreateEntry($row.path, [IO.Compression.CompressionLevel]::Optimal)
        $input = [IO.File]::OpenRead((Join-Path $taskRoot $row.path)); $output = $entry.Open()
        try { $input.CopyTo($output) } finally { $input.Dispose(); $output.Dispose() }
    }
} finally { $zip.Dispose() }
$manifest = [ordered]@{
    schema_version=1; root=$taskRoot; pinned_master='f8ba97fe9eafa38810dbbbc3c4184800da7bafcd';
    byte_capture_boundary='Original remaining artifacts as observed at preservation clarification; pre-merge source history remains in earlier checkpoint commits';
    archive='handoff/T03-preservation-20261006.zip'; archive_sha256=(Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash;
    included=$included
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8
@{schema_version=1; root=$taskRoot; preserved_on_disk=$true; excluded=$excluded} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $excludedPath -Encoding utf8
Verify-Archive
foreach ($row in $included) {
    if ($row.storage -like 'archive-only*') { continue }
    # Populate explicit ordinary paths without staging nested repositories as gitlinks.
    # Git filters may normalize text; the binary archive preserves original bytes.
    $blob = git hash-object -w "--path=$($row.path)" -- (Join-Path $taskRoot $row.path)
    if ($LASTEXITCODE -ne 0) { throw "Cannot hash $($row.path)" }
    git update-index --add --cacheinfo "100644,$blob,$($row.path)"
    if ($LASTEXITCODE -ne 0) { throw "Cannot index $($row.path)" }
}
git add -- handoff/Preserve-T03-OriginalArtifacts.ps1 handoff/T03-preservation-20261006.zip handoff/T03-preservation-20261006.json handoff/T03-preservation-excluded-20261006.json
if ($LASTEXITCODE -ne 0) { throw 'Cannot index preservation receipts' }
Write-Output "Included: $($included.Count); excluded, preserved on disk: $($excluded.Count)"
