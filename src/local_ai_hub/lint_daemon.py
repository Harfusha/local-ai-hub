"""Persistent, read-only Ruff LSP transport with generation-owned bounded pipes."""
from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any, Callable

from .external_tools import MCPStdioClient
from .process_utils import popen_managed, terminate_tree

_MAX_FRAME = 4_000_000


class LintDaemonAdmissionTimeout(TimeoutError):
    """This caller never owned the session, so must not terminate another call."""


def read_lsp_message(stream: Any) -> dict[str, Any] | None:
    length = None
    for _ in range(16):
        line = stream.readline(2049)
        if not line:
            return None
        if len(line) > 2048 or not line.endswith(b"\n"):
            raise ValueError("invalid LSP header")
        if line in {b"\r\n", b"\n"}:
            break
        name, separator, value = line.partition(b":")
        if separator and name.lower() == b"content-length":
            if length is not None:
                raise ValueError("duplicate LSP content length")
            length = int(value.strip())
    else:
        raise ValueError("LSP header limit exceeded")
    if length is None or not 0 < length <= _MAX_FRAME:
        raise ValueError("LSP frame limit exceeded")
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            raise EOFError("incomplete LSP frame")
        data.extend(chunk)
    message = json.loads(data)
    if not isinstance(message, dict):
        raise ValueError("LSP message must be an object")
    return message


