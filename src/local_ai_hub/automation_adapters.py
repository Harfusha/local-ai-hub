"""Existing Playwright MCP and winapp transports; no executable/code passthrough."""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import secrets
import shutil
import tempfile
import time
import threading
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

from .process_utils import process_identity, run_hidden


class MCPTransport:
    def __init__(self, command: list[str], timeout: float, cwd: Path):
        from anyio.from_thread import start_blocking_portal
        self._context = start_blocking_portal()
        self._portal = self._context.__enter__()
        self._closed = False
        self._future = None
        self._cancel_requested = threading.Event()
        try:
            self._connection = self._portal.wrap_async_context_manager(self._connect(command, timeout, cwd))
            self._client = self._connection.__enter__()
        except BaseException:
            self._context.__exit__(None, None, None)
            raise

    @staticmethod
    @asynccontextmanager
    async def _connect(command, timeout, cwd):
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        # The MCP SDK uses hidden Windows processes with Job Object tree cleanup.
        env = {key: value for key, value in os.environ.items() if key.upper() in {
            'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA'}}
        params = StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=str(cwd))
        with open(os.devnull, 'w') as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=timeout)) as client:
                    with anyio.fail_after(timeout):
                        await client.initialize()
                    yield client

    def call(self, code: str, timeout: float) -> dict[str, Any]:
        if self._closed or self._cancel_requested.is_set():
            raise RuntimeError('Playwright MCP transport has been cancelled')
        async def perform():
            result = await asyncio.wait_for(self._client.call_tool('browser_run_code_unsafe', {'code': code}), timeout)
            if result.isError:
                detail = ' '.join(block.text for block in result.content if getattr(block, 'type', '') == 'text')
                raise RuntimeError('Playwright MCP rejected operation: ' + detail[:1000])
            # Accept only the tool's explicit result section. Never forward snapshots,
            # console logs, page-generated MCP tools or other upstream prose.
            for block in result.content:
                if getattr(block, 'type', '') != 'text':
                    continue
                text = block.text
                if len(text) > 262144:
                    raise ValueError('oversized Playwright MCP response')
                marker = '### Result\n'
                if text.startswith(marker):
                    raw = text[len(marker):].split('\n### ', 1)[0].strip()
                    value = json.loads(raw)
                    if isinstance(value, str):
                        value = json.loads(value)
                    if isinstance(value, dict):
                        return value
            raise ValueError('Playwright MCP returned no structured operation result')
        future = self._portal.start_task_soon(perform)
        self._future = future
        if self._cancel_requested.is_set():
            future.cancel()
        try:
            return future.result(timeout=timeout + 2)
        except BaseException:
            future.cancel()
            raise
        finally:
            self._future = None

    def cancel(self):
        self._cancel_requested.set()
        if self._future is not None:
            self._future.cancel()

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._connection.__exit__(None, None, None)
            finally:
                self._context.__exit__(None, None, None)


