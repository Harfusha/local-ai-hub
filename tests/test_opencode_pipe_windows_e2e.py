"""Real Windows AppContainer pipe transaction tests; never call a model."""

from __future__ import annotations

import ctypes
import base64
import json
import os
import shutil
import sys
import subprocess
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import local_ai_hub.opencode_pipe_broker as broker


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows AppContainer APIs required")


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEX(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


def _launch_appcontainer_process(
    application: str, arguments: list[str], appcontainer_sid: ctypes.c_void_p,
    expected_sid: str, expected_session_id: int, expected_logon_sid: str,
    *, environment: dict[str, str] | None = None,
) -> int:
    """Run a short command under the supplied disposable package SID."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    attribute_list = None
    process_info = _PROCESS_INFORMATION()
    sid_string = wintypes.LPWSTR()
    try:
        advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        if not advapi32.ConvertSidToStringSidW(appcontainer_sid, ctypes.byref(sid_string)):
            raise ctypes.WinError(ctypes.get_last_error())

        required = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(required))
        if ctypes.get_last_error() != 122:
            raise ctypes.WinError(ctypes.get_last_error())
        attribute_list = ctypes.create_string_buffer(required.value)
        if not kernel32.InitializeProcThreadAttributeList(attribute_list, 1, 0, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())

        capabilities = _SECURITY_CAPABILITIES(appcontainer_sid, None, 0, 0)
        kernel32.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        if not kernel32.UpdateProcThreadAttribute(
            attribute_list, 0, 0x00020009, ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        startup = _STARTUPINFOEX()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.lpDesktop = r"WinSta0\Default"
        startup.lpAttributeList = ctypes.cast(attribute_list, ctypes.c_void_p)
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline([application, *arguments]))
        environment_buffer = None
        environment_pointer = None
        creation_flags = 0x00080000  # EXTENDED_STARTUPINFO_PRESENT
        if environment is not None:
            if any(not key or "=" in key or "\x00" in key or "\x00" in value
                   for key, value in environment.items()):
                raise ValueError("invalid explicit process environment")
            environment_text = "\0".join(
                f"{key}={value}" for key, value in sorted(environment.items(), key=lambda item: item[0].casefold())
            ) + "\0\0"
            environment_buffer = ctypes.create_unicode_buffer(environment_text)
            environment_pointer = ctypes.cast(environment_buffer, ctypes.c_void_p)
            creation_flags |= 0x00000400  # CREATE_UNICODE_ENVIRONMENT
        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.c_void_p, ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL
        if not kernel32.CreateProcessW(
            application, command_line, None, None, False, creation_flags,
            environment_pointer, os.path.dirname(application), ctypes.byref(startup), ctypes.byref(process_info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        import win32api
        import win32security
        process_token = win32security.OpenProcessToken(
            process_info.hProcess, win32security.TOKEN_QUERY
        )
        try:
            actual_sid = broker._token_appcontainer_sid(int(process_token))
            if actual_sid != expected_sid:
                raise AssertionError(f"AppContainer process token SID mismatch: {actual_sid!r}")
            actual_session = win32security.GetTokenInformation(
                process_token, win32security.TokenSessionId
            )
            if actual_session != expected_session_id:
                raise AssertionError(f"AppContainer token session mismatch: {actual_session!r}")
            groups = win32security.GetTokenInformation(
                process_token, win32security.TokenGroups
            )
            logon_sids = [
                win32security.ConvertSidToStringSid(sid)
                for sid, attributes in groups
                if attributes & 0xC0000000 == 0xC0000000
            ]
            if logon_sids != [expected_logon_sid]:
                raise AssertionError(f"AppContainer token logon SID mismatch: {logon_sids!r}")
        finally:
            win32api.CloseHandle(process_token)
        if kernel32.WaitForSingleObject(process_info.hProcess, 20000) != 0:
            kernel32.TerminateProcess(process_info.hProcess, 124)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
            return 124
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return exit_code.value
    finally:
        if process_info.hThread:
            kernel32.CloseHandle(process_info.hThread)
        if process_info.hProcess:
            kernel32.CloseHandle(process_info.hProcess)
        if attribute_list:
            kernel32.DeleteProcThreadAttributeList(attribute_list)
        if sid_string:
            kernel32.LocalFree(ctypes.cast(sid_string, wintypes.HLOCAL))


def _client_js(
    pipe_basename: str, secret: bytes, *, request_target: str, ack: int, host_port: int,
) -> str:
    if isinstance(host_port, bool) or not isinstance(host_port, int) or not 1 <= host_port <= 65535:
        raise ValueError("host_port must be a valid TCP port")
    path = json.dumps(r"\\.\pipe" + "\\" + pipe_basename)
    key = json.dumps(secret.hex())
    host_endpoint = json.dumps({"host": "127.0.0.1", "port": host_port})
    request = json.dumps(
        f"POST {request_target} HTTP/1.1\r\nHost: attacker.invalid\r\n"
        "Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
    )
    return f"""
const net = require('node:net');
const timer = setTimeout(() => process.exit(250), 12000);
function blocked(endpoint) {{
  return new Promise((resolve, reject) => {{
    const client = net.connect(endpoint);
    const timeout = setTimeout(() => {{ client.destroy(); resolve(); }}, 1200);
    client.once('connect', () => {{ clearTimeout(timeout); client.destroy(); reject(new Error('host network reachable')); }});
    client.once('error', () => {{ clearTimeout(timeout); resolve(); }});
  }});
}}
async function checkNetworkBoundary() {{
  const server = net.createServer(client => client.end('container-loopback-ok'));
  await new Promise((resolve, reject) => {{ server.once('error', reject); server.listen(0, '127.0.0.1', resolve); }});
  try {{
    await new Promise((resolve, reject) => {{
      const client = net.connect(server.address().port, '127.0.0.1');
      const timeout = setTimeout(() => {{ client.destroy(); reject(new Error('container loopback timed out')); }}, 1500);
      client.once('data', data => {{ clearTimeout(timeout); data.toString() === 'container-loopback-ok' ? resolve() : reject(new Error('bad loopback response')); }});
      client.once('error', error => {{ clearTimeout(timeout); reject(error); }});
    }});
  }} finally {{ await new Promise(resolve => server.close(resolve)); }}
  await blocked({host_endpoint});
  await blocked({{ host: '1.1.1.1', port: 443 }});
}}
checkNetworkBoundary().then(() => {{
const socket = net.connect({path});
let pending = Buffer.alloc(0), chunks = [], ackSent = false;
socket.on('connect', () => {{ socket.write(Buffer.concat([Buffer.from({key}, 'hex'), Buffer.from({request}, 'ascii')])); }});
socket.on('data', data => {{
  pending = Buffer.concat([pending, data]);
  while (pending.length >= 4) {{
    const length = pending.readUInt32BE(0);
    if (length > 65536) process.exit(240);
    if (pending.length < 4 + length) return;
    const chunk = pending.subarray(4, 4 + length);
    pending = pending.subarray(4 + length);
    if (length === 0) {{
      if (pending.length) process.exit(239);
      const response = Buffer.concat(chunks).toString('ascii');
      if (!response.startsWith('HTTP/1.1 200 OK\\r\\n') || !response.endsWith('{{"answer":"ok"}}')) process.exit(238);
      ackSent = true;
      socket.write(Buffer.from([{ack}]), () => {{ clearTimeout(timer); socket.end(); process.exit(0); }});
      return;
    }}
    chunks.push(chunk);
  }}
}});
socket.on('error', error => {{ if (ackSent) return; clearTimeout(timer); process.exit(100 + ((Math.abs(error.errno || 1)) % 100)); }});
}}).catch(() => process.exit(231));
"""


def _powershell_pipe_open(
    pipe_basename: str, payload: bytes = b"", *, local_namespace: bool = True
) -> list[str]:
    """Use the inbox .NET pipe client to isolate AppContainer namespace visibility."""
    pipe_name = ("LOCAL\\" if local_namespace else "") + pipe_basename
    script = (
        "$ErrorActionPreference='Stop';"
        "try {$p=[System.IO.Pipes.NamedPipeClientStream]::new('.',"
        f"'{pipe_name}',[System.IO.Pipes.PipeDirection]::InOut);"
        "$p.Connect(5000);$p.Dispose();exit 0}"
        "catch {exit ($_.Exception.HResult -band 255)}"
    )
    if payload:
        script = (
            "$ErrorActionPreference='Stop';"
            "$p=[System.IO.Pipes.NamedPipeClientStream]::new('.',"
            f"'{pipe_name}',[System.IO.Pipes.PipeDirection]::InOut);"
            f"$p.Connect(5000);$b=[Convert]::FromBase64String('{base64.b64encode(payload).decode('ascii')}');"
            "$p.Write($b,0,$b.Length);$p.Flush();$p.Dispose();exit 0"
        )
    return ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode("ascii")]


def _powershell_pipe_server(pipe_name: str, appcontainer_sid: str) -> list[str]:
    """Create a .NET host control pipe with owner plus exact package SID ACL."""
    script = f"""
$ErrorActionPreference='Stop'
$sec=[System.IO.Pipes.PipeSecurity]::new()
$sec.SetAccessRuleProtection($true,$false)
$owner=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$sec.AddAccessRule([System.IO.Pipes.PipeAccessRule]::new($owner,[System.IO.Pipes.PipeAccessRights]::FullControl,[System.Security.AccessControl.AccessControlType]::Allow))
$package=[System.Security.Principal.SecurityIdentifier]::new('{appcontainer_sid}')
$rights=[System.Enum]::ToObject([System.IO.Pipes.PipeAccessRights],0x12019B)
$sec.AddAccessRule([System.IO.Pipes.PipeAccessRule]::new($package,$rights,[System.Security.AccessControl.AccessControlType]::Allow))
$server=[System.IO.Pipes.NamedPipeServerStream]::new('{pipe_name}',[System.IO.Pipes.PipeDirection]::InOut,1,[System.IO.Pipes.PipeTransmissionMode]::Byte,[System.IO.Pipes.PipeOptions]::Asynchronous,65536,65536,$sec)
Write-Output 'READY'
$server.WaitForConnection()
$buffer=New-Object byte[] 32
$offset=0
while($offset -lt 32){{$n=$server.Read($buffer,$offset,32-$offset);if($n -le 0){{throw 'client disconnected'}};$offset+=$n}}
Write-Output "RECEIVED=$offset"
$server.Dispose()
"""
    return ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode("ascii")]


def _powershell_createfile_probe(pipe_name: str) -> list[str]:
    """Return the exact Win32 CreateFile error instead of .NET's retry timeout."""
    path = "'" + pipe_name.replace("'", "''") + "'"
    script = f"""
$ErrorActionPreference='Stop'
$source=@'
using System;
using System.Runtime.InteropServices;
public static class OpenCodePipeProbe {{
  [DllImport("kernel32.dll", EntryPoint="CreateFileW", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern IntPtr CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool CloseHandle(IntPtr handle);
}}
'@
try {{
  Add-Type -TypeDefinition $source -ErrorAction Stop
  $access=[Convert]::ToUInt32('3221225472')
  $handle=[OpenCodePipeProbe]::CreateFile({path},$access,0,[IntPtr]::Zero,3,0,[IntPtr]::Zero)
  if($handle.ToInt64() -eq -1){{exit [Runtime.InteropServices.Marshal]::GetLastWin32Error()}}
  [OpenCodePipeProbe]::CloseHandle($handle)|Out-Null
  exit 0
}} catch {{
  try {{ [System.IO.File]::WriteAllText((Join-Path $env:TEMP 'opencode-createfile-error.txt'),$_.Exception.ToString()) }} catch {{}}
  exit 240
}}
"""
    return ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode("ascii")]


