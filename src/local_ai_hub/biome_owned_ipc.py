"""Windows-only, process-owned Biome LSP transport.

Biome's public proxy attaches to a shared version-named server.  This module
starts the foreground server itself and verifies every pipe peer before LSP
traffic.  Unsupported transports fail closed.
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import subprocess
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any, Callable

from .process_utils import popen_managed, terminate_tree

_MAX_FRAME = 4_000_000
_MAX_CAPTURE = 8192
# This implementation is grounded to the currently reviewed upstream protocol
# source and release only.  Any other installed version fails before server IPC.
_VERSION = re.compile(r"^biome (2\.5\.15)$", re.IGNORECASE)


class BiomeOwnershipError(RuntimeError):
    pass


def _assert_peer_pid(actual_pid: int, expected_pid: int) -> None:
    if actual_pid != expected_pid:
        raise BiomeOwnershipError("Biome pipe belongs to a different process")


def _frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if not body or len(body) > _MAX_FRAME:
        raise ValueError("Biome LSP frame limit exceeded")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def _read(stream: Any) -> dict[str, Any] | None:
    length = None
    for _ in range(16):
        line = stream.readline(2049)
        if not line:
            return None
        if len(line) > 2048 or not line.endswith(b"\n"):
            raise ValueError("invalid Biome LSP header")
        if line in (b"\r\n", b"\n"):
            break
        name, sep, value = line.partition(b":")
        if sep and name.lower() == b"content-length":
            if length is not None:
                raise ValueError("duplicate Biome LSP content length")
            length = int(value.strip())
    else:
        raise ValueError("Biome LSP header limit exceeded")
    if length is None or not 0 < length <= _MAX_FRAME:
        raise ValueError("Biome LSP frame limit exceeded")
    data = bytearray()
    while len(data) < length:
        part = stream.read(length - len(data))
        if not part:
            raise EOFError("incomplete Biome LSP frame")
        data.extend(part)
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Biome LSP message must be an object")
    return value


def _windows_pipe(path: str, expected_pid: int):
    if os.name != "nt":
        raise BiomeOwnershipError("owned Biome daemon transport is supported only on Windows")
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    get_pid = kernel.GetNamedPipeServerProcessId
    get_pid.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    get_pid.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    invalid = wintypes.HANDLE(-1).value
    handle = create(path, 0xC0000000, 0, None, 3, 0, None)  # GENERIC_RW, OPEN_EXISTING
    if handle == invalid:
        raise OSError(ctypes.get_last_error(), "Biome named-pipe connect failed")
    try:
        actual = wintypes.ULONG()
        if not get_pid(handle, ctypes.byref(actual)):
            raise OSError(ctypes.get_last_error(), "cannot verify Biome pipe server PID")
        _assert_peer_pid(actual.value, expected_pid)
        fd = msvcrt_open_osfhandle(handle)
        handle = invalid
        return os.fdopen(fd, "r+b", buffering=0)
    finally:
        if handle != invalid:
            close(handle)


def msvcrt_open_osfhandle(handle: int) -> int:
    import msvcrt
    return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)


class OwnedBiomeDaemon:
    """One owned foreground server; each bounded call gets a verified LSP session."""

    def __init__(self, executable: str):
        self.executable = executable
        self._lock = threading.Lock()
        self._proc: Any = None
        self._version: str | None = None
        self._closed = False
        self._call_lock = threading.Lock()
        self._sessions: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._drainers: list[threading.Thread] = []

    @staticmethod
    def supported_here() -> bool:
        return os.name == "nt"

    def _capture_version(self, deadline: float) -> str:
        proc = popen_managed([self.executable, "--version"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        output = bytearray()
        errors: list[BaseException] = []

        def drain(stream: Any, target: bytearray | None) -> None:
            try:
                while True:
                    chunk = stream.read(1024)
                    if not chunk:
                        break
                    if target is not None and len(target) < _MAX_CAPTURE:
                        target.extend(chunk[:_MAX_CAPTURE - len(target)])
            except BaseException as exc:
                errors.append(exc)

        out = threading.Thread(target=drain, args=(proc.stdout, output), daemon=True)
        err = threading.Thread(target=drain, args=(proc.stderr, None), daemon=True)
        out.start(); err.start()
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if proc.poll() is None:
            terminate_tree(proc.pid, grace_seconds=0.2, process_handle=proc)
            raise TimeoutError("Biome version capture timed out")
        out.join(0.2); err.join(0.2)
        if proc.returncode != 0 or errors or out.is_alive() or err.is_alive():
            raise BiomeOwnershipError("Biome version could not be captured cleanly")
        match = _VERSION.fullmatch(output.decode("utf-8", errors="strict").strip())
        if not match:
            raise BiomeOwnershipError("unsupported Biome version or protocol")
        return match.group(1)

    def _ensure_server(self, deadline: float) -> tuple[Any, str]:
        if not self.supported_here():
            raise BiomeOwnershipError("owned Biome IPC is unavailable on this platform")
        with self._lock:
            if self._closed:
                raise BiomeOwnershipError("owned Biome daemon is closed")
            if self._proc is not None:
                if self._proc.poll() is not None:
                    raise BiomeOwnershipError("owned Biome server exited")
                return self._proc, self._version or ""
            version = self._capture_version(deadline)
            # Hidden foreground entry point, never the proxy/auto-start path.
            proc = popen_managed([self.executable, "__run_server"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            self._proc, self._version = proc, version
            for stream in (proc.stdout, proc.stderr):
                reader = threading.Thread(target=self._drain, args=(stream,), daemon=True)
                self._drainers.append(reader)
                reader.start()
            return proc, version

    @staticmethod
    def _drain(stream: Any) -> None:
        try:
            while stream.read(4096):
                pass
        except Exception:
            pass

    def _send(self, pipe: Any, message: dict[str, Any]) -> None:
        if self._proc is None or self._proc.poll() is not None:
            raise BiomeOwnershipError("owned Biome server exited before LSP write")
        pipe.write(_frame(message))
        pipe.flush()

    def has_session(self, tenant: str, root: str) -> bool:
        key = (tenant, os.path.normcase(str(Path(root).resolve(strict=False))))
        return key in self._sessions

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def diagnostics(self, tenant: str, root: str, paths: list[str], *, timeout: float,
                    should_stop: Callable[[], bool]) -> list[dict[str, Any]]:
        if not self._call_lock.acquire(timeout=max(0.1, min(120.0, float(timeout)))):
            raise TimeoutError("Biome LSP session is busy")
        try:
            return self._diagnostics_locked(tenant, root, paths, timeout=timeout, should_stop=should_stop)
        finally:
            self._call_lock.release()

    def _diagnostics_locked(self, tenant: str, root: str, paths: list[str], *, timeout: float,
                            should_stop: Callable[[], bool]) -> list[dict[str, Any]]:
        if not paths or len(paths) > 64:
            raise ValueError("Biome daemon accepts 1-64 files")
        deadline = time.monotonic() + max(0.1, min(120.0, float(timeout)))
        proc, version = self._ensure_server(deadline)
        if should_stop() or time.monotonic() >= deadline:
            raise TimeoutError("Biome LSP request cancelled or timed out")
        session_key = (tenant, os.path.normcase(str(Path(root).resolve(strict=True))))
        session = self._sessions.get(session_key)
        if session is None:
            pipe_name = rf"\\.\pipe\biome-service-{version}"
            pipe = None
            while pipe is None and time.monotonic() < deadline and not should_stop():
                if proc.poll() is not None:
                    raise BiomeOwnershipError("owned Biome foreground server exited during startup")
                try:
                    pipe = _windows_pipe(pipe_name, proc.pid)  # PID check precedes first protocol write
                except OSError:
                    time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
            if pipe is None:
                raise BiomeOwnershipError("owned Biome protocol endpoint did not become available")
            incoming: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=128)
            stop_reader = threading.Event()
            session = {"pipe": pipe, "incoming": incoming, "stop": stop_reader,
                       "deferred": deque(maxlen=128), "seq": 0, "documents": OrderedDict(),
                       "reader": None, "last_used": time.monotonic()}

            def read_loop() -> None:
                try:
                    while not stop_reader.is_set():
                        message = _read(pipe)
                        if message is None:
                            break
                        incoming.put(message, timeout=0.2)
                except Exception:
                    pass
                finally:
                    try:
                        incoming.put_nowait(None)
                    except queue.Full:
                        pass

            reader = threading.Thread(target=read_loop, daemon=True)
            session["reader"] = reader
            self._sessions[session_key] = session
            reader.start()

        pipe = session["pipe"]
        incoming = session["incoming"]
        deferred = session["deferred"]
        def receive() -> dict[str, Any] | None:
            if deferred:
                return deferred.popleft()
            try:
                return incoming.get(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
            except queue.Empty:
                return {}

        def request(method: str, params: dict[str, Any]) -> Any:
            session["seq"] += 1
            ident = session["seq"]
            self._send(pipe, {"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            while time.monotonic() < deadline and not should_stop():
                message = receive()
                if message == {}:
                    continue
                if message is None:
                    raise EOFError("Biome LSP disconnected")
                if message.get("method") == "workspace/configuration" and "id" in message:
                    items = (message.get("params") or {}).get("items", [])
                    self._send(pipe, {"jsonrpc": "2.0", "id": message["id"], "result": [None] * min(16, len(items))})
                elif message.get("method") == "workspace/applyEdit" and "id" in message:
                    self._send(pipe, {"jsonrpc": "2.0", "id": message["id"], "result": {"applied": False}})
                elif "id" in message and "method" in message:
                    self._send(pipe, {"jsonrpc": "2.0", "id": message["id"], "result": None})
                elif message.get("id") == ident:
                    if "error" in message:
                        raise BiomeOwnershipError("Biome rejected LSP request")
                    return message.get("result")
                else:
                    if len(deferred) == deferred.maxlen:
                        raise ValueError("Biome notification queue limit exceeded")
                    deferred.append(message)
            raise TimeoutError("Biome LSP request timed out or cancelled")

        try:
            if not session.get("initialized"):
                request("initialize", {"processId": os.getpid(), "rootUri": Path(root).resolve().as_uri(),
                                        "capabilities": {"workspace": {"configuration": True},
                                                         "textDocument": {"publishDiagnostics": {"relatedInformation": True}}}})
                self._send(pipe, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
                session["initialized"] = True
            diagnostics: list[dict[str, Any]] = []
            versions: dict[str, int] = {}
            original_paths: dict[str, str] = {}
            total_bytes = 0
            for path in paths:
                absolute = str(Path(path).resolve(strict=True))
                root_path = Path(root).resolve(strict=True)
                if not Path(absolute).is_relative_to(root_path):
                    raise ValueError("Biome LSP path escapes project root")
                size = Path(absolute).stat().st_size
                total_bytes += size
                if size > 2_000_000 or total_bytes > 8_000_000:
                    raise ValueError("Biome LSP file exceeds 2 MB")
                uri = Path(absolute).as_uri()
                old_document = session["documents"].get(uri)
                version_num = (old_document["version"] + 1) if old_document else 1
                versions[uri] = version_num
                original_paths[uri] = path
                session["documents"][uri] = {"version": version_num, "path": path,
                                              "language_id": None, "last_used": time.monotonic()}
                text = Path(absolute).read_text(encoding="utf-8")
                language_id = {".json": "json", ".jsonc": "jsonc", ".js": "javascript",
                               ".jsx": "javascriptreact", ".mjs": "javascript", ".cjs": "javascript",
                               ".ts": "typescript", ".tsx": "typescriptreact", ".mts": "typescript",
                               ".cts": "typescript"}.get(Path(absolute).suffix.lower())
                if language_id is None:
                    raise ValueError("unsupported Biome document type")
                session["documents"][uri]["language_id"] = language_id
                if old_document is None:
                    self._send(pipe, {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                        "textDocument": {"uri": uri, "languageId": language_id, "version": version_num, "text": text}}})
                else:
                    self._send(pipe, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                        "textDocument": {"uri": uri, "version": version_num},
                        "contentChanges": [{"text": text}]}})
                session["documents"].move_to_end(uri)
            while len(session["documents"]) > 64:
                evicted_uri, _ = session["documents"].popitem(last=False)
                if self._proc is None or self._proc.poll() is not None:
                    raise BiomeOwnershipError("owned Biome server exited before document close")
                self._send(pipe, {"jsonrpc": "2.0", "method": "textDocument/didClose",
                                  "params": {"textDocument": {"uri": evicted_uri}}})
            pending = set(versions)
            while pending and time.monotonic() < deadline and not should_stop():
                message = receive()
                if message == {}:
                    continue
                if message is None:
                    raise EOFError("Biome LSP disconnected before diagnostics")
                method = message.get("method")
                if method == "workspace/configuration" and "id" in message:
                    items = (message.get("params") or {}).get("items", [])
                    self._send(pipe, {"jsonrpc": "2.0", "id": message["id"], "result": [None] * min(16, len(items))})
                elif method == "workspace/applyEdit" and "id" in message:
                    self._send(pipe, {"jsonrpc": "2.0", "id": message["id"], "result": {"applied": False}})
                elif "id" in message and method:
                    self._send(pipe, {"jsonrpc": "2.0", "id": message["id"], "result": None})
                elif method == "textDocument/publishDiagnostics":
                    params = message.get("params") or {}
                    uri = params.get("uri")
                    if uri in pending and params.get("version") == versions[uri]:
                        pending.remove(uri)
                        for item in params.get("diagnostics", [])[:512]:
                            if len(diagnostics) >= 512:
                                raise ValueError("Biome diagnostic budget exceeded")
                            diagnostics.append({"path": original_paths[uri], "message": str(item.get("message", ""))[:1000],
                                                "code": str(item.get("code", ""))[:100],
                                                "severity": item.get("severity"), "range": item.get("range")})
            if pending:
                raise TimeoutError("Biome did not publish terminal diagnostics for every opened file")
            session["last_used"] = time.monotonic()
            return diagnostics
        except Exception:
            self._close_session(session_key)
            raise

    def _close_session(self, key: tuple[str, str]) -> None:
        session = self._sessions.pop(key, None)
        if not session:
            return
        session["stop"].set()
        try:
            session["pipe"].close()
        except Exception:
            pass
        session["reader"].join(0.2)

    def prune_sessions(self, idle_ttl: float) -> None:
        cutoff = time.monotonic() - idle_ttl
        for key, session in list(self._sessions.items()):
            if session["last_used"] <= cutoff:
                self._close_session(key)

    def close(self) -> bool:
        with self._lock:
            self._closed = True
            proc = self._proc
            self._proc = None
        for key in list(self._sessions):
            self._close_session(key)
        if proc is None:
            return True
        try:
            terminated = bool(terminate_tree(proc.pid, grace_seconds=0.5, process_handle=proc))
            proc.wait(timeout=1.0)
            for reader in self._drainers:
                reader.join(0.2)
            return terminated and proc.poll() is not None and not any(reader.is_alive() for reader in self._drainers)
        except Exception:
            return False