class BrowserMCPAdapter:
    COMMANDS = {'navigate', 'snapshot', 'click', 'fill', 'press', 'select', 'check', 'hover', 'drag', 'scroll',
                'screenshot', 'dialog', 'upload', 'download', 'tabs', 'new_tab', 'close_tab', 'switch_tab'}

    def __init__(self, mode, config, request, policy, state_dir, *, transport=None, persist_binary=None):
        self.config, self.mode, self.policy = config, mode, policy
        self.output = Path(tempfile.mkdtemp(prefix='browser-', dir=str(state_dir)))
        self.persist_binary = persist_binary
        self.owner = secrets.token_hex(24)
        self.tab = 'main'
        self.initialized = False
        self.closed = False
        self.initial_url = request['url']
        self.script = Path(__file__).with_name('automation_browser.js').read_text(encoding='utf-8')
        try:
            if transport is None:
                command = config.get('playwright_command', [])
                if (len(command) != 2 or Path(command[0]).name.lower() not in {'node', 'node.exe'} or
                        not all(Path(p).is_absolute() and Path(p).is_file() for p in command) or
                        Path(command[1]).suffix.lower() not in {'.js', '.mjs', '.cjs'}):
                    raise ValueError('configure installed node executable and @playwright/mcp CLI; no automatic downloads')
                args = [*command, '--output-dir', str(self.output)]
                if mode == 'isolated':
                    args += ['--isolated', '--headless', '--browser', 'chrome']
                else:
                    args += ['--extension']
                    if config.get('profile_directory'):
                        args += ['--profile-dir-name', config['profile_directory']]
                transport = MCPTransport(args, request.get('timeout_seconds', config.get('timeout_seconds', 20)), self.output)
            self.transport = transport
        except BaseException:
            shutil.rmtree(self.output)
            raise

    def execute(self, request, timeout):
        if self.closed:
            raise RuntimeError('browser adapter closed')
        command = request.get('command')
        if command not in self.COMMANDS:
            raise ValueError('unsupported browser command')
        selectors = {'click', 'fill', 'press', 'select', 'check', 'hover', 'drag', 'upload', 'download'}
        if command in selectors and (not isinstance(request.get('selector'), str) or not 1 <= len(request['selector']) <= 2048):
            raise ValueError('command requires a bounded CSS selector')
        for name in ('selector', 'destination'):
            value = request.get(name)
            if isinstance(value, str) and (name == 'selector' or command == 'drag') and (
                    '>>' in value or 'internal:' in value or value.startswith(('xpath=', 'css=', 'text=', 'role=', '//'))):
                raise ValueError('only plain CSS selectors on the owned main frame are supported')
        for key in ('text', 'key', 'option', 'destination'):
            if key in request and (not isinstance(request[key], str) or len(request[key]) > 12000):
                raise ValueError(f'{key} must be a bounded string')
        for key in ('checked', 'accept'):
            if key in request and type(request[key]) is not bool:
                raise ValueError(f'{key} must be boolean')
        for key in ('x', 'y'):
            if key in request and (type(request[key]) not in (float, int) or not -10000 <= request[key] <= 10000):
                raise ValueError('scroll must be bounded')
        required = {'fill': 'text', 'press': 'key', 'select': 'option', 'check': 'checked', 'dialog': 'accept',
                    'drag': 'destination', 'switch_tab': 'destination', 'navigate': 'url', 'new_tab': 'url', 'upload': 'files'}
        if command in required and required[command] not in request:
            raise ValueError(f'{command} requires {required[command]}')
        output_file = self.output / (secrets.token_hex(16) + ('.png' if command == 'screenshot' else '.bin'))
        data = {'arguments': {k: v for k, v in request.items() if k not in {'session_key', 'session_id', 'request_id', 'op'}},
                'rules': self.policy.rules, 'mode': self.mode, 'owner': self.owner, 'tab': self.tab,
                'initialize': not self.initialized, 'initialUrl': self.initial_url, 'timeout': max(1, int(timeout * 1000)),
                'maxChars': self.config.get('max_output_chars', 12000),
                'maxBinaryBytes': self.config.get('max_binary_bytes', 8388608), 'outputFile': str(output_file)}
        code = self.script.replace(
            '__LOCAL_AI_AUTOMATION_INPUT__',
            json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(',', ':')),
        )
        result = self.transport.call(code, timeout)
        self.initialized = True
        if result.get('success') is False:
            return result
        if result.get('tab_id') and command in {'new_tab', 'switch_tab'}:
            self.tab = result['tab_id']
        if command == 'close_tab':
            self.tab = 'main'
        artifact_path = result.pop('artifact_path', None)
        if artifact_path:
            path = Path(artifact_path)
            if path != output_file or path.is_symlink() or not path.resolve().is_relative_to(self.output.resolve()):
                raise ValueError('backend artifact escaped session directory')
            if not path.is_file() or not 0 < path.stat().st_size <= self.config.get('max_binary_bytes', 8388608):
                raise ValueError('backend binary exceeds configured bound')
            if self.persist_binary is None:
                raise ValueError('binary artifact persistence unavailable')
            result.update(self.persist_binary(path.read_bytes(), result.pop('mime_type', 'application/octet-stream')))
            path.unlink()
        if len(json.dumps(result, separators=(',', ':'))) > self.config.get('max_output_chars', 12000) * 4:
            raise ValueError('backend result exceeds bound')
        return result

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.transport.close()
            finally:
                shutil.rmtree(self.output)

    def cancel(self):
        cancel = getattr(self.transport, 'cancel', None)
        if callable(cancel):
            cancel()


