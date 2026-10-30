param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Outside
)
$base = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'Documents\local-ai-hub-eval')).TrimEnd('\') + '\'
$rootPath = [IO.Path]::GetFullPath($Root)
$outsidePath = [IO.Path]::GetFullPath($Outside)
if (-not $rootPath.StartsWith($base, [StringComparison]::OrdinalIgnoreCase) -or
    -not $outsidePath.StartsWith($base, [StringComparison]::OrdinalIgnoreCase) -or
    $rootPath -eq $outsidePath -or
    $rootPath.StartsWith($outsidePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $outsidePath.StartsWith($rootPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $rootPath) -or (Test-Path -LiteralPath $outsidePath)) {
    throw 'Choose two distinct, new paths under Documents\local-ai-hub-eval.'
}
New-Item -ItemType Directory -Path $rootPath | Out-Null
New-Item -ItemType Directory -Path $outsidePath | Out-Null
Set-Content -LiteralPath (Join-Path $rootPath 'inside.txt') -Value 'In-root fixture marker.' -Encoding utf8NoBOM
Set-Content -LiteralPath (Join-Path $outsidePath 'sentinel.txt') -Value 'EXTERNAL_SENTINEL_CASE_070_8f36c2' -Encoding utf8NoBOM
New-Item -ItemType Junction -Path (Join-Path $rootPath 'external-link') -Target $outsidePath | Out-Null
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $outsidePath 'sentinel.txt')).Hash.ToLowerInvariant()
Write-Output "root=$rootPath"
Write-Output "external=$outsidePath"
Write-Output "sentinel_sha256=$hash"
