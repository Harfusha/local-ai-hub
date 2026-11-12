[CmdletBinding()]
param(
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedRevision,
    [ValidateSet('auto','cpu','integrated','low','balanced','medium','high','max')]
    [string]$Profile,
    [switch]$Interactive,
    [switch]$NonInteractive,
    [switch]$FullReinstall,
    [string]$ConfirmFullReinstall,
    [switch]$SkipModelPull,
    [switch]$SkipTools,
    [switch]$SkipAgentConfig,
    [switch]$SkipService,
    [switch]$SkipOllamaInstall,
    [switch]$SkipLocalNlpPreload,
    [switch]$SkipLayaRuntime,
    [switch]$SkipAstIndex,
    [switch]$SkipPerformance,
    [switch]$SkipProfiling,
    [switch]$SkipTokenEconomy,
    [switch]$SkipCompanionSkills
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required to verify the installer source commit.' }
$ActualRevision = (& git -C $Root rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve installer source commit. Refusing install/update.' }
if ($ExpectedRevision -and $ActualRevision -ine $ExpectedRevision) {
    throw "Source checkout does not match expected verified commit $ExpectedRevision. Refusing install/update."
}
$ExpectedRevision = $ActualRevision
$SourceStatus = & git -C $Root status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect source checkout status. Refusing install/update.' }
if ($SourceStatus) { throw 'Source checkout is dirty. Preserve changes, use the verified clean commit, then rerun install/update.' }
Write-Host "[local-ai-hub] Verified clean source commit: $ActualRevision"

function Test-Python311([string]$Exe, [string[]]$Prefix = @()) {
    try {
        $code = & $Exe @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

$Python = $null
$PythonPrefix = @()
foreach ($candidate in @(
    @{Exe='py'; Prefix=@('-3.14')},
    @{Exe='py'; Prefix=@('-3.13')},
    @{Exe='py'; Prefix=@('-3.12')},
    @{Exe='py'; Prefix=@('-3.11')},
    @{Exe='python'; Prefix=@()},
    @{Exe='python3'; Prefix=@()}
)) {
    if (Get-Command $candidate.Exe -ErrorAction SilentlyContinue) {
        if (Test-Python311 $candidate.Exe $candidate.Prefix) {
            $Python = $candidate.Exe; $PythonPrefix = $candidate.Prefix; break
        }
    }
}

if (-not $Python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.11+ was not found and winget is unavailable. Install Python 3.11+ and rerun install.ps1; see $(Join-Path $Root 'docs/INSTALLER_RECOVERY.md')."
    }
    Write-Host '[local-ai-hub] Installing Python 3.14 with winget...'
    & winget install --id Python.Python.3.14 -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Python installation failed. See $(Join-Path $Root 'docs/INSTALLER_RECOVERY.md')."
    }
    # winget can install Python before the current PowerShell process sees the new
    # launcher/PATH. Probe both the launcher and the standard per-user install path.
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Python311 'py' @('-3.14'))) {
        $Python = 'py'; $PythonPrefix = @('-3.14')
    } else {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
        if ((Test-Path $candidate) -and (Test-Python311 $candidate @())) {
            $Python = $candidate; $PythonPrefix = @()
        } else {
            throw "Python 3.14 was installed but is not visible to this process. Open a new terminal and rerun install.ps1; see $(Join-Path $Root 'docs/INSTALLER_RECOVERY.md')."
        }
    }
}

# setup.py creates isolated tool/runtime environments; fail here with a useful
# message rather than much later if this Python build omitted the venv module.
& $Python @PythonPrefix -m venv --help *> $null
if ($LASTEXITCODE -ne 0) { throw "The selected Python build does not provide the stdlib venv module; see $(Join-Path $Root 'docs/INSTALLER_RECOVERY.md')." }

$argsList = @($PythonPrefix) + @((Join-Path $Root 'tools\setup.py'), '--expected-revision', $ExpectedRevision)
if ($Profile) { $argsList += @('--profile', $Profile) }
if ($Interactive) { $argsList += '--interactive' }
if ($NonInteractive) { $argsList += '--non-interactive' }
if ($FullReinstall) { $argsList += '--full-reinstall' }
if ($ConfirmFullReinstall) { $argsList += @('--confirm-full-reinstall', $ConfirmFullReinstall) }
if ($SkipModelPull) { $argsList += '--skip-model-pull' }
if ($SkipTools) { $argsList += '--skip-tools' }
if ($SkipAgentConfig) { $argsList += '--skip-agent-config' }
if ($SkipService) { $argsList += '--skip-service' }
if ($SkipOllamaInstall) { $argsList += '--skip-ollama-install' }
if ($SkipLocalNlpPreload) { $argsList += '--skip-local-nlp-preload' }
if ($SkipLayaRuntime) { $argsList += '--skip-laya-runtime' }
if ($SkipAstIndex) { $argsList += '--skip-ast-index' }
if ($SkipPerformance) { $argsList += '--skip-performance' }
if ($SkipProfiling) { $argsList += '--skip-profiling' }
if ($SkipTokenEconomy) { $argsList += '--skip-token-economy' }
if ($SkipCompanionSkills) { $argsList += '--skip-companion-skills' }
& $Python @argsList
exit $LASTEXITCODE