def _powershell_createfile_from_app_probe(pipe_name: str, payload: bytes) -> list[str]:
    """Open a host pipe through the AppContainer-aware Win32 entry point."""
    path = "'" + pipe_name.replace("'", "''") + "'"
    encoded_payload = base64.b64encode(payload).decode("ascii")
    script = f"""
$ErrorActionPreference='Stop'
$source=@'
using System;
using System.Runtime.InteropServices;
public static class OpenCodePipeFromAppProbe {{
  [DllImport("kernelbase.dll", EntryPoint="CreateFileFromAppW", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern IntPtr CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool WriteFile(IntPtr handle, byte[] buffer, uint length, out uint written, IntPtr overlapped);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool CloseHandle(IntPtr handle);
}}
'@
try {{
  Add-Type -TypeDefinition $source -ErrorAction Stop
  $access=[Convert]::ToUInt32('3221225472')
  $handle=[OpenCodePipeFromAppProbe]::CreateFile({path},$access,0,[IntPtr]::Zero,3,0,[IntPtr]::Zero)
  if($handle.ToInt64() -eq -1){{exit [Runtime.InteropServices.Marshal]::GetLastWin32Error()}}
  $bytes=[Convert]::FromBase64String('{encoded_payload}')
  [uint32]$written=0
  if(-not [OpenCodePipeFromAppProbe]::WriteFile($handle,$bytes,$bytes.Length,[ref]$written,[IntPtr]::Zero)){{exit [Runtime.InteropServices.Marshal]::GetLastWin32Error()}}
  [OpenCodePipeFromAppProbe]::CloseHandle($handle)|Out-Null
  if($written -ne $bytes.Length){{exit 234}}
  exit 0
}} catch {{
  try {{ [System.IO.File]::WriteAllText((Join-Path $env:TEMP 'opencode-fromapp-error.txt'),$_.Exception.ToString()) }} catch {{}}
  exit 240
}}
"""
    return ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode("ascii")]