class RuffLintDaemon:
    def __init__(self, executable: str, root: str):
        self.executable = executable
        self.root = Path(root).resolve(strict=True)
        self._lock = threading.Lock()
        self._process_guard = threading.Lock()
        self._closed = False
        self._cleanup_pending = threading.Event()
        self._cleanup_done = threading.Event()
        self._cleanup_done.set()
        self._cleanup_failed = False
        self._proc: Any = None
        self._readers: tuple[threading.Thread, ...] = ()
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
        self._writes: queue.Queue[Any] = queue.Queue(maxsize=16)
        self._stop = threading.Event()
        self._stderr: deque[str] = deque(maxlen=16)
        self._sequence = 0
        self._documents: OrderedDict[str, int] = OrderedDict()

    def _detach(self) -> None:
        with self._process_guard:
            proc, readers, responses, stderr = self._proc, self._readers, self._responses, self._stderr
            self._proc = None
            self._readers = ()
            self._stop.set()
            self._documents.clear()
            if proc is not None:
                self._cleanup_pending.set()
                self._cleanup_done.clear()
        if proc is not None:
            # Cleanup operates on held process handles and old-generation buffers.
            def reap() -> None:
                confirmed = False
                try:
                    confirmed = bool(terminate_tree(proc.pid, grace_seconds=0.5, process_handle=proc))
                    MCPStdioClient._cleanup_process(proc, readers, responses, stderr)
                    confirmed = confirmed and proc.poll() is not None and not any(reader.is_alive() for reader in readers)
                except Exception:
                    confirmed = False
                finally:
                    with self._process_guard:
                        self._cleanup_failed = not confirmed
                        self._cleanup_pending.clear()
                        self._cleanup_done.set()
            threading.Thread(target=reap, name="lint-daemon-reaper", daemon=True).start()

    def close(self) -> None:
        with self._process_guard:
            self._closed = True
        self._detach()

    def cleanup_confirmed(self, timeout: float = 0.0) -> bool:
        self._cleanup_done.wait(max(0.0, min(1.0, timeout)))
        with self._process_guard:
            return not self._cleanup_pending.is_set() and not self._cleanup_failed

    def idle(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self._lock.release()
        return True

    def _spawn(self, deadline: float, should_stop: Callable[[], bool]) -> None:
        with self._process_guard:
            if self._closed:
                raise RuntimeError("lint daemon is closed")
            if self._cleanup_pending.is_set() or self._cleanup_failed:
                raise RuntimeError("lint daemon cleanup is pending or unconfirmed")
            if self._proc is not None and self._proc.poll() is None:
                return
            if self._proc is not None:
                raise RuntimeError("lint daemon process exited")
            if should_stop() or time.monotonic() >= deadline:
                raise TimeoutError("lint daemon startup cancelled or timed out")
            responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
            writes: queue.Queue[Any] = queue.Queue(maxsize=16)
            stopped = threading.Event()
            stderr: deque[str] = deque(maxlen=16)
            proc = popen_managed([self.executable, "server"], cwd=str(self.root),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            self._proc, self._responses, self._writes, self._stop, self._stderr = proc, responses, writes, stopped, stderr

            def write_loop() -> None:
                while not stopped.is_set():
                    try:
                        data, done, errors = writes.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    try:
                        view = memoryview(data)
                        while view:
                            written = proc.stdin.write(view)
                            if not written:
                                raise EOFError("lint stdin closed")
                            view = view[written:]
                        proc.stdin.flush()
                    except Exception as exc:
                        errors.append(type(exc).__name__)
                        stopped.set()
                    finally:
                        done.set()
                        writes.task_done()

            def read_loop() -> None:
                try:
                    while not stopped.is_set():
                        item = read_lsp_message(proc.stdout)
                        if item is None:
                            break
                        if "method" in item:
                            if "id" in item:
                                method = item.get("method")
                                if method == "workspace/configuration":
                                    requested = (item.get("params") or {}).get("items", [])
                                    result: Any = [None] * min(16, len(requested)) if isinstance(requested, list) else []
                                elif method == "workspace/applyEdit":
                                    result = {"applied": False, "failureReason": "read-only lint client"}
                                else:
                                    result = None
                                self._enqueue(writes, {"jsonrpc": "2.0", "id": item["id"], "result": result})
                            continue
                        if "id" in item:
                            responses.put_nowait(item)
                except Exception:
                    pass
                finally:
                    stopped.set()

            def stderr_loop() -> None:
                try:
                    while not stopped.is_set():
                        chunk = proc.stderr.read(4096)
                        if not chunk:
                            break
                        stderr.append(chunk[-1000:].decode("utf-8", errors="replace"))
                except Exception:
                    pass

            readers = tuple(threading.Thread(target=operation, name=name, daemon=True) for operation, name in (
                (write_loop, "lint-stdin"), (read_loop, "lint-stdout"), (stderr_loop, "lint-stderr"),
            ))
            self._readers = readers
            for reader in readers:
                reader.start()
        initialized = self._request("initialize", {
            "processId": os.getpid(), "rootUri": self.root.as_uri(),
            "workspaceFolders": [{"uri": self.root.as_uri(), "name": self.root.name}],
            "capabilities": {"textDocument": {"diagnostic": {"dynamicRegistration": False}},
                             "workspace": {"configuration": True, "applyEdit": False}},
        }, deadline, should_stop)
        if not isinstance(initialized, dict) or not (initialized.get("capabilities") or {}).get("diagnosticProvider"):
            raise RuntimeError("Ruff server does not advertise pull diagnostics")
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}}, deadline, should_stop)

    @staticmethod
    def _enqueue(writes: queue.Queue[Any], message: dict[str, Any]) -> tuple[threading.Event, list[str]]:
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_FRAME:
            raise ValueError("outgoing LSP frame limit exceeded")
        done, errors = threading.Event(), []
        writes.put_nowait((f"Content-Length: {len(body)}\r\n\r\n".encode() + body, done, errors))
        return done, errors

    def _wait(self, ready: threading.Event, deadline: float, should_stop: Callable[[], bool]) -> None:
        while not ready.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or should_stop() or self._stop.is_set():
                raise TimeoutError("lint daemon request cancelled or timed out")
            ready.wait(min(0.1, remaining))

    def _send(self, message: dict[str, Any], deadline: float, should_stop: Callable[[], bool]) -> None:
        done, errors = self._enqueue(self._writes, message)
        self._wait(done, deadline, should_stop)
        if errors:
            raise RuntimeError("lint daemon pipe write failed")

    def _request(self, method: str, params: dict[str, Any], deadline: float,
                 should_stop: Callable[[], bool]) -> Any:
        self._sequence += 1
        request_id = self._sequence
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, deadline, should_stop)
        while time.monotonic() < deadline and not should_stop() and not self._stop.is_set():
            try:
                item = self._responses.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if item.get("id") != request_id:
                continue
            if item.get("error"):
                raise RuntimeError("lint daemon returned a protocol error")
            return item.get("result")
        raise TimeoutError("lint daemon response cancelled or timed out")

    def diagnostics(self, paths: list[str], *, timeout: float = 30,
                    should_stop: Callable[[], bool] = lambda: False) -> list[dict[str, Any]]:
        deadline = time.monotonic() + max(0.05, min(120.0, float(timeout)))
        while not self._lock.acquire(timeout=min(0.1, max(0.001, deadline - time.monotonic()))):
            if time.monotonic() >= deadline or should_stop() or self._closed:
                raise LintDaemonAdmissionTimeout("lint daemon admission cancelled or timed out")
        output: list[dict[str, Any]] = []
        try:
            if not paths or len(paths) > 64:
                raise ValueError("lint daemon requires between 1 and 64 paths")
            self._spawn(deadline, should_stop)
            total_bytes = 0
            for path in paths:
                target = (self.root / path).resolve(strict=True)
                target.relative_to(self.root)
                if target.suffix.lower() != ".py":
                    raise ValueError("Ruff daemon accepts Python paths only")
                with target.open("rb") as handle:
                    raw = handle.read(2_000_001)
                total_bytes += len(raw)
                if len(raw) > 2_000_000 or total_bytes > 8_000_000:
                    raise ValueError("lint source budget exceeded")
                uri, text = target.as_uri(), raw.decode("utf-8", errors="replace")
                version = self._documents.get(uri, 0) + 1
                if uri in self._documents:
                    method, params = "textDocument/didChange", {"textDocument": {"uri": uri, "version": version},
                                                                "contentChanges": [{"text": text}]}
                else:
                    method, params = "textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "python",
                                                                              "version": version, "text": text}}
                self._send({"jsonrpc": "2.0", "method": method, "params": params}, deadline, should_stop)
                self._documents[uri] = version
                self._documents.move_to_end(uri)
                if len(self._documents) > 64:
                    old_uri, _version = self._documents.popitem(last=False)
                    self._send({"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {"textDocument": {"uri": old_uri}}}, deadline, should_stop)
                report = self._request("textDocument/diagnostic", {"textDocument": {"uri": uri}}, deadline, should_stop)
                if not isinstance(report, dict) or report.get("kind") != "full" or not isinstance(report.get("items"), list):
                    raise ValueError("invalid full diagnostic report")
                for diagnostic in report["items"]:
                    if not isinstance(diagnostic, dict):
                        raise ValueError("invalid diagnostic")
                    if len(output) >= 512:
                        raise ValueError("lint diagnostic budget exceeded")
                    output.append({"path": path, "message": str(diagnostic.get("message", ""))[:1000],
                                   "code": str(diagnostic.get("code", ""))[:100],
                                   "severity": diagnostic.get("severity"), "range": diagnostic.get("range")})
            return output
        except Exception:
            self._detach()
            raise
        finally:
            self._lock.release()


class RuffDaemonPool:
    """Bounded tenant/project sessions. Retiring processes retain their slot."""

    def __init__(self, *, max_sessions: int = 4, idle_ttl: float = 300.0):
        self.max_sessions = max(1, min(16, int(max_sessions)))
        self.idle_ttl = max(1.0, min(3600.0, float(idle_ttl)))
        self._lock = threading.Lock()
        self._closed = False
        self._sessions: dict[tuple[str, str], dict[str, Any]] = {}

    def run(self, executable: str, root: str, tenant: str, paths: list[str], *,
            timeout: float = 30, should_stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
        key = (tenant, os.path.normcase(str(Path(root).resolve(strict=True))))
        tick = time.monotonic()
        base = {"daemon_mode": True, "transport": "stdio_lsp", "read_only": True, "auto_fix": False}
        with self._lock:
            if self._closed:
                return {**base, "success": False, "error": "lint daemon pool is closed", "terminal": True, "retryable": False}
            for old_key, entry in list(self._sessions.items()):
                daemon = entry["daemon"]
                if entry["retiring"]:
                    if daemon.cleanup_confirmed():
                        del self._sessions[old_key]
                elif not entry["users"] and tick - entry["last_used"] >= self.idle_ttl:
                    entry["retiring"] = True
                    daemon.close()
                    if daemon.cleanup_confirmed():
                        del self._sessions[old_key]
            entry = self._sessions.get(key)
            if entry is not None and entry["retiring"]:
                return {**base, "success": False, "error": "lint session cleanup is pending", "terminal": True, "retryable": False}
            if entry is None:
                if len(self._sessions) >= self.max_sessions:
                    return {**base, "success": False, "error": "lint daemon session capacity reached", "terminal": True, "retryable": False}
                entry = {"daemon": RuffLintDaemon(executable, root), "last_used": tick, "users": 0, "retiring": False}
                self._sessions[key] = entry
            entry["users"] += 1
            daemon = entry["daemon"]
        try:
            diagnostics = daemon.diagnostics(paths, timeout=timeout, should_stop=should_stop)
            return {**base, "success": not diagnostics, "exit_code": 1 if diagnostics else 0,
                    "diagnostics": diagnostics, "diagnostic_count": len(diagnostics)}
        except LintDaemonAdmissionTimeout as exc:
            # Never terminate the other request that currently owns this session.
            return {**base, "success": False, "error": str(exc), "terminal": True, "retryable": False}
        except Exception as exc:
            confirmed = daemon.cleanup_confirmed(timeout=1.0)
            return {**base, "success": False, "error": str(exc)[:500], "terminal": True,
                    "retryable": False, "cleanup_unconfirmed": not confirmed, "outcome_unknown": not confirmed}
        finally:
            with self._lock:
                entry["users"] -= 1
                entry["last_used"] = time.monotonic()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            sessions = [entry["daemon"] for entry in self._sessions.values()]
        for daemon in sessions:
            daemon.close()


class OwnedBiomeDaemonPool:
    """Bounded pool of owned Biome foreground servers (Windows transport only)."""

    def __init__(self, *, max_sessions: int = 4, idle_ttl: float = 300.0):
        self.max_sessions = max(1, min(16, int(max_sessions)))
        self.idle_ttl = max(1.0, min(3600.0, float(idle_ttl)))
        self._lock = threading.Lock()
        self._closed = False
        self._servers: dict[str, dict[str, Any]] = {}

    def run(self, executable: str, root: str, tenant: str, paths: list[str], *,
            timeout: float = 30, should_stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
        from .biome_owned_ipc import BiomeOwnershipError, OwnedBiomeDaemon

        base = {"provider": "biome", "daemon_mode": True, "transport": "owned_foreground_lsp",
                "read_only": True, "auto_fix": False}
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            return {**base, "success": False, "error": "Biome timeout must be a positive finite number",
                    "terminal": True, "retryable": False}
        deadline = time.monotonic() + min(120.0, float(timeout))
        if not OwnedBiomeDaemon.supported_here():
            return {**base, "success": False, "unsupported": True,
                    "transport": "unsupported_unowned_platform", "terminal": True,
                    "retryable": False, "error": "owned Biome named-pipe transport is supported only on Windows"}
        key = os.path.normcase(str(Path(executable).resolve(strict=True)))
        now = time.monotonic()
        retiring: list[tuple[str, dict[str, Any]]] = []
        with self._lock:
            if self._closed:
                return {**base, "success": False, "error": "Biome daemon pool is closed", "terminal": True,
                        "retryable": False}
            for old_key, entry in list(self._servers.items()):
                if (not entry["busy"] and
                        (entry.get("retiring") or now - entry["last_used"] >= self.idle_ttl)):
                    entry["retiring"] = True
                    entry["busy"] = True
                    retiring.append((old_key, entry))
        for old_key, old_entry in retiring:
            confirmed = old_entry["daemon"].close(deadline=deadline)
            with self._lock:
                old_entry["busy"] = False
                if confirmed:
                    if self._servers.get(old_key) is old_entry:
                        del self._servers[old_key]
            if not confirmed:
                return {**base, "success": False, "error": "Biome daemon cleanup is pending or unconfirmed",
                        "cleanup_unconfirmed": True, "terminal": True, "retryable": False}
        with self._lock:
            entry = self._servers.get(key)
            if entry is not None and entry.get("retiring"):
                return {**base, "success": False, "error": "Biome daemon cleanup is pending or unconfirmed",
                        "cleanup_unconfirmed": True, "terminal": True, "retryable": False}
            if entry is None:
                if len(self._servers) >= self.max_sessions:
                    return {**base, "success": False, "error": "Biome daemon capacity reached", "terminal": True,
                            "retryable": False}
                entry = {"daemon": OwnedBiomeDaemon(key), "last_used": now, "busy": False, "retiring": False}
                self._servers[key] = entry
            if not entry["daemon"].has_session(tenant, root):
                current_sessions = sum(item["daemon"].session_count for item in self._servers.values())
                if current_sessions >= self.max_sessions:
                    if entry["daemon"].session_count == 0:
                        self._servers.pop(key, None)
                    return {**base, "success": False, "error": "Biome LSP session capacity reached",
                            "terminal": True, "retryable": False}
            if entry["busy"]:
                return {**base, "success": False, "error": "Biome daemon session is busy", "terminal": True,
                        "retryable": False}
            entry["busy"] = True
        try:
            entry["daemon"].prune_sessions(self.idle_ttl, deadline=deadline)
            diagnostics = entry["daemon"].diagnostics(tenant, root, paths, deadline=deadline, should_stop=should_stop)
            return {**base, "success": not diagnostics, "exit_code": 1 if diagnostics else 0,
                    "diagnostics": diagnostics, "diagnostic_count": len(diagnostics)}
        except BiomeOwnershipError as exc:
            confirmed = entry["daemon"].close(deadline=deadline)
            with self._lock:
                if confirmed:
                    self._servers.pop(key, None)
                else:
                    entry["retiring"] = True
            return {**base, "success": False, "unsupported": True, "terminal": True,
                    "retryable": False, "cleanup_unconfirmed": not confirmed,
                    "outcome_unknown": not confirmed, "error": str(exc)[:500]}
        except Exception as exc:
            confirmed = entry["daemon"].close(deadline=deadline)
            with self._lock:
                if confirmed:
                    self._servers.pop(key, None)
                else:
                    entry["retiring"] = True
            return {**base, "success": False, "terminal": True, "retryable": False,
                    "cleanup_unconfirmed": not confirmed, "outcome_unknown": not confirmed,
                    "error": str(exc)[:500]}
        finally:
            with self._lock:
                entry["busy"] = False
                entry["last_used"] = time.monotonic()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            servers = [entry["daemon"] for entry in self._servers.values()]
        for daemon in servers:
            daemon.close()
