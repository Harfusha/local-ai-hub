"""Windows-only, process-owned Biome LSP transport.

Biome's public proxy attaches to a shared version-named server.  This module
starts the foreground server itself and verifies every pipe peer before LSP
traffic.  Unsupported transports fail closed.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import re
import stat
import subprocess
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any, Callable

from .process_utils import _release_process_job, popen_managed, terminate_tree

_MAX_FRAME = 2_100_000
_MAX_INBOUND_FRAME = 256_000
_INBOUND_QUEUE_SIZE = 4
_INBOUND_SESSION_QUEUE_BUDGET = 2 * _INBOUND_QUEUE_SIZE * _MAX_INBOUND_FRAME
_MAX_CAPTURE = 8192
# This implementation is grounded to the currently reviewed upstream protocol
# source and release only.  Any other installed version fails before server IPC.
_VERSION = re.compile(r"^Version: (2\.5\.15)$")


class BiomeOwnershipError(RuntimeError):
    pass


def _assert_peer_pid(actual_pid: int, expected_pid: int) -> None:
    if actual_pid != expected_pid:
        raise BiomeOwnershipError("Biome pipe belongs to a different process")


def _valid_range(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for point in (value.get("start"), value.get("end")):
        if not isinstance(point, dict):
            return False
        for name in ("line", "character"):
            number = point.get(name)
            if not isinstance(number, int) or isinstance(number, bool) or number < 0 or number > 2_000_000:
                return False
    return True


def _normalize_diagnostics(items: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(items, list) or len(items) > 512:
        raise ValueError("Biome diagnostics are malformed or exceed the response budget")
    normalized = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("message"), str):
            raise ValueError("Biome returned a malformed diagnostic")
        severity = item.get("severity")
        if severity is not None and (not isinstance(severity, int) or isinstance(severity, bool) or severity not in {1, 2, 3, 4}):
            raise ValueError("Biome returned an invalid diagnostic severity")
        code = item.get("code")
        if code is not None and (not isinstance(code, (str, int)) or isinstance(code, bool)):
            raise ValueError("Biome returned an invalid diagnostic code")
        location = item.get("range")
        if location is not None and not _valid_range(location):
            raise ValueError("Biome returned an invalid diagnostic range")
        normalized.append({"path": path, "message": item["message"][:1000],
                           "code": str(code or "")[:100], "severity": severity, "range": location})
    return normalized


def _frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if not body or len(body) > _MAX_FRAME:
        raise ValueError("Biome LSP frame limit exceeded")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def _read(stream: Any, *, max_frame: int = _MAX_FRAME) -> dict[str, Any] | None:
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
    if length is None or not 0 < length <= max_frame:
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


def _read_source_snapshot(candidate: Path, root: Path) -> tuple[Path, str]:
    target = candidate.resolve(strict=True)
    target.relative_to(root)
    if not target.is_file():
        raise ValueError("Biome source path must name a regular file")
    path_before = target.stat()
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(target, flags)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 2_000_000:
            raise ValueError("Biome source must be a regular file within the 2 MB source budget bound")
        data = source.read(2_000_001)
        after = os.fstat(source.fileno())
    if len(data) > 2_000_000 or b"\x00" in data:
        raise ValueError("Biome source is binary or exceeds the 2 MB source budget bound")
    current_target = candidate.resolve(strict=True)
    current_target.relative_to(root)
    current = current_target.stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    same_file_identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if (
        current_target != target
        or identity(path_before) != identity(current)
        or identity(before) != identity(after)
        or same_file_identity(path_before) != same_file_identity(before)
    ):
        raise ValueError("Biome source changed while reading")
    return target, data.decode("utf-8", errors="strict")


def _windows_pipe(path: str, expected_pid: int, *, deadline: float):
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
    wait_pipe = kernel.WaitNamedPipeW
    wait_pipe.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    wait_pipe.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    invalid = wintypes.HANDLE(-1).value
    remaining_ms = max(1, min(250, int((deadline - time.monotonic()) * 1000)))
    if time.monotonic() >= deadline or not wait_pipe(path, remaining_ms):
        raise OSError(ctypes.get_last_error(), "Biome named-pipe availability wait timed out")
    if time.monotonic() >= deadline:
        raise TimeoutError("Biome named-pipe connect deadline expired")
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


def _cancel_synchronous_io(thread: threading.Thread) -> bool:
    """Cancel one owned worker's blocking synchronous pipe operation."""
    if os.name != "nt" or thread.native_id is None or not thread.is_alive():
        return not thread.is_alive()
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_thread = kernel.OpenThread
    open_thread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_thread.restype = wintypes.HANDLE
    cancel = kernel.CancelSynchronousIo
    cancel.argtypes = (wintypes.HANDLE,)
    cancel.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = open_thread(0x0001, False, thread.native_id)  # THREAD_TERMINATE
    if not handle:
        return False
    try:
        return bool(cancel(handle))
    finally:
        close(handle)