@pytest.mark.parametrize(
    "client_kind",
    [
        "node", "powershell-container", "powershell-host", "powershell-createfile",
        "dotnet-server-local-local", "dotnet-server-plain-local",
        "dotnet-server-local-plain", "dotnet-server-plain-plain", "fromapp-plain-pipe",
    ],
    ids=[
        "node-roundtrip", "inbox-container-diagnostic", "inbox-host-control", "win32-createfile-diagnostic",
        "dotnet-server-local-local", "dotnet-server-plain-local",
        "dotnet-server-local-plain", "dotnet-server-plain-plain", "fromapp-plain-pipe",
    ],
)
def test_named_pipe_transport_behavior_under_host_and_appcontainer(client_kind: str):
    observed: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed["path"] = self.path
            observed["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            response = json.dumps({"answer": "ok"}, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args):
            pass

    hub = HTTPServer(("127.0.0.1", 0), Handler)
    hub_thread = threading.Thread(target=hub.serve_forever, daemon=True)
    hub_thread.start()
    session_id = uuid.uuid4().hex
    secret = os.urandom(32)
    outcome: dict[str, object] = {}
    dotnet_cases = {
        "dotnet-server-local-local": (True, True),
        "dotnet-server-plain-local": (False, True),
        "dotnet-server-local-plain": (True, False),
        "dotnet-server-plain-plain": (False, False),
        "fromapp-plain-pipe": (False, False),
    }

    # First create a temporary AppContainer to learn the package SID used by the pipe ACL.
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    profile = "LocalAIHub-OpenCode-Test-" + uuid.uuid4().hex
    app_sid = ctypes.c_void_p()
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    hr = userenv.CreateAppContainerProfile(profile, profile, "temporary OpenCode pipe test", None, 0, ctypes.byref(app_sid))
    assert hr >= 0, f"CreateAppContainerProfile HRESULT 0x{hr & 0xFFFFFFFF:08x}"
    sid_text = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    assert advapi32.ConvertSidToStringSidW(app_sid, ctypes.byref(sid_text))
    import win32api
    import win32security
    current_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
    )
    windows_session_id = win32security.GetTokenInformation(current_token, win32security.TokenSessionId)
    current_groups = win32security.GetTokenInformation(current_token, win32security.TokenGroups)
    logon_sids = [
        win32security.ConvertSidToStringSid(sid)
        for sid, attributes in current_groups
        if attributes & 0xC0000000 == 0xC0000000
    ]
    win32api.CloseHandle(current_token)
    assert len(logon_sids) == 1, f"expected one host logon SID, got {logon_sids!r}"
    listener = broker.WindowsOpenCodePipeListener(
        session_id=session_id,
        appcontainer_sid=sid_text.value,
        windows_session_id=windows_session_id,
        secret=secret,
        hub_port=hub.server_port,
        io_timeout=15,
    )
    if client_kind == "powershell-createfile":
        listener.pipe_name = rf"\\.\pipe\LOCAL\lah-opencode-{session_id}"

    pipe_thread = None
    dotnet_server = None
    if client_kind not in dotnet_cases:
        def serve():
            try:
                listener.serve_once()
                outcome["returned"] = True
            except Exception as exc:
                outcome["error"] = exc

        pipe_thread = threading.Thread(target=serve, daemon=True)
        pipe_thread.start()
    else:
        powershell = shutil.which("powershell")
        assert powershell
        server_local, _client_local = dotnet_cases[client_kind]
        server_name = ("LOCAL\\" if server_local else "") + f"lah-opencode-{session_id}"
        dotnet_server = subprocess.Popen(
            [powershell, *_powershell_pipe_server(server_name, sid_text.value)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    client_script = _client_js(
        f"lah-opencode-{session_id}", secret,
        request_target="/api/chat/completions", ack=6, host_port=hub.server_port,
    )
    try:
        if client_kind in dotnet_cases:
            assert dotnet_server is not None and dotnet_server.stdout is not None
            ready: dict[str, str] = {}
            ready_thread = threading.Thread(
                target=lambda: ready.setdefault("line", dotnet_server.stdout.readline()), daemon=True
            )
            ready_thread.start()
            ready_thread.join(timeout=10)
            assert ready == {"line": "READY\n"}, f".NET pipe server failed to start: {ready}"
        else:
            assert listener.pipe_ready.wait(timeout=5), f"pipe listener did not become ready: {outcome}"
        if client_kind == "node":
            application = shutil.which("node")
            assert application
            arguments = ["-e", client_script]
        elif client_kind == "powershell-createfile":
            application = shutil.which("powershell")
            assert application
            arguments = _powershell_createfile_probe(listener.pipe_name)
        elif client_kind in {"powershell-container", "powershell-host", *dotnet_cases}:
            application = shutil.which("powershell")
            assert application
            payload = bytes(32) if client_kind in {"powershell-host", "powershell-container", *dotnet_cases} else b""
            local_namespace = dotnet_cases.get(client_kind, (False, False))[1]
            arguments = _powershell_pipe_open(
                f"lah-opencode-{session_id}", payload, local_namespace=local_namespace
            )
        if client_kind == "fromapp-plain-pipe":
            application = shutil.which("powershell")
            assert application
            arguments = _powershell_createfile_from_app_probe(
                rf"\\.\pipe\lah-opencode-{session_id}", bytes(32)
            )
        if client_kind == "powershell-host":
            result = subprocess.run([application, *arguments], timeout=10, check=False)
            exit_code = result.returncode
        elif client_kind in dotnet_cases:
            exit_code = _launch_appcontainer_process(
                application, arguments, app_sid, sid_text.value,
                windows_session_id, logon_sids[0],
            )
            assert dotnet_server is not None
            if exit_code != 0:
                dotnet_server.terminate()
            server_stdout, server_stderr = dotnet_server.communicate(timeout=10)
        else:
            exit_code = _launch_appcontainer_process(
                application, arguments, app_sid, sid_text.value,
                windows_session_id, logon_sids[0],
            )
        if pipe_thread is not None:
            pipe_thread.join(timeout=20)
            assert not pipe_thread.is_alive(), "host pipe listener did not finish"
        if client_kind in dotnet_cases:
            if client_kind == "fromapp-plain-pipe":
                assert exit_code == 0, f"CreateFileFromAppW exit {exit_code}; server={server_stdout!r} {server_stderr!r}"
                assert dotnet_server is not None and dotnet_server.returncode == 0
                assert "RECEIVED=32" in server_stdout
                return
            if exit_code != 0:
                assert dotnet_server is not None and dotnet_server.returncode != 0
                assert "RECEIVED=32" not in server_stdout
                assert not observed
                return
            assert dotnet_server is not None and dotnet_server.returncode == 0
            assert "RECEIVED=32" in server_stdout
            return
        if client_kind == "powershell-host":
            assert exit_code == 0, f"full-trust .NET pipe client exit {exit_code}; listener={outcome}"
            assert isinstance(outcome.get("error"), PermissionError), outcome
            assert not observed
            return
        if client_kind == "powershell-container":
            assert exit_code == 0, f"AppContainer .NET client could not open the unqualified pipe; listener={outcome}"
            assert isinstance(outcome.get("error"), PermissionError), outcome
            assert not observed
            return
        if client_kind == "powershell-createfile":
            probe_error_path = os.path.join(
                os.environ["LOCALAPPDATA"], "Packages", profile, "AC", "Temp",
                "opencode-createfile-error.txt",
            )
            probe_error = ""
            if os.path.exists(probe_error_path):
                with open(probe_error_path, encoding="utf-8") as error_file:
                    probe_error = error_file.read()
            assert exit_code == 2, (
                f"Win32 CreateFileW error {exit_code}; probe={probe_error!r}; listener={outcome}"
            )
            assert isinstance(outcome.get("error"), TimeoutError), outcome
            assert not observed
            return
        assert exit_code == 0, f"AppContainer client stage exit {exit_code}; listener={outcome}; Hub={observed}"
        assert outcome == {"returned": True}
        assert observed == {"path": "/api/chat/completions", "body": b"{}"}
    finally:
        if pipe_thread is not None:
            pipe_thread.join(timeout=20)
        if dotnet_server is not None and dotnet_server.poll() is None:
            dotnet_server.terminate()
            try:
                dotnet_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dotnet_server.kill()
                dotnet_server.wait(timeout=5)
        hub.shutdown()
        hub_thread.join(timeout=2)
        hub.server_close()
        if sid_text:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(sid_text, wintypes.HLOCAL))
        if app_sid:
            advapi32.FreeSid(app_sid)
        userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
        userenv.DeleteAppContainerProfile.restype = ctypes.c_long
        userenv.DeleteAppContainerProfile(profile)


def test_appcontainer_workspace_junction_cannot_read_private_external_target():
    """A writable staged root must not grant access through a junction escape."""
    import win32api
    import win32security

    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    profile = "LAH-OC-WKSP-" + uuid.uuid4().hex
    app_sid = ctypes.c_void_p()
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    hr = userenv.CreateAppContainerProfile(profile, profile, "temporary workspace isolation test", None, 0, ctypes.byref(app_sid))
    assert hr >= 0, f"CreateAppContainerProfile HRESULT 0x{hr & 0xFFFFFFFF:08x}"
    sid_text = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    assert advapi32.ConvertSidToStringSidW(app_sid, ctypes.byref(sid_text))

    current_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
    )
    try:
        user_sid = win32security.GetTokenInformation(current_token, win32security.TokenUser)[0]
        session_id = win32security.GetTokenInformation(current_token, win32security.TokenSessionId)
        groups = win32security.GetTokenInformation(current_token, win32security.TokenGroups)
        logon_sids = [
            win32security.ConvertSidToStringSid(sid)
            for sid, attributes in groups
            if attributes & 0xC0000000 == 0xC0000000
        ]
    finally:
        win32api.CloseHandle(current_token)
    assert len(logon_sids) == 1, f"expected one host logon SID, got {logon_sids!r}"

    try:
        with tempfile.TemporaryDirectory(prefix="lah-opencode-workspace-test-") as temp_root:
            root = Path(temp_root)
            stage = root / "workspace"
            external = Path(__file__).resolve().parents[1]
            stage.mkdir()

            dacl = win32security.ACL()
            inherit = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
            for sid in (user_sid, win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None),
                        win32security.ConvertStringSidToSid(sid_text.value)):
                dacl.AddAccessAllowedAceEx(
                        win32security.ACL_REVISION_DS, inherit, 0x1F01FF, sid,
                )
            win32security.SetNamedSecurityInfo(
                str(stage), win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, dacl, None,
            )
            (stage / "inside.txt").write_text("inside", encoding="utf-8")

            junction = stage / "escape"
            powershell = shutil.which("powershell")
            assert powershell, "Windows PowerShell executable not found"
            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 f"New-Item -ItemType Junction -Path '{junction}' -Target '{external}' | Out-Null"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            assert result.returncode == 0 and junction.is_dir(), result.stderr or result.stdout

            escaped_file = junction / "docs" / "OPENCODE.md"
            script = (
                "$ErrorActionPreference='Stop';"
                f"try {{ Move-Item -LiteralPath '{stage}' -Destination '{stage}-moved' -ErrorAction Stop; exit 40 }} catch {{ }};"
                f"if([IO.File]::ReadAllText('{stage / 'inside.txt'}') -ne 'inside'){{exit 41}};"
                "try { [void][IO.File]::ReadAllText('" + str(escaped_file) + "'); exit 42 } "
                "catch [System.UnauthorizedAccessException] { exit 0 } "
                "catch [System.IO.IOException] { exit 0 } "
                "catch [System.Security.SecurityException] { exit 0 } "
                "catch { exit 43 }"
            )
            environment = {
                "SystemRoot": os.environ["SystemRoot"],
                "WINDIR": os.environ["WINDIR"],
                "LOCALAPPDATA": os.path.join(os.environ["LOCALAPPDATA"], "Packages", profile, "AC", "Temp"),
                "APPDATA": str(stage),
                "TEMP": str(stage),
                "TMP": str(stage),
                "PATH": os.path.dirname(powershell),
            }
            os.makedirs(environment["LOCALAPPDATA"], exist_ok=True)
            exit_code = _launch_appcontainer_process(
                powershell,
                ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                 base64.b64encode(script.encode("utf-16le")).decode("ascii")],
                app_sid, sid_text.value, session_id, logon_sids[0], environment=environment,
            )
            assert exit_code == 0, f"AppContainer junction read probe exited {exit_code}"
    finally:
        if sid_text:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(sid_text, wintypes.HLOCAL))
        if app_sid:
            advapi32.FreeSid(app_sid)
        userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
        userenv.DeleteAppContainerProfile.restype = ctypes.c_long
        userenv.DeleteAppContainerProfile(profile)


