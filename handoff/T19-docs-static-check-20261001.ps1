$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$InstallPrompt = Get-Content docs/INSTALL_PROMPT.md
$UpdatePrompt = Get-Content docs/UPDATE_PROMPT.md
$InstallRoute = @($InstallPrompt | Where-Object { $_.StartsWith('Local model routing starts') })
$UpdateRoute = @($UpdatePrompt | Where-Object { $_.StartsWith('Local model routing starts') })
if ($InstallRoute.Count -ne 1 -or $UpdateRoute.Count -ne 1 -or $InstallRoute[0] -cne $UpdateRoute[0]) {
    throw 'Install/update profile paragraphs differ or are duplicated.'
}

$Tick = [string][char]96
$ModelDoc = Get-Content docs/MODEL_CAPABILITIES.md -Raw
$ModelRows = @(
    '| `integrated` | `qwen2.5-coder:0.5b` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen2.5-coder:1.5b` | `qwen3-vl:4b` |',
    '| `balanced` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen2.5-coder:7b` | `qwen3.5:9b` |',
    '| `high` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` |',
    '| `max` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` |'
)
foreach ($Row in $ModelRows) {
    if (-not $ModelDoc.Contains($Row)) { throw "Model capability route missing: $Row" }
}

$Installation = Get-Content docs/INSTALLATION.md -Raw
foreach ($Text in @(
    '## Optional standalone tool: CodeGraphContext',
    'not Hub dependencies or backends',
    'pip install "codegraphcontext[gcf]==0.6.13"',
    'it does not configure Local AI Hub'
)) {
    if (-not $Installation.Contains($Text)) { throw "CodeGraphContext optional-tool contract missing: $Text" }
}

$Runbook = (Get-Content docs/T19_RELEASE_VALIDATION_RUNBOOK.md -Raw).Replace($Tick, '')
$PythonRows = @(
    '| 3.11 | py -3.11 | python3.11 | py311 |',
    '| 3.12 | py -3.12 | python3.12 | py312 |',
    '| 3.13 | py -3.13 | python3.13 | py313 |',
    '| 3.14 | py -3.14 | python3.14 | py314 |',
    'Frozen-source command pack — prepared, not run'
)
foreach ($Row in $PythonRows) {
    if (-not $Runbook.Contains($Row)) { throw "Runbook contract missing: $Row" }
}
Write-Output 'PASS prompt parity, four profile rows, standalone CodeGraphContext contract, four Python/tag rows'

$TrailingWhitespace = @()
foreach ($Path in @(
    'docs/INSTALLATION.md', 'docs/INSTALL_PROMPT.md', 'docs/UPDATE_PROMPT.md',
    'docs/T19_RELEASE_VALIDATION_RUNBOOK.md'
)) {
    $Lines = Get-Content -LiteralPath $Path
    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match '[ \t]+$') { $TrailingWhitespace += ('{0}:{1}' -f $Path, ($Index + 1)) }
    }
}
if ($TrailingWhitespace.Count) { throw "Trailing whitespace: $($TrailingWhitespace -join ', ')" }
Write-Output 'PASS trailing whitespace scan on four T19 documentation files'

git diff --check -- docs/INSTALLATION.md docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed.' }
Write-Output 'PASS git diff --check on tracked install and prompt docs'

Get-FileHash -Algorithm SHA256 @(
    'docs/INSTALLATION.md', 'docs/INSTALL_PROMPT.md', 'docs/UPDATE_PROMPT.md',
    'docs/T19_RELEASE_VALIDATION_RUNBOOK.md'
) | Select-Object Path, Hash
