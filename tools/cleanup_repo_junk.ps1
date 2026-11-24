[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [switch]$Apply,
    [ValidateRange(1, 3650)]
    [int]$OldLogDays = 30
)

$ErrorActionPreference = 'Stop'

$rootPath = (Resolve-Path -LiteralPath $RepositoryRoot).Path.TrimEnd('\')
$gitRoot = (& git -C $rootPath rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0) {
    throw "Cesta není Git repozitář: $rootPath"
}
$gitRoot = (Resolve-Path -LiteralPath $gitRoot).Path.TrimEnd('\')
if (-not [string]::Equals($rootPath, $gitRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Cesta musí být kořen repozitáře. Nalezený kořen: $gitRoot"
}

$tracked = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($trackedPath in (& git -C $rootPath ls-files --full-name)) {
    [void]$tracked.Add($trackedPath.Replace('/', '\'))
}
if ($LASTEXITCODE -ne 0) {
    throw 'Nelze načíst seznam sledovaných souborů z Gitu.'
}

$excludedDirectoryNames = @('.git', '.venv', 'venv', 'tool-envs', 'node_modules')
$cacheDirectoryNames = @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.hypothesis')
$filesToRemove = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$directoriesToPrune = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$pending = [System.Collections.Generic.Stack[object]]::new()
$pending.Push([pscustomobject]@{ Path = $rootPath; CleanupMode = $false })
$logCutoff = (Get-Date).AddDays(-$OldLogDays)

function Get-RepoRelativePath([string]$Path) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $rootPrefix = $rootPath.TrimEnd('\') + '\'
    if ([string]::Equals($fullPath, $rootPath, [StringComparison]::OrdinalIgnoreCase)) {
        return '.'
    }
    if (-not $fullPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cesta leží mimo repozitář: $fullPath"
    }
    return $fullPath.Substring($rootPrefix.Length)
}

function Test-TrackedPath([string]$Path) {
    return $tracked.Contains((Get-RepoRelativePath $Path))
}

function Test-ActiveSqliteSnapshot([string]$Directory) {
    $sidecars = Get-ChildItem -LiteralPath $Directory -Force -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '(?i)\.(sqlite3|db)-(wal|shm)$' }
    return ($null -ne $sidecars -and @($sidecars).Count -gt 0)
}

while ($pending.Count -gt 0) {
    $item = $pending.Pop()
    foreach ($child in (Get-ChildItem -LiteralPath $item.Path -Force -ErrorAction SilentlyContinue)) {
        if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }

        if ($child.PSIsContainer) {
            if ($excludedDirectoryNames -contains $child.Name) {
                continue
            }

            $backupDirectory = $child.Name -match '(?i)^backups?$' -or
                $child.Name -match '(?i)^rag-pre-rebuild-\d{8}-\d{4,6}$'
            $cacheDirectory = $cacheDirectoryNames -contains $child.Name

            if ($backupDirectory -and (Test-ActiveSqliteSnapshot $child.FullName)) {
                Write-Warning "Ponecháno: SQLite snapshot má WAL/SHM soubory, může být aktivní: $(Get-RepoRelativePath $child.FullName)"
                continue
            }

            $cleanupMode = $item.CleanupMode -or $backupDirectory -or $cacheDirectory
            if ($cleanupMode) {
                [void]$directoriesToPrune.Add($child.FullName)
            }
            $pending.Push([pscustomobject]@{ Path = $child.FullName; CleanupMode = $cleanupMode })
            continue
        }

        $relativePath = Get-RepoRelativePath $child.FullName
        if (Test-TrackedPath $child.FullName) {
            continue
        }

        if ($child.Name -match '(?i)^external-gpu-reservation\.lease\.json\..+\.tmp$') {
            Write-Warning "Ponecháno: provozní GPU reservation soubor: $relativePath"
            continue
        }

        $junkName = $child.Name -match '(?i)(\.bak|\.backup|\.old|\.orig|\.rej|\.tmp|\.temp|\.swp|\.swo|~)$' -or
            $child.Name -match '(?i)\.previous-[^\\/]+\.[^\\/]+$'
        $generatedFile = $child.Extension -match '(?i)^\.(pyc|pyo)$' -or
            $child.Name -in @('.DS_Store', 'Thumbs.db', '.coverage', 'coverage.xml')
        $oldLog = $child.Extension -ieq '.log' -and $child.LastWriteTime -lt $logCutoff

        if ($item.CleanupMode -or $junkName -or $generatedFile -or $oldLog) {
            [void]$filesToRemove.Add($child.FullName)
        }
    }
}

$orderedFiles = @($filesToRemove | Sort-Object)
if ($orderedFiles.Count -eq 0) {
    Write-Output 'Nenašel jsem žádný bezpečně rozpoznaný balast.'
    return
}

Write-Output "Nalezeno souborů k odstranění: $($orderedFiles.Count)"
foreach ($file in $orderedFiles) {
    Write-Output "  $(Get-RepoRelativePath $file)"
}
if (-not $Apply) {
    Write-Output 'Pouze náhled. Pro smazání spusť: .\tools\cleanup_repo_junk.ps1 -Apply'
    return
}

$confirmation = Read-Host 'Smazání je nevratné a zálohy se nevytvoří. Napiš DELETE'
if ($confirmation -cne 'DELETE') {
    Write-Output 'Zrušeno; nic jsem nesmazal.'
    return
}

$deleted = 0
foreach ($file in $orderedFiles) {
    try {
        Remove-Item -LiteralPath $file -Force -ErrorAction Stop
        $deleted++
    }
    catch {
        Write-Warning "Nepodařilo se smazat $(Get-RepoRelativePath $file): $($_.Exception.Message)"
    }
}

foreach ($directory in ($directoriesToPrune | Sort-Object { $_.Length } -Descending)) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        continue
    }
    $remaining = Get-ChildItem -LiteralPath $directory -Force -ErrorAction SilentlyContinue
    if (@($remaining).Count -eq 0) {
        try {
            Remove-Item -LiteralPath $directory -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Nepodařilo se odstranit prázdnou složku $(Get-RepoRelativePath $directory): $($_.Exception.Message)"
        }
    }
}

Write-Output "Smazáno souborů: $deleted. Zálohy se nevytvářely."