def test_production_appcontainer_process_uses_explicit_environment_and_job():
    """Exercise the production suspended launch primitive with a disposable child."""
    from local_ai_hub.opencode_appcontainer import (
        ManagedAppContainerProcessSession,
    )

    session = None
    try:
        with tempfile.TemporaryDirectory(prefix="lah-opencode-production-stage-") as temp_root:
            session = ManagedAppContainerProcessSession.create()
            stage = session.stage
            (stage / "inside.txt").write_text("inside", encoding="utf-8")
            powershell = shutil.which("powershell")
            assert powershell
            external = Path(__file__).resolve().parents[1]
            junction = stage / "escape"
            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 f"New-Item -ItemType Junction -Path '{junction}' -Target '{external}' | Out-Null"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            assert result.returncode == 0 and junction.is_dir(), result.stderr or result.stdout
            escaped_file = junction / "docs" / "OPENCODE.md"
            script = (
                "$ErrorActionPreference='Stop';"
                f"if([IO.File]::ReadAllText('{stage / 'inside.txt'}') -ne 'inside'){{exit 41}};"
                "try { [void][IO.File]::ReadAllText('" + str(escaped_file) + "'); exit 42 } "
                "catch [System.UnauthorizedAccessException] { exit 0 } "
                "catch [System.IO.IOException] { exit 0 } "
                "catch [System.Security.SecurityException] { exit 0 } "
                "catch { exit 43 }"
            )
            environment = {
                "SystemRoot": os.environ["SystemRoot"],
                "WINDIR": os.environ["WINDIR"],
                "LOCALAPPDATA": os.path.join(os.environ["LOCALAPPDATA"], "Packages", session.profile.name, "AC", "Temp"),
                "APPDATA": str(stage), "TEMP": str(stage), "TMP": str(stage),
                "PATH": os.path.dirname(powershell),
            }
            os.makedirs(environment["LOCALAPPDATA"], exist_ok=True)
            session.launch(
                powershell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                    base64.b64encode(script.encode("utf-16le")).decode("ascii")],
                environment,
            )
            assert session.wait(15_000) == 0
            session.close()
            assert session.state == "closed"
    finally:
        if session is not None:
            session.close()


