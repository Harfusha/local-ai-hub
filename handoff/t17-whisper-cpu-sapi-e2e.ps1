$ErrorActionPreference = 'Stop'
$whisperExe = 'C:\Users\Adam\AppData\Roaming\Python\Python313\Scripts\whisper.exe'
$modelDir = 'C:\Users\Adam\.cache\whisper'
$modelPath = Join-Path $modelDir 'base.pt'
if (-not (Test-Path -LiteralPath $whisperExe) -or -not (Test-Path -LiteralPath $modelPath)) {
    throw 'Cached Whisper CLI/base model unavailable; refusing download or install.'
}

$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempDir = Join-Path $tempRoot ('t17-whisper-sapi-' + [guid]::NewGuid().ToString('N'))
$tempDir = [System.IO.Path]::GetFullPath($tempDir)
if (-not $tempDir.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to write outside the temporary directory.'
}
New-Item -ItemType Directory -Path $tempDir | Out-Null

try {
    $audioPath = Join-Path $tempDir 'known-reference.wav'
    $invalidAudioPath = Join-Path $tempDir 'invalid-audio.wav'
    [System.IO.File]::WriteAllBytes($invalidAudioPath, [System.Text.Encoding]::ASCII.GetBytes('not a RIFF audio file'))
    $reference = 'The local model runs on the CPU and returns a short transcript without network access.'
    $voiceHost = New-Object -ComObject SAPI.SpVoice
    $voice = $voiceHost.GetVoices() | Where-Object { $_.GetDescription() -like '*David Desktop*' } | Select-Object -First 1
    if (-not $voice) { throw 'Microsoft David Desktop voice unavailable; no audio sample generated.' }
    $voiceHost.Voice = $voice
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Open($audioPath, 3, $false)
    $voiceHost.AudioOutputStream = $stream
    $null = $voiceHost.Speak($reference)
    $stream.Close()

    $projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    $pythonExe = 'C:\Python313\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Python 3.13 runtime unavailable; refusing install.' }
    $pythonCode = @'
import json, sys
from local_ai_hub.services import LocalAIServices
service = object.__new__(LocalAIServices)
result = service.transcribe({"audio": sys.argv[1], "model": "base", "language": "English"}, "t17-local-quality")
invalid = service.transcribe({"audio": sys.argv[2], "model": "base", "language": "English"}, "t17-invalid-audio")
print(json.dumps({"valid": result, "invalid_audio": invalid}, ensure_ascii=False))
'@
    $oldPythonPath = $env:PYTHONPATH
    $oldCudaDevices = $env:CUDA_VISIBLE_DEVICES
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    if ($oldPythonPath) { $env:PYTHONPATH += ';' + $oldPythonPath }
    $env:CUDA_VISIBLE_DEVICES = '-1'
    $serviceOutput = & $pythonExe -B -c $pythonCode $audioPath $invalidAudioPath 2>&1
    $exitCode = $LASTEXITCODE
    $env:PYTHONPATH = $oldPythonPath
    $env:CUDA_VISIBLE_DEVICES = $oldCudaDevices
    if ($exitCode -ne 0) { throw "LocalAIServices.transcribe failed (exit $exitCode): $($serviceOutput | Select-Object -Last 4 | Out-String)" }
    $serviceResults = ($serviceOutput | Select-Object -Last 1) | ConvertFrom-Json
    if ($serviceResults.valid.success -ne $true) { throw "LocalAIServices.transcribe returned failure: $($serviceResults.valid | ConvertTo-Json -Compress)" }
    if ($serviceResults.invalid_audio.success -ne $false) { throw "Invalid audio unexpectedly succeeded: $($serviceResults.invalid_audio | ConvertTo-Json -Compress)" }
    $hypothesis = $serviceResults.valid.text
    $normalize = { param([string]$Text) (($Text.ToLowerInvariant() -replace '[^\p{L}\p{N}\s]', ' ') -replace '\s+', ' ').Trim() }
    $referenceWords = @((& $normalize $reference) -split ' ')
    $hypothesisWords = @((& $normalize $hypothesis) -split ' ')
    $previous = [int[]]::new($hypothesisWords.Count + 1)
    for ($j = 0; $j -le $hypothesisWords.Count; $j++) { $previous[$j] = $j }
    for ($i = 1; $i -le $referenceWords.Count; $i++) {
        $current = [int[]]::new($hypothesisWords.Count + 1)
        $current[0] = $i
        for ($j = 1; $j -le $hypothesisWords.Count; $j++) {
            $cost = if ($referenceWords[$i - 1] -ceq $hypothesisWords[$j - 1]) { 0 } else { 1 }
            $current[$j] = [Math]::Min([Math]::Min($current[$j - 1] + 1, $previous[$j] + 1), $previous[$j - 1] + $cost)
        }
        $previous = $current
    }
    $distance = $previous[$hypothesisWords.Count]
    [pscustomobject]@{
        status = 'MEASURED_SYNTHETIC_ENGLISH_VIA_LOCAL_AI_SERVICES'
        model = 'base'
        device = 'cpu'
        invalid_audio = $serviceResults.invalid_audio.reason
        invalid_audio_success = $serviceResults.invalid_audio.success
        voice = $voice.GetDescription()
        reference = $reference
        hypothesis = $hypothesis.Trim()
        word_errors = $distance
        reference_words = $referenceWords.Count
        wer = [Math]::Round($distance / $referenceWords.Count, 4)
        sample = 'Windows SAPI synthesized speech; not natural or multilingual corpus'
        network = 'not used; cached base.pt required'
    } | ConvertTo-Json -Compress
}
finally {
    if (Test-Path -LiteralPath $tempDir) {
        $resolvedTemp = [System.IO.Path]::GetFullPath($tempDir)
        if ($resolvedTemp.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
        }
    }
}