def window_identity(hwnd: int) -> dict[str, Any]:
    if os.name != 'nt':
        raise OSError('desktop automation requires Windows')
    from ctypes import wintypes
    user32, kernel32 = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        raise PermissionError('window no longer exists')
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        raise PermissionError('window process is inaccessible')
    try:
        size, buffer = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise PermissionError('cannot resolve window executable')
        identity = process_identity(pid.value)
        if not identity:
            raise PermissionError('cannot bind process lifetime')
        return {**identity, 'exe': str(Path(buffer.value).resolve())}
    finally:
        kernel32.CloseHandle(handle)


class WinAppAdapter:
    BLOCKED = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'chromium.exe', 'opera.exe',
               'cmd.exe', 'powershell.exe', 'pwsh.exe', 'windowsterminal.exe', 'wt.exe', 'explorer.exe'}
    COMMANDS = {'inspect': 'inspect', 'invoke': 'invoke', 'set_value': 'set-value', 'get_value': 'get-value',
                'click': 'click', 'hover': 'hover', 'focus': 'focus', 'press': 'send-keys', 'screenshot': 'screenshot'}

    def __init__(self, mode, config, request, state_dir, *, resolver=window_identity, runner=run_hidden, persist_binary=None):
        self.config, self.resolver, self.runner = config, resolver, runner
        self._cancel = threading.Event()
        self.sandbox = mode == 'desktop_sandbox'
        if self.sandbox and not config.get('sandbox_enabled', False):
            raise PermissionError('Windows Sandbox must be explicitly enabled and prepared by the operator')
        self._deadline = time.monotonic() + request.get('timeout_seconds', config.get('timeout_seconds', 20))
        self.output, self.persist_binary = Path(state_dir), persist_binary
        self.window = request.get('window_id')
        if type(self.window) is not int or not 0 < self.window < 1 << 63:
            raise ValueError('desktop requires a positive window_id')
        executable = config.get('winapp_executable', '')
        if not executable or not Path(executable).is_file():
            raise ValueError('configure installed winapp.exe; no automatic installation')
        self.executable = executable
        if self.sandbox and resolver is window_identity:
            self.resolver = self._guest_identity
        target = config.get('allowed_sandbox_applications' if self.sandbox else 'allowed_applications', {}).get(request.get('application'))
        if not target:
            raise PermissionError('application is not configured')
        self.identity = self.resolver(self.window)
        path_type = PureWindowsPath if self.sandbox else Path
        actual, expected = path_type(self.identity['exe']), path_type(target)
        if actual.name.lower() in self.BLOCKED or (actual != expected if self.sandbox else actual.resolve() != expected.resolve()):
            raise PermissionError('window executable is not the configured desktop target; browsers require browser sessions')

    def _remaining(self):
        value = self._deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError('desktop operation deadline exceeded')
        return value

    def _guest_identity(self, hwnd):
        # Only a validated integer is inserted. This fixed read-only helper runs
        # inside the existing winapp guest transport, never a host shell.
        script = '''$ErrorActionPreference='Stop'; Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class HubWindowIdentity { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid); }';
$taskProcessId=[uint32]0; [void][HubWindowIdentity]::GetWindowThreadProcessId([IntPtr]__HWND__,[ref]$taskProcessId);
if ($taskProcessId -eq 0) { throw 'window missing' }; $taskProcess=Get-Process -Id $taskProcessId -ErrorAction Stop;
@{exe=$taskProcess.Path;pid=$taskProcess.Id;creation_identity=$taskProcess.StartTime.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json -Compress'''.replace('__HWND__', str(hwnd))
        result = self.runner([self.executable, 'target', 'exec', 'sandbox', '--',
                              r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', '-NoProfile',
                              '-NonInteractive', '-Command', script], timeout=self._remaining(), capture_output=True,
                             text=True, max_output_bytes=8192, cancel_event=self._cancel)
        if result.returncode or getattr(result, 'stdout_truncated', False):
            raise PermissionError('guest window identity unavailable; no host fallback')
        identity = json.loads(result.stdout)
        if (not isinstance(identity, dict) or set(identity) != {'exe', 'pid', 'creation_identity'} or
                not isinstance(identity['exe'], str) or not PureWindowsPath(identity['exe']).is_absolute() or
                type(identity['pid']) is not int or identity['pid'] <= 0 or
                not isinstance(identity['creation_identity'], str) or not identity['creation_identity']):
            raise PermissionError('guest returned malformed window identity')
        return identity

    def execute(self, request, timeout):
        self._deadline = time.monotonic() + timeout
        if self.resolver(self.window) != self.identity:
            raise PermissionError('window process identity changed')
        command = request.get('command')
        if command not in self.COMMANDS:
            raise ValueError('unsupported desktop command')
        if command in {'click', 'hover', 'focus', 'press'} and not self.config.get('allow_physical_input', False):
            raise PermissionError('physical input is disabled')
        selector = request.get('selector', '')
        if not isinstance(selector, str) or len(selector) > 2048 or selector.startswith('-') or '\0' in selector:
            raise ValueError('invalid UI selector')
        args = [self.executable, 'ui', self.COMMANDS[command]]
        if command in {'invoke', 'set_value', 'get_value', 'click', 'hover'} and not selector:
            raise ValueError('command requires an element selector')
        if selector and command != 'press':
            args.append(selector)
        if command == 'set_value':
            text = request.get('text')
            if not isinstance(text, str) or len(text) > 12000 or text.startswith('-') or '\0' in text:
                raise ValueError('invalid UI value')
            args.append(text)
        if command == 'press':
            key = request.get('key', '')
            if not isinstance(key, str) or key.lower() not in {'enter', 'escape', 'tab', 'space', 'up', 'down', 'left', 'right', 'backspace', 'delete'}:
                raise ValueError('system shortcuts are not scoped desktop keys')
            args.append(key)
            if selector:
                args += ['--target', selector]
        output_file = self.output / (secrets.token_hex(16) + '.png')
        if command == 'screenshot':
            args += ['--output', str(output_file)]
        args += ['-w', str(self.window), '--json']
        if self.sandbox:
            args += ['--on', 'sandbox']
        completed = self.runner(args, timeout=self._remaining(), capture_output=True, text=True,
                                cancel_event=self._cancel,
                                max_output_bytes=self.config.get('max_output_chars', 12000) * 4)
        if getattr(completed, 'stdout_truncated', False) or completed.returncode:
            raise RuntimeError('winapp operation failed or output exceeded configured bound')
        if self.resolver(self.window) != self.identity:
            raise PermissionError('window identity changed during operation')
        if command == 'screenshot':
            if output_file.is_symlink() or not output_file.is_file() or not 0 < output_file.stat().st_size <= self.config.get('max_binary_bytes', 8388608):
                raise ValueError('desktop screenshot exceeds configured bound')
            try:
                if self.persist_binary is None:
                    raise ValueError('binary artifact persistence unavailable')
                return self.persist_binary(output_file.read_bytes(), 'image/png')
            finally:
                output_file.unlink(missing_ok=True)
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise ValueError('malformed winapp response')
        return value

    def close(self):
        # Never close or kill an application owned by the user.
        pass

    def cancel(self):
        self._cancel.set()