def test_managed_appcontainer_session_cancel_confirms_owned_job_empty():
    from local_ai_hub.opencode_appcontainer import ManagedAppContainerProcessSession

    powershell = shutil.which("powershell")
    assert powershell
    session = None
    try:
        with tempfile.TemporaryDirectory(prefix="lah-opencode-cancel-stage-") as temp_root:
            session = ManagedAppContainerProcessSession.create()
            stage = session.stage
            environment = {
                "SystemRoot": os.environ["SystemRoot"],
                "WINDIR": os.environ["WINDIR"],
                "LOCALAPPDATA": os.path.join(os.environ["LOCALAPPDATA"], "Packages", session.profile.name, "AC", "Temp"),
                "APPDATA": str(stage), "TEMP": str(stage), "TMP": str(stage),
                "PATH": os.path.dirname(powershell),
            }
            os.makedirs(environment["LOCALAPPDATA"], exist_ok=True)
            session.launch(powershell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 30"], environment)
            time.sleep(0.2)
            session.cancel()
            assert session.state == "cancelled"
            session.close()
    finally:
        if session is not None:
            session.close()


def test_stage_acl_refuses_a_root_junction_without_touching_target():
    from local_ai_hub.opencode_appcontainer import grant_staged_workspace_access

    with tempfile.TemporaryDirectory(prefix="lah-opencode-stage-junction-") as temp_root:
        root = Path(temp_root)
        target = root / "target"
        target.mkdir()
        link = root / "workspace"
        powershell = shutil.which("powershell")
        assert powershell
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' | Out-Null"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 0 and link.is_dir(), result.stderr or result.stdout
        with pytest.raises(ValueError, match="reparse point"):
            grant_staged_workspace_access(link, "S-1-15-2-123-456")


def test_managed_session_rejects_stage_path_replacement_before_launch():
    from local_ai_hub.opencode_appcontainer import ManagedAppContainerProcessSession

    powershell = shutil.which("powershell")
    assert powershell
    with tempfile.TemporaryDirectory(prefix="lah-opencode-stage-swap-") as temp_root:
        root = Path(temp_root)
        target = root / "external"
        target.mkdir()
        session = ManagedAppContainerProcessSession.create()
        stage = session.stage
        try:
            moved = root / "workspace-original"
            stage.rename(moved)
            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 f"New-Item -ItemType Junction -Path '{stage}' -Target '{target}' | Out-Null"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            assert result.returncode == 0 and stage.is_dir(), result.stderr or result.stdout
            with pytest.raises(RuntimeError, match="path changed"):
                session.launch(powershell, ["-NoProfile", "-Command", "exit 0"], {
                    "SystemRoot": os.environ["SystemRoot"],
                    "WINDIR": os.environ["WINDIR"],
                    "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
                    "TEMP": str(stage), "TMP": str(stage), "PATH": os.path.dirname(powershell),
                })
        finally:
            session.close()


def test_managed_session_stops_owned_pipe_listener_before_profile_cleanup():
    from local_ai_hub.opencode_appcontainer import ManagedAppContainerProcessSession

    with tempfile.TemporaryDirectory(prefix="lah-opencode-listener-stage-") as temp_root:
        session = ManagedAppContainerProcessSession.create()
        try:
            session.start_pipe_listener(hub_port=1, io_timeout=5)
            assert session.pipe_thread is not None and session.pipe_thread.is_alive()
            assert session.pipe_listener.pipe_ready.is_set()
            worker = session.pipe_thread
            session.close()
            assert session.state == "closed"
            assert not worker.is_alive()
        finally:
            session.close()


def test_managed_session_close_invalidates_credentials_and_removes_stage():
    from local_ai_hub.opencode_appcontainer import ManagedAppContainerProcessSession

    session = ManagedAppContainerProcessSession.create()
    stage = session.stage
    profile = session.profile
    session.start_pipe_listener(hub_port=1, hub_api_token="host-only-test-token")
    listener = session.pipe_listener
    assert listener is not None
    temporary_descriptor = stage / ("bridge-" + session.session_id + ".port")
    temporary_descriptor.write_text("12345", encoding="ascii")

    session.close()

    assert session.state == "closed"
    assert session.secret == b""
    assert listener.secret == b""
    assert listener.hub_api_token is None
    assert session.pipe_listener is None
    assert session.pipe_thread is None
    assert session.stage_handle is None
    assert session.job_handle == 0
    assert profile._closed
    assert not temporary_descriptor.exists()
    assert not stage.exists()


def test_managed_session_bridge_and_opencode_profile_boundary():
    from local_ai_hub.opencode_appcontainer import ManagedAppContainerProcessSession

    observed: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed["path"] = self.path
            body = self.rfile.read(int(self.headers["Content-Length"]))
            observed["body"] = body
            request = json.loads(body)
            if request.get("stream") is True:
                chunks = [
                    {"id":"chatcmpl-test","object":"chat.completion.chunk","created":0,
                     "model":"fake-model","choices":[{"index":0,"delta":{"role":"assistant","content":"managed ok"},"finish_reason":None}]},
                    {"id":"chatcmpl-test","object":"chat.completion.chunk","created":0,
                     "model":"fake-model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]},
                    {"id":"chatcmpl-test","object":"chat.completion.chunk","created":0,
                     "model":"fake-model","choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}},
                ]
                response = b"".join(
                    b"data: " + json.dumps(chunk, separators=(",", ":")).encode("utf-8") + b"\n\n"
                    for chunk in chunks
                ) + b"data: [DONE]\n\n"
                content_type = "text/event-stream; charset=utf-8"
            else:
                response = (
                b'{"id":"chatcmpl-test","object":"chat.completion","created":0,'
                b'"model":"fake-model","choices":[{"index":0,"message":'
                b'{"role":"assistant","content":"managed ok"},"finish_reason":"stop"}]}'
                )
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            observed["response_sent"] = True

        def log_message(self, *_args):
            pass

    hub = HTTPServer(("127.0.0.1", 0), Handler)
    hub_thread = threading.Thread(target=hub.serve_forever, daemon=True)
    hub_thread.start()
    session = None
    try:
        with tempfile.TemporaryDirectory(prefix="lah-opencode-managed-roundtrip-") as temp_root:
            project_root = Path(temp_root) / "authorized-project"
            project_root.mkdir()
            session = ManagedAppContainerProcessSession.create()
            stage = session.stage
            session.start_pipe_listener(
                hub_port=hub.server_port, repository_root=str(project_root.resolve()), io_timeout=10,
            )
            node = shutil.which("node")
            assert node
            bridge_source = Path(__file__).resolve().parents[1] / "tools" / "opencode_pipe_client.cjs"
            bridge_copy = stage / "opencode_pipe_client.cjs"
            shutil.copy2(bridge_source, bridge_copy)
            environment = {
                "SystemRoot": os.environ["SystemRoot"],
                "WINDIR": os.environ["WINDIR"],
                "LOCALAPPDATA": os.path.join(os.environ["LOCALAPPDATA"], "Packages", session.profile.name, "AC", "Temp"),
                "APPDATA": str(stage), "TEMP": str(stage), "TMP": str(stage),
                "HOME": str(stage), "USERPROFILE": str(stage),
                "PATH": os.path.dirname(node),
            }
            os.makedirs(environment["LOCALAPPDATA"], exist_ok=True)
            appcontainer_entry = (
                "const fs=require('node:fs'),Module=require('node:module');"
                "const file=process.argv[1],bridge=new Module(file);"
                "bridge.filename=file;bridge.paths=module.paths;"
                "bridge._compile(fs.readFileSync(file,'utf8'),file);bridge.exports.runCli();"
            )
            bridge_pid = session.launch_bridge(node, ["-e", appcontainer_entry, str(bridge_copy)], environment)
            bridge_port = session.wait_bridge_port()
            client_script = f"""
const net=require('node:net');
const client=net.connect({bridge_port},'127.0.0.1');
const chunks=[];
const timer=setTimeout(()=>process.exit(90),8000);
client.on('data',data=>chunks.push(data));
client.on('end',()=>{{
  const response=Buffer.concat(chunks).toString('ascii');
  if(!response.startsWith('HTTP/1.1 200 OK\\r\\n') || !response.includes('managed ok')) process.exit(91);
  clearTimeout(timer); process.exit(0);
}});
client.on('error',()=>process.exit(92));
client.write('POST /api/chat/completions HTTP/1.1\\r\\nHost: ignored.invalid\\r\\nContent-Type: application/json\\r\\nContent-Length: 2\\r\\n\\r\\n{{}}');
"""
            client_pid = session.launch(node, ["-e", client_script], environment)
            assert session.wait_child(client_pid, 15_000) == 0, (
                f"request child failed; listener={session.pipe_error}; Hub={observed}"
            )
            assert bridge_pid in [child.pid for child in session.processes]
            assert observed["path"] == "/api/chat/completions"
            assert json.loads(observed["body"]) == {"root": str(project_root.resolve())}
            assert observed["response_sent"] is True

            opencode = shutil.which("opencode") or (
                str(Path.home() / "AppData" / "Local" / "Programs" / "OpenCode-LocalAIHub"
                    / "2.2.5" / "opencode.exe")
            )
            assert opencode and os.path.isfile(opencode), "OpenCode 2.2.5 executable is unavailable"
            staged_opencode = stage / "opencode.exe"
            shutil.copy2(opencode, staged_opencode)
            config_path = stage / "opencode.json"
            config_path.write_text(json.dumps({
                "providers": {
                    "local-ai-hub": {
                        "name": "Local AI Hub",
                        "package": "@opencode/ai/providers/openai-compatible",
                        "settings": {"baseURL": f"http://127.0.0.1:{bridge_port}/api"},
                        "headers": {"X-LocalAI-Agent": "opencode"},
                        "models": {"auto": {
                            "name": "Local AI Hub Auto",
                            "modelID": "auto",
                            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
                            "limit": {"context": 32768, "output": 1024},
                        }},
                    },
                },
                "model": "local-ai-hub/auto",
            }), encoding="utf-8")
            opencode_environment = {
                **environment,
                "OPENCODE_CONFIG": str(config_path),
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "OPENCODE_DISABLE_TELEMETRY": "1",
                "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "XDG_CONFIG_HOME": str(stage / "xdg-config"),
                "XDG_DATA_HOME": str(stage / "xdg-data"),
                "XDG_CACHE_HOME": str(stage / "xdg-cache"),
                "XDG_STATE_HOME": str(stage / "xdg-state"),
                "TMPDIR": str(stage / "tmpdir"),
            }
            debug_paths_pid = session.launch(str(staged_opencode), ["debug", "paths"], opencode_environment)
            assert session.wait_child(debug_paths_pid, 10_000) == 0
            observed.clear()
            opencode_pid = session.launch(str(staged_opencode), [
                "--print-logs", "--log-level", "error", "run", "--standalone",
                "--model", "local-ai-hub/auto", "--format", "json",
                "respond with exactly managed ok",
            ], opencode_environment)
            try:
                opencode_exit = session.wait_child(opencode_pid, 15_000)
            except TimeoutError:
                request = json.loads(observed["body"])
                prompt_present = any(
                    "respond with exactly managed ok" in str(message.get("content"))
                    for message in request["messages"]
                )
                summary = {
                    "path": observed.get("path"), "model": request.get("model"),
                    "stream": request.get("stream"), "prompt_present": prompt_present,
                    "root": request.get("root"), "response_sent": observed.get("response_sent"),
                }
                assert observed.get("path") == "/api/chat/completions"
                assert request["model"] == "auto"
                assert request.get("root") == str(project_root.resolve())
                assert prompt_present, f"OpenCode lost the test prompt; request={summary}"
                assert observed.get("response_sent") is True, "fake Hub response was not fully written"
                assert session.state == "cancelled" and not session.processes
            else:
                request = json.loads(observed["body"])
                summary = {
                    "path": observed.get("path"), "model": request.get("model"),
                    "stream": request.get("stream"), "response_sent": observed.get("response_sent"),
                }
                assert opencode_exit == 0, f"OpenCode failed after the fake Hub response; {summary}"
                assert observed.get("path") == "/api/chat/completions"
                request = json.loads(observed["body"])
                assert request["model"] == "auto"
                assert request.get("root") == str(project_root.resolve())
                assert any("respond with exactly managed ok" in str(message.get("content"))
                           for message in request["messages"])
            staged_path = session.stage
            session.close()
            assert not staged_path.exists(), f"session stage was not removed: {staged_path}"
    finally:
        if session is not None:
            session.close()
        hub.shutdown()
        hub_thread.join(timeout=2)
        hub.server_close()


def test_managed_bridge_and_open_code_children_share_one_job_without_secret_inheritance():
    from local_ai_hub.opencode_appcontainer import ManagedAppContainerProcessSession

    node = shutil.which("node")
    powershell = shutil.which("powershell")
    assert node and powershell
    session = ManagedAppContainerProcessSession.create()
    try:
        session.start_pipe_listener(hub_port=1, io_timeout=5)
        common_environment = {
            "SystemRoot": os.environ["SystemRoot"],
            "WINDIR": os.environ["WINDIR"],
            "LOCALAPPDATA": os.path.join(os.environ["LOCALAPPDATA"], "Packages", session.profile.name, "AC", "Temp"),
            "APPDATA": str(session.stage), "TEMP": str(session.stage), "TMP": str(session.stage),
            "PATH": os.path.dirname(node),
        }
        os.makedirs(common_environment["LOCALAPPDATA"], exist_ok=True)
        bridge_pid = session.launch_bridge(node, ["-e", "setInterval(()=>{},1000)"], common_environment)
        app_environment = {**common_environment, "PATH": os.path.dirname(powershell)}
        env_probe = session.stage / "open-code-env.txt"
        check_secret = (
            "$present=Test-Path Env:LOCAL_AI_PIPE_SECRET;"
            f"[IO.File]::WriteAllText('{env_probe}',[string]$present);"
            "Start-Sleep -Seconds 30"
        )
        opencode_pid = session.launch(
            powershell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", check_secret],
            app_environment,
        )
        assert bridge_pid != opencode_pid
        assert len(session.processes) == 2
        assert session.processes[0].job_handle == session.processes[1].job_handle == session.job_handle
        assert all(not child.owns_job for child in session.processes)
        deadline = time.monotonic() + 5
        while not env_probe.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert env_probe.read_text(encoding="utf-8") == "False"
        session.cancel()
        assert session.state == "cancelled" and not session.processes
    finally:
        session.close()