class OwnedBiomeDaemon:
    """One owned foreground server; each bounded call gets a verified LSP session."""

    def __init__(self, executable: str):
        self.executable = executable
        self._lock = threading.Lock()
        self._proc: Any = None
        self._version_proc: Any = None
        self._version_readers: tuple[threading.Thread, ...] = ()
        self._version: str | None = None
        self._closed = False
        self._call_lock = threading.Lock()
        self._sessions: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._drainers: list[threading.Thread] = []
        self._workers: list[threading.Thread] = []

    @staticmethod
    def supported_here() -> bool:
        return os.name == "nt"

    def _finish_version_capture(self, proc: Any, readers: tuple[threading.Thread, ...], deadline: float) -> bool:
        for reader in readers:
            reader.join(min(0.1, max(0.0, deadline - time.monotonic())))
        if any(reader.is_alive() for reader in readers):
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except Exception:
                    pass
            for reader in readers:
                reader.join(min(0.1, max(0.0, deadline - time.monotonic())))
        if proc.poll() is None or any(reader.is_alive() for reader in readers):
            return False
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass
        if not _release_process_job(proc):
            return False
        self._version_proc = None
        self._version_readers = ()
        return True

    def _capture_version(self, deadline: float) -> str:
        proc = popen_managed([self.executable, "--version"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self._version_proc = proc
        output = bytearray()
        errors: list[BaseException] = []
        truncated = threading.Event()

        def drain(stream: Any, target: bytearray | None) -> None:
            try:
                while True:
                    chunk = stream.read(1024)
                    if not chunk:
                        break
                    if target is not None:
                        room = _MAX_CAPTURE - len(target)
                        target.extend(chunk[:room])
                        if len(chunk) > room:
                            truncated.set()
            except BaseException as exc:
                errors.append(exc)

        out = threading.Thread(target=drain, args=(proc.stdout, output), daemon=True)
        err = threading.Thread(target=drain, args=(proc.stderr, None), daemon=True)
        self._version_readers = (out, err)
        out.start(); err.start()
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        timed_out = proc.poll() is None
        if timed_out:
            terminate_tree(proc.pid, grace_seconds=min(0.2, max(0.0, deadline - time.monotonic())), process_handle=proc)
        else:
            # A completed CLI may have left descendants holding inherited pipes.
            # Releasing its owned Job Object closes those handles before draining.
            _release_process_job(proc)
        cleanup_ok = self._finish_version_capture(proc, (out, err), deadline)
        if not cleanup_ok:
            raise BiomeOwnershipError("Biome version process cleanup is unconfirmed")
        if timed_out:
            raise TimeoutError("Biome version capture timed out")
        if proc.returncode != 0 or errors or truncated.is_set():
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
            if time.monotonic() >= deadline:
                raise TimeoutError("Biome startup deadline expired")
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
        session = next((item for item in self._sessions.values() if item["pipe"] is pipe), None)
        if session is None:
            raise BiomeOwnershipError("Biome LSP pipe has no owned session")
        deadline = session["deadline"]
        remaining = deadline - time.monotonic()
        if remaining <= 0 or session["should_stop"]():
            raise TimeoutError("Biome LSP write cancelled or timed out")
        done = threading.Event()
        errors: list[BaseException] = []
        try:
            session["writes"].put((_frame(message), done, errors), timeout=min(0.05, remaining))
        except queue.Full as exc:
            raise TimeoutError("Biome LSP write queue is full") from exc
        while not done.wait(min(0.05, max(0.0, deadline - time.monotonic()))):
            if session["should_stop"]() or time.monotonic() >= deadline:
                raise TimeoutError("Biome LSP write timed out or cancelled")
        if errors:
            raise EOFError("Biome LSP write failed") from errors[0]

    def has_session(self, tenant: str, root: str) -> bool:
        key = (tenant, os.path.normcase(str(Path(root).resolve(strict=False))))
        return key in self._sessions

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def diagnostics(self, tenant: str, root: str, paths: list[str], *, deadline: float,
                    should_stop: Callable[[], bool]) -> list[dict[str, Any]]:
        if not self._call_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError("Biome LSP session is busy")
        try:
            return self._diagnostics_locked(tenant, root, paths, deadline=deadline, should_stop=should_stop)
        finally:
            self._call_lock.release()

    def _diagnostics_locked(self, tenant: str, root: str, paths: list[str], *, deadline: float,
                            should_stop: Callable[[], bool]) -> list[dict[str, Any]]:
        if not paths or len(paths) > 64:
            raise ValueError("Biome daemon accepts 1-64 files")
        if time.monotonic() >= deadline or should_stop():
            raise TimeoutError("Biome LSP request cancelled or timed out")
        proc, version = self._ensure_server(deadline)
        if should_stop() or time.monotonic() >= deadline:
            raise TimeoutError("Biome LSP request cancelled or timed out")
        session_key = (tenant, os.path.normcase(str(Path(root).resolve(strict=True))))
        session = self._sessions.get(session_key)
        if session is not None and session.get("retiring"):
            raise BiomeOwnershipError("Biome LSP session cleanup is pending or unconfirmed")
        if session is None:
            pipe_name = rf"\\.\pipe\biome-service-{version}"
            pipe = None
            while pipe is None and time.monotonic() < deadline and not should_stop():
                if proc.poll() is not None:
                    raise BiomeOwnershipError("owned Biome foreground server exited during startup")
                try:
                    pipe = _windows_pipe(pipe_name, proc.pid, deadline=deadline)  # PID check precedes first protocol write
                except OSError:
                    time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
            if pipe is None:
                raise BiomeOwnershipError("owned Biome protocol endpoint did not become available")
            incoming: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_INBOUND_QUEUE_SIZE)
            writes: queue.Queue[Any] = queue.Queue(maxsize=8)
            stop_reader = threading.Event()
            session = {"pipe": pipe, "incoming": incoming, "stop": stop_reader,
                       "writes": writes, "deferred": deque(maxlen=_INBOUND_QUEUE_SIZE), "seq": 0,
                       "documents": OrderedDict(), "reader": None, "writer": None,
                       "last_used": time.monotonic(), "deadline": deadline,
                       "should_stop": should_stop, "overflow": threading.Event(),
                       "write_failed": threading.Event()}

            def read_loop() -> None:
                try:
                    while not stop_reader.is_set():
                        message = _read(pipe, max_frame=_MAX_INBOUND_FRAME)
                        if message is None:
                            break
                        incoming.put(message, timeout=0.2)
                except queue.Full:
                    session["overflow"].set()
                except Exception:
                    pass
                finally:
                    try:
                        incoming.put_nowait(None)
                    except queue.Full:
                        session["overflow"].set()

            def write_loop() -> None:
                while not stop_reader.is_set():
                    try:
                        item = writes.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    data, done, errors = item
                    try:
                        view = memoryview(data)
                        while view:
                            if proc.poll() is not None or time.monotonic() >= session["deadline"] or session["should_stop"]():
                                raise TimeoutError("Biome LSP write cancelled or timed out")
                            count = pipe.write(view)
                            if not count:
                                raise EOFError("Biome LSP pipe closed during write")
                            view = view[count:]
                        pipe.flush()
                    except BaseException as exc:
                        errors.append(exc)
                        session["write_failed"].set()
                    finally:
                        done.set()

            reader = threading.Thread(target=read_loop, daemon=True)
            writer = threading.Thread(target=write_loop, daemon=True)
            session["reader"] = reader
            session["writer"] = writer
            self._sessions[session_key] = session
            reader.start()
            writer.start()
            self._workers.extend((reader, writer))
        else:
            session["deadline"] = deadline
            session["should_stop"] = should_stop

        pipe = session["pipe"]
        incoming = session["incoming"]
        deferred = session["deferred"]
        def receive() -> dict[str, Any] | None:
            if session["overflow"].is_set() or session["write_failed"].is_set():
                return None
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
                if session["overflow"].is_set() or session["write_failed"].is_set():
                    raise EOFError("Biome LSP transport worker failed")
                try:
                    message = incoming.get(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                except queue.Empty:
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
            diagnostics: list[dict[str, Any]] = []
            versions: dict[str, int] = {}
            original_paths: dict[str, str] = {}
            total_bytes = 0
            root_path = Path(root).resolve(strict=True)
            prepared: list[tuple[str, Path, str, str, str, int, dict[str, Any] | None]] = []
            for path in paths:
                candidate = Path(path).expanduser()
                if not candidate.is_absolute():
                    candidate = root_path / candidate
                target, text = _read_source_snapshot(candidate, root_path)
                source_size = len(text.encode("utf-8"))
                total_bytes += source_size
                if source_size > 2_000_000 or total_bytes > 8_000_000:
                    raise ValueError("Biome LSP source budget exceeded")
                absolute = str(target)
                uri = target.as_uri()
                old_document = session["documents"].get(uri)
                version_num = (old_document["version"] + 1) if old_document else 1
                language_id = {".json": "json", ".jsonc": "jsonc", ".js": "javascript",
                               ".jsx": "javascriptreact", ".mjs": "javascript", ".cjs": "javascript",
                               ".ts": "typescript", ".tsx": "typescriptreact", ".mts": "typescript",
                               ".cts": "typescript"}.get(Path(absolute).suffix.lower())
                if language_id is None:
                    raise ValueError("unsupported Biome document type")
                prepared.append((path, target, uri, text, language_id, version_num, old_document))
            if not session.get("initialized"):
                request("initialize", {"processId": os.getpid(), "rootUri": root_path.as_uri(),
                                        "capabilities": {"workspace": {"configuration": True},
                                                         "textDocument": {"publishDiagnostics": {"relatedInformation": True}}}})
                self._send(pipe, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
                session["initialized"] = True
            for path, target, uri, text, language_id, version_num, old_document in prepared:
                versions[uri] = version_num
                original_paths[uri] = path
                session["documents"][uri] = {"version": version_num, "path": path,
                                              "language_id": language_id, "last_used": time.monotonic()}
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
                    version = params.get("version")
                    if uri in pending and isinstance(version, int) and not isinstance(version, bool) and version == versions[uri]:
                        pending.remove(uri)
                        items = params.get("diagnostics")
                        normalized = _normalize_diagnostics(items, original_paths[uri])
                        if len(normalized) > 512 - len(diagnostics):
                            raise ValueError("Biome diagnostic budget exceeded; response is incomplete")
                        diagnostics.extend(normalized)
            if pending:
                raise TimeoutError("Biome did not publish terminal diagnostics for every opened file")
            session["last_used"] = time.monotonic()
            return diagnostics
        except Exception:
            self._close_session(session_key, deadline=deadline)
            raise

    def _close_session(self, key: tuple[str, str], *, deadline: float | None = None) -> bool:
        session = self._sessions.get(key)
        if not session:
            return True
        session["retiring"] = True
        session["stop"].set()
        for worker in (session["reader"], session["writer"]):
            try:
                _cancel_synchronous_io(worker)
            except Exception:
                pass
        try:
            session["writes"].put_nowait(None)
        except queue.Full:
            pass
        try:
            session["pipe"].close()
        except Exception:
            pass
        cleanup_deadline = time.monotonic() + 0.25 if deadline is None else deadline
        remaining = max(0.0, cleanup_deadline - time.monotonic())
        session["reader"].join(min(0.2, remaining))
        session["writer"].join(min(0.2, remaining))
        confirmed = not session["reader"].is_alive() and not session["writer"].is_alive()
        if confirmed:
            del self._sessions[key]
            self._workers = [worker for worker in self._workers if worker.is_alive()]
        return confirmed

    def prune_sessions(self, idle_ttl: float, *, deadline: float) -> None:
        cutoff = time.monotonic() - idle_ttl
        for key, session in list(self._sessions.items()):
            if session["last_used"] <= cutoff:
                self._close_session(key, deadline=deadline)

    def close(self, *, deadline: float | None = None) -> bool:
        with self._lock:
            self._closed = True
            proc = self._proc
            version_proc = self._version_proc
        sessions_closed = True
        for key in list(self._sessions):
            sessions_closed = self._close_session(key, deadline=deadline) and sessions_closed
        confirmed = sessions_closed and not self._sessions
        for child in (proc, version_proc):
            if child is None:
                continue
            child_confirmed = False
            try:
                remaining = max(0.0, deadline - time.monotonic()) if deadline is not None else 1.0
                terminated = bool(terminate_tree(child.pid, grace_seconds=min(0.5, remaining), process_handle=child))
                child.wait(timeout=min(1.0, max(0.0, deadline - time.monotonic()) if deadline is not None else 1.0))
                child_confirmed = terminated and child.poll() is not None
            except Exception:
                child_confirmed = False
            finally:
                readers = self._version_readers if child is version_proc else tuple(self._drainers)
                for stream in (getattr(child, "stdout", None), getattr(child, "stderr", None)):
                    if stream is None:
                        continue
                    try:
                        stream.close()
                    except Exception:
                        pass
                for reader in readers:
                    try:
                        reader.join(min(0.2, max(0.0, deadline - time.monotonic()) if deadline is not None else 0.2))
                    except Exception:
                        pass
                child_confirmed = (child_confirmed and child.poll() is not None
                                   and not any(r.is_alive() for r in readers)
                                   and _release_process_job(child))
            confirmed = child_confirmed and confirmed
            if child_confirmed:
                if child is version_proc:
                    self._version_proc = None
                    self._version_readers = ()
                else:
                    self._proc = None
        for worker in self._workers:
            try:
                _cancel_synchronous_io(worker)
            except Exception:
                pass
            worker.join(min(0.2, max(0.0, deadline - time.monotonic()) if deadline is not None else 0.2))
        sessions_closed = not self._sessions and not any(worker.is_alive() for worker in self._workers)
        return confirmed and sessions_closed

