# Experimental control client. Session cancellation aborts the entire job.
$ErrorActionPreference = 'Stop'
$name = $env:LOCAL_AI_STOP_PIPE
$encoded = $env:LOCAL_AI_STOP_SECRET
Remove-Item Env:LOCAL_AI_STOP_PIPE -ErrorAction SilentlyContinue
Remove-Item Env:LOCAL_AI_STOP_SECRET -ErrorAction SilentlyContinue
$sent = $false
$pipe = $null
$cancel = $null
$process = $null
try {
    $match = [regex]::Match([string]$name, '^\\\\\.\\pipe\\(lah-opencode-[a-f0-9]{32})$')
    $target = 0
    $cancelSession = $args.Count -eq 2 -and $args[0] -ceq '--cancel-session'
    if ($cancelSession) { $pidText = [string]$args[1] }
    elseif ($args.Count -eq 1) { $pidText = [string]$args[0] }
    else { exit 4 }
    if ($pidText -notmatch '^[1-9][0-9]{0,9}$' -or
        -not [int]::TryParse($pidText, [ref]$target) -or $target -le 0 -or
        -not $match.Success -or $encoded -cnotmatch '^[a-f0-9]{64}$') { exit 4 }
    $key = [byte[]]::new(32)
    for ($i = 0; $i -lt 32; $i++) { $key[$i] = [Convert]::ToByte($encoded.Substring(2 * $i, 2), 16) }
    $encoded = $null
    $process = [Diagnostics.Process]::GetProcessById($target)
    $created = [uint64]$process.StartTime.ToUniversalTime().ToFileTimeUtc()
    $pidBytes = [BitConverter]::GetBytes([uint32]$target)
    $timeBytes = [BitConverter]::GetBytes($created)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($pidBytes); [Array]::Reverse($timeBytes) }
    $request = [byte[]]::new(48)
    $magic = if ($cancelSession) { 'LAC2' } else { 'LAC1' }
    [Array]::Copy([Text.Encoding]::ASCII.GetBytes($magic), 0, $request, 0, 4)
    [Array]::Copy($key, 0, $request, 4, 32)
    [Array]::Copy($pidBytes, 0, $request, 36, 4)
    [Array]::Copy($timeBytes, 0, $request, 40, 8)
    [Array]::Clear($key, 0, $key.Length)
    $pipe = [IO.Pipes.NamedPipeClientStream]::new('.', $match.Groups[1].Value, [IO.Pipes.PipeDirection]::InOut,
                                                  [IO.Pipes.PipeOptions]::Asynchronous)
    $pipe.Connect(2000)
    $cancel = [Threading.CancellationTokenSource]::new(5000)
    $sent = $true
    $pipe.WriteAsync($request, 0, $request.Length, $cancel.Token).GetAwaiter().GetResult()
    [Array]::Clear($request, 0, $request.Length)
    $response = [byte[]]::new(1)
    $count = $pipe.ReadAsync($response, 0, 1, $cancel.Token).GetAwaiter().GetResult()
    if ($count -ne 1 -or $response[0] -gt 3 -or ($response[0] -eq 3 -and -not $cancelSession)) { exit 2 }
    $ack = [byte[]]@(6)
    $pipe.WriteAsync($ack, 0, 1, $cancel.Token).GetAwaiter().GetResult()
    if ($response[0] -eq 1 -and -not $cancelSession) { exit 0 }
    if ($response[0] -eq 0) { exit 5 }
    if ($response[0] -eq 3 -and $cancelSession) { exit 3 } # accepted, not a completion receipt
    exit 2
} catch {
    if ($sent) { exit 2 }
    exit 4
} finally {
    if ($pipe) { $pipe.Dispose() }
    if ($cancel) { $cancel.Dispose() }
    if ($process) { $process.Dispose() }
    if ($key) { [Array]::Clear($key, 0, $key.Length) }
    if ($request) { [Array]::Clear($request, 0, $request.Length) }
}
