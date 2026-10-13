from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import __version__
from .process_utils import hidden_run_kwargs, popen_managed, run_hidden, terminate_tree


class MCPStdioError(RuntimeError):
    pass


class MCPSoftTimeoutError(TimeoutError):
    """Soft query deadline expired without killing the underlying MCP process."""
    pass


class MCPStdioClient:
    """Small bounded stdio MCP client used only for managed local code-intelligence tools.

    It deliberately avoids importing an async MCP client into the hub runtime. Requests are
    serialized, every call is timeout-bounded, stderr is drained, and failed processes are
    discarded so an external tool cannot wedge the hub.
    """

    def __init__(self, command: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None, startup_timeout: float = 30.0, call_timeout: float = 30.0):
        if not command:
            raise ValueError("empty MCP command")
        self.command = [str(x) for x in command]
        self.cwd = cwd
        self.env = env
        self.startup_timeout = max(2.0, float(startup_timeout))
        self.call_timeout = max(1.0, float(call_timeout))
        self._proc: subprocess.Popen[str] | None = None
        # Queues/buffers are process-generation scoped. Reader threads capture these
        # exact objects so a late reader from an old process can never consume from or
        # inject into a freshly restarted JSON-RPC session.
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        self._stderr: deque[str] = deque(maxlen=80)
        self._reader_threads: tuple[threading.Thread, ...] = ()
        self._dropped_responses = 0
        self._stale_responses = 0
        self._lock = threading.RLock()
        self._next_id = 1
        self._tools: dict[str, dict[str, Any]] = {}
        self._closed = False

    def _spawn(self) -> None:
        if self._closed:
            raise MCPStdioError("MCP client is closed")
        if self._proc is not None and self._proc.poll() is None:
            return
        self._stop_process()
        kwargs: dict[str, Any] = hidden_run_kwargs(text=True, new_group=True)
        if os.name != "nt":
            kwargs["start_new_session"] = True
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update({str(k): str(v) for k, v in self.env.items()})
        # Managed Python MCP tools must emit Unicode diagnostics even when the
        # Windows process code page may use a locale-specific charmap (for example cp1252).
        merged_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        stderr_lines: deque[str] = deque(maxlen=80)
        try:
            proc = popen_managed(
                self.command,
                cwd=self.cwd,
                env=merged_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                **kwargs,
            )
        except Exception as exc:
            self._proc = None
            raise MCPStdioError(f"cannot start MCP server: {type(exc).__name__}: {exc}") from exc
        self._proc = proc
        self._responses = responses
        self._stderr = stderr_lines
        stdout_thread = threading.Thread(
            target=self._read_stdout, args=(proc, responses), name="local-ai-mcp-stdout", daemon=True
        )
        stderr_thread = threading.Thread(
            target=self._read_stderr, args=(proc, stderr_lines), name="local-ai-mcp-stderr", daemon=True
        )
        self._reader_threads = (stdout_thread, stderr_thread)
        stdout_thread.start()
        stderr_thread.start()
        try:
            init = self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "local-ai-hub", "version": __version__},
                },
                timeout=self.startup_timeout,
                ensure_started=False,
            )
            if not isinstance(init, dict):
                raise MCPStdioError("invalid MCP initialize result")
            self._notify("notifications/initialized", {})
            self._refresh_tools()
        except Exception:
            self._stop_process()
            raise

    def _read_stdout(self, proc: subprocess.Popen[str], responses: queue.Queue[dict[str, Any]]) -> None:
        if not proc.stdout:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict) and ("id" in item or "error" in item):
                    try:
                        responses.put_nowait(item)
                    except queue.Full:
                        # A broken MCP peer must not grow hub memory without bound.
                        # Drop the oldest unmatched response and keep the newest one,
                        # which is most likely to belong to the current serialized call.
                        try:
                            responses.get_nowait()
                        except queue.Empty:
                            pass
                        self._dropped_responses += 1
                        try:
                            responses.put_nowait(item)
                        except queue.Full:
                            self._dropped_responses += 1
        except Exception:
            return

    def _read_stderr(self, proc: subprocess.Popen[str], stderr_lines: deque[str]) -> None:
        if not proc.stderr:
            return
        try:
            for line in proc.stderr:
                value = line.rstrip()
                if value:
                    stderr_lines.append(value[-1000:])
        except Exception:
            return

    def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if not proc or proc.poll() is not None or not proc.stdin:
            raise MCPStdioError("MCP process is not running")
        try:
            proc.stdin.write(json_dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except Exception as exc:
            raise MCPStdioError(f"MCP write failed: {type(exc).__name__}") from exc

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any], *, timeout: float | None = None, soft_timeout: float | None = None, ensure_started: bool = True) -> Any:
        request_started = time.monotonic()
        hard_timeout = self.call_timeout if timeout is None else max(0.05, float(timeout))
        hard_deadline = request_started + hard_timeout
        soft_deadline = (request_started + max(0.05, float(soft_timeout))) if soft_timeout is not None else None
        effective_deadline = min(hard_deadline, soft_deadline) if soft_deadline is not None else hard_deadline
        if ensure_started:
            self._spawn()
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

        while time.monotonic() < effective_deadline:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                detail = " | ".join(list(self._stderr)[-3:])
                raise MCPStdioError(f"MCP process exited{': ' + detail if detail else ''}")
            try:
                item = self._responses.get(timeout=min(0.2, max(0.01, effective_deadline - time.monotonic())))
            except queue.Empty:
                continue
            resp_id = item.get("id")
            if resp_id != request_id:
                if resp_id is None and "error" in item:
                    raise MCPStdioError(f"MCP server error: {item.get('error')}")
                # Calls are serialized by the client lock, so a different id can only
                # be a stale/late response. Re-queueing it makes every later request
                # scan the same junk forever and lets a bad peer grow memory.
                self._stale_responses += 1
                continue
            if item.get("error"):
                raise MCPStdioError(f"MCP error: {item.get('error')}")
            return item.get("result")

        if soft_deadline is not None and time.monotonic() >= soft_deadline and time.monotonic() < hard_deadline:
            raise MCPSoftTimeoutError(f"MCP soft timeout: {method}")

        self._stop_process(deadline=hard_deadline)
        raise TimeoutError(f"MCP call timed out: {method}")

    def _refresh_tools(self) -> None:
        result = self._request("tools/list", {}, timeout=self.startup_timeout, ensure_started=False)
        tools = result.get("tools", []) if isinstance(result, dict) else []
        self._tools = {str(item.get("name")): item for item in tools if isinstance(item, dict) and item.get("name")}

    def tool_names(self) -> list[str]:
        with self._lock:
            self._spawn()
            if not self._tools:
                self._refresh_tools()
            return sorted(self._tools)

    @staticmethod
    def _schema_properties(tool: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        if not isinstance(schema, dict):
            return {}, set()
        props = schema.get("properties", {})
        required = schema.get("required", [])
        return (props if isinstance(props, dict) else {}, {str(x) for x in required if isinstance(x, str)})

    def call_tool(self, name: str, args: dict[str, Any], *, timeout: float | None = None, soft_timeout: float | None = None) -> dict[str, Any]:
        lock_wait = min(float(soft_timeout), 1.5) if soft_timeout is not None else (float(timeout) if timeout is not None else None)
        acquired = self._lock.acquire(timeout=lock_wait if lock_wait is not None else -1)
        if not acquired:
            raise MCPSoftTimeoutError(f"MCP lock wait timeout for tool: {name}")
        try:
            self._spawn()
            if name not in self._tools:
                self._refresh_tools()
            tool = self._tools.get(name)
            if tool is None:
                raise MCPStdioError(f"MCP tool not available: {name}")
            props, required = self._schema_properties(tool)
            filtered = {k: v for k, v in args.items() if v is not None and (not props or k in props)}
            missing = [k for k in required if k not in filtered]
            if missing:
                raise MCPStdioError(f"missing required args for {name}: {', '.join(missing)}")
            result = self._request("tools/call", {"name": name, "arguments": filtered}, timeout=timeout, soft_timeout=soft_timeout)
            return self._normalize_tool_result(result)
        finally:
            self._lock.release()

    @staticmethod
    def _normalize_tool_result(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"success": True, "result": result}
        content = result.get("content")
        texts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text") is not None:
                    texts.append(str(item.get("text")))
        structured = result.get("structuredContent")
        out: dict[str, Any] = {"success": not bool(result.get("isError", False))}
        if structured is not None:
            out["structured"] = structured
        if texts:
            joined = "\n".join(texts)
            try:
                parsed = json.loads(joined)
                out["result"] = parsed
            except Exception:
                out["text"] = joined
        if not texts and structured is None:
            out["result"] = {k: v for k, v in result.items() if k not in {"content", "structuredContent"}}
        return out

    def _stop_process(self, *, deadline: float | None = None) -> None:
        proc = self._proc
        responses = self._responses
        stderr_lines = self._stderr
        reader_threads = self._reader_threads
        self._proc = None
        self._tools = {}
        self._reader_threads = ()
        # Detach the public/current buffers before reaping. Any late old-generation
        # reader still owns only the captured objects above.
        self._responses = queue.Queue(maxsize=128)
        self._stderr = deque(maxlen=80)
        if not proc:
            return

        # A request timeout has no remaining budget for process-tree teardown.
        # Detach state now, then reap in the background so cleanup cannot extend
        # the caller's explicit deadline.
        if deadline is not None and time.monotonic() >= deadline:
            threading.Thread(
                target=self._cleanup_process,
                args=(proc, reader_threads, responses, stderr_lines),
                name="local-ai-mcp-reaper",
                daemon=True,
            ).start()
            return
        self._cleanup_process(proc, reader_threads, responses, stderr_lines)

    @staticmethod
    def _cleanup_process(
        proc: subprocess.Popen[str],
        reader_threads: tuple[threading.Thread, ...],
        responses: queue.Queue[dict[str, Any]],
        stderr_lines: deque[str],
    ) -> None:
        try:
            stdin = getattr(proc, "stdin", None)
            if stdin:
                stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            pid = getattr(proc, "pid", None)
            if isinstance(pid, int) and pid > 0:
                try:
                    terminate_tree(pid, grace_seconds=1.0, process_handle=proc)
                except Exception:
                    pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass
        # Popen does not guarantee pipe file objects are closed merely because
        # the child exited. Closing them also unblocks line-reader threads.
        for stream in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        for thread in reader_threads:
            try:
                if thread is not threading.current_thread():
                    thread.join(timeout=0.5)
            except Exception:
                pass
        while True:
            try:
                responses.get_nowait()
            except queue.Empty:
                break
        stderr_lines.clear()

    def reset(self) -> None:
        with self._lock:
            self._stop_process()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_process()

    def __enter__(self) -> "MCPStdioClient":
        if self._closed:
            raise MCPStdioError("MCP client is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class ExternalCodeIntelligence:
    """Manage Serena integration for preprocessing and local agents."""

    def __init__(self, config: dict[str, Any], telemetry: Any | None = None, code_index: Any | None = None):
        self.config = config
        self.telemetry = telemetry
        self.code_index = code_index
        self.cfg = config.get("code_intelligence", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.serena_enabled = self.enabled and bool(self.cfg.get("serena_enabled", True))
        configured_install_root = config.get("setup", {}).get("install_dir")
        self.install_root = (
            Path(configured_install_root).expanduser().resolve()
            if configured_install_root
            else Path(__file__).resolve().parents[2]
        )
        self.call_timeout = float(self.cfg.get("query_timeout_seconds", 60.0))
        self.soft_timeout = float(self.cfg.get("soft_timeout_seconds", 4.0))
        self.startup_timeout = float(self.cfg.get("startup_timeout_seconds", 60.0))
        self.index_timeout = float(self.cfg.get("index_timeout_seconds", 1200.0))
        self.max_output_chars = max(1000, int(self.cfg.get("max_output_chars", 9000)))
        self._lock = threading.RLock()
        self._operation_lock_guard = threading.Lock()
        self._operation_locks: dict[tuple[str, str], threading.Lock] = {}
        self._operation_lock_users: dict[tuple[str, str], int] = {}
        self._serena_sessions: dict[str, MCPStdioClient] = {}
        self.max_sessions = max(1, int(self.cfg.get("max_sessions_per_backend", 16)))
        self.session_idle_ttl = max(1.0, float(self.cfg.get("session_idle_ttl_seconds", 3600.0)))
        self._session_access: dict[str, dict[str, float]] = {"serena": {}}
        self._failures: dict[str, int] = {"serena": 0}
        self._cooldown_until: dict[str, float] = {"serena": 0.0}
        self._root_failures: dict[tuple[str, str], int] = {}
        self._root_cooldown_until: dict[tuple[str, str], float] = {}
        self._repair_locks = {"serena": threading.Lock()}
        self._backend_health: dict[str, dict[str, Any]] = {
            name: {
                "state": "disabled" if not getattr(self, f"{name}_enabled") else "unknown",
                "last_failure": "",
                "last_recovery": "",
                "last_successful_probe": "",
                "repair_attempts": 0,
                "last_repair_at": 0.0,
                "last_preflight_at": 0.0,
            }
            for name in ("serena",)
        }
        self.repair_timeout = min(300.0, max(10.0, float(self.cfg.get("repair_timeout_seconds", 120.0))))
        self.repair_cooldown = min(3600.0, max(30.0, float(self.cfg.get("repair_cooldown_seconds", 300.0))))
        self.failure_threshold = max(1, int(self.cfg.get("failure_threshold", 2)))
        self.cooldown_seconds = max(1.0, float(self.cfg.get("cooldown_seconds", 60.0)))
        self._serena = self._resolve_command("serena") if self.serena_enabled else None
        self.index_runs = 0
        self.index_failures = 0
        self.queries = 0
        self.query_failures = 0
        if self.enabled and self.serena_enabled:
            threading.Thread(target=self._startup_preflight, name="local-ai-code-intelligence-preflight", daemon=True).start()

    def _resolve_command(self, backend: str) -> str | None:
        if backend != "serena":
            return None
        explicit = str(self.cfg.get(f"{backend}_command", "") or "").strip()
        if explicit:
            parts = shlex.split(explicit, posix=os.name != "nt")
            candidate = os.path.expandvars(os.path.expanduser(parts[0].strip('"\''))) if parts else ""
            if candidate and (Path(candidate).exists() or shutil.which(candidate)):
                return str(Path(candidate).resolve()) if Path(candidate).exists() else str(shutil.which(candidate))
        suffix = ".exe" if os.name == "nt" else ""
        bindir = "Scripts" if os.name == "nt" else "bin"
        candidates = [
            self.install_root / "tool-envs" / "serena" / bindir / f"serena{suffix}",
        ]
        names = ["serena"]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        for name in names:
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return None

    def refresh_discovery(self) -> None:
        with self._lock:
            self._serena = self._resolve_command("serena") if self.serena_enabled else None

    @staticmethod
    def _git_ignored_directory_names(root: str) -> set[str]:
        """Return literal directory names Git already excludes from this worktree."""
        try:
            probe = subprocess.run(
                ["git", "-C", root, "rev-parse", "--show-toplevel"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2,
                **hidden_run_kwargs(),
            )
            if probe.returncode != 0:
                return set()
            raw_root = probe.stdout.decode("utf-8", "replace") if isinstance(probe.stdout, bytes) else str(probe.stdout or "")
            git_root = Path(raw_root.strip()).resolve()
        except (OSError, subprocess.SubprocessError, ValueError):
            return set()

        ignore_files = [git_root / ".gitignore", git_root / ".git" / "info" / "exclude"]
        try:
            listed = subprocess.run(
                ["git", "-C", root, "ls-files", "-z", "--", ".gitignore", "**/.gitignore"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
                **hidden_run_kwargs(),
            )
            raw_listed = listed.stdout.decode("utf-8", "replace") if isinstance(listed.stdout, bytes) else str(listed.stdout or "")
            ignore_files.extend(git_root / item for item in raw_listed.split("\0") if item)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

        names: set[str] = set()
        for ignore_file in dict.fromkeys(ignore_files):
            try:
                lines = ignore_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line in lines:
                pattern = line.strip()
                if not pattern or pattern.startswith("#") or pattern.startswith("!") or not pattern.endswith("/"):
                    continue
                normalized = pattern.rstrip("/").replace("\\", "/")
                name = normalized.rsplit("/", 1)[-1]
                is_global = "/" not in normalized.lstrip("/")
                if name and is_global and not any(char in name for char in "*?["):
                    names.add(name)
        return names

    def _prune_sessions_locked(self) -> list[MCPStdioClient]:
        """Remove idle/LRU project MCP processes while holding ``self._lock``."""
        sessions = self._serena_sessions
        access = self._session_access["serena"]
        now = time.monotonic()
        evicted: list[MCPStdioClient] = []
        for root, touched in list(access.items()):
            if root not in sessions:
                access.pop(root, None)
                continue
            if now - touched > self.session_idle_ttl:
                client = sessions.pop(root, None)
                access.pop(root, None)
                if client is not None:
                    evicted.append(client)
        while len(sessions) > self.max_sessions:
            root = min(sessions, key=lambda item: access.get(item, 0.0))
            client = sessions.pop(root)
            access.pop(root, None)
            evicted.append(client)
        return evicted

    def _touch_session_locked(self, root: str) -> list[MCPStdioClient]:
        self._session_access["serena"][root] = time.monotonic()
        return self._prune_sessions_locked()

    @contextmanager
    def _backend_operation(self, backend: str, root: str, timeout: float | None = None):
        """Serialize operations for one embedded database, with bounded lock wait."""
        if backend != "serena":
            raise ValueError(f"unknown code-intelligence backend: {backend}")
        key = (backend, root)
        with self._operation_lock_guard:
            operation_lock = self._operation_locks.get(key)
            if operation_lock is None:
                operation_lock = threading.Lock()
                self._operation_locks[key] = operation_lock
                self._operation_lock_users[key] = 0
            self._operation_lock_users[key] += 1
        wait_timeout = self.call_timeout if timeout is None else max(0.0, float(timeout))
        acquired = False
        try:
            acquired = operation_lock.acquire(timeout=wait_timeout)
            if not acquired:
                raise TimeoutError(f"Timed out waiting for {backend} operation lock")
            yield
        finally:
            if acquired:
                operation_lock.release()
            with self._operation_lock_guard:
                remaining = self._operation_lock_users[key] - 1
                if remaining:
                    self._operation_lock_users[key] = remaining
                else:
                    self._operation_lock_users.pop(key, None)
                    self._operation_locks.pop(key, None)

    @staticmethod
    def _close_clients(clients: list[MCPStdioClient]) -> None:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass

    def _allowed(self, backend: str, root: str | None = None) -> bool:
        if time.monotonic() < self._cooldown_until.get(backend, 0.0):
            return False
        return root is None or time.monotonic() >= self._root_cooldown_until.get((backend, root), 0.0)

    @staticmethod
    def _timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _record_success(self, backend: str, *, root: str | None = None, probe: bool = False) -> None:
        if root is not None:
            self._root_failures.pop((backend, root), None)
            self._root_cooldown_until.pop((backend, root), None)
        self._failures[backend] = sum(value for (name, _root), value in self._root_failures.items() if name == backend)
        self._cooldown_until[backend] = 0.0
        health = self._backend_health[backend]
        health["state"] = "healthy"
        health["last_successful_operation"] = self._timestamp()
        if probe:
            health["last_successful_probe"] = self._timestamp()
            health["last_probe_success"] = True
        health["failure_active"] = False
        health["repair_error"] = ""
        health["repair_blocked"] = ""

    @staticmethod
    def _is_revision_scoped_index_error(operation: str, message: str) -> bool:
        if operation != "index":
            return False
        lowered = message.lower()
        return any(marker in lowered for marker in (
            "no associated project configuration",
            "no configuration file found",
            "project configuration auto-generation failed",
            "project root is missing",
        ))

    def _record_failure(
        self,
        backend: str,
        exc: Exception,
        *,
        operation: str,
        root: str | None = None,
        emit_telemetry: bool = True,
    ) -> None:
        message = str(exc)
        health = self._backend_health[backend]
        key = (backend, root or "")
        if self._is_revision_scoped_index_error(operation, message):
            self._root_failures.pop(key, None)
            self._root_cooldown_until.pop(key, None)
            self._failures[backend] = sum(value for (name, _root), value in self._root_failures.items() if name == backend)
            if self.telemetry is not None:
                try:
                    self.telemetry.record_system(f"code_intelligence:{backend}:index_skipped", success=True, degraded=True)
                except Exception:
                    pass
            return
        health["state"] = "degraded"
        health["last_failure"] = message[:500]
        health["last_failure_at"] = self._timestamp()
        health["last_probe_success"] = False
        health["failure_active"] = True
        self._root_failures[key] = self._root_failures.get(key, 0) + 1
        self._failures[backend] = sum(value for (name, _root), value in self._root_failures.items() if name == backend)
        if self._root_failures[key] >= self.failure_threshold:
            self._root_cooldown_until[key] = time.monotonic() + self.cooldown_seconds
        if emit_telemetry and self.telemetry is not None:
            try:
                self.telemetry.record_error("code_intelligence", f"{backend}:{operation}", exc, retryable=True, recovered=False)
            except Exception:
                pass

    def _record_failure_recovery(self, backend: str, exc: Exception, *, operation: str, recovered: bool) -> None:
        if self.telemetry is not None:
            try:
                self.telemetry.record_error(
                    "code_intelligence", f"{backend}:{operation}", exc,
                    retryable=True, recovered=recovered,
                )
            except Exception:
                pass

    def _backend_enabled(self, backend: str) -> bool:
        return self.enabled and backend == "serena" and self.serena_enabled

    def _tool_python(self, backend: str) -> Path:
        bindir = "Scripts" if os.name == "nt" else "bin"
        executable = "python.exe" if os.name == "nt" else "python"
        return self.install_root / "tool-envs" / backend / bindir / executable

    def _package_spec(self, backend: str) -> tuple[str, str, str] | None:
        if backend != "serena":
            return None
        tools_cfg = self.config.get("tools", {})
        configured = str(tools_cfg.get(f"{backend}_package", "") or "").strip()
        if configured.count("==") != 1 or any(marker in configured for marker in (";", " @ ", "*")):
            return None
        distribution, version = (part.strip() for part in configured.split("==", 1))
        distribution_name = distribution.split("[", 1)[0].lower().replace("_", "-")
        expected_name = "serena-agent"
        if distribution_name != expected_name or not version or any(char in version for char in "<>!=,* "):
            return None
        return configured, expected_name, version

    def _managed_command(self, backend: str, command: str | None) -> bool:
        if not command:
            return False
        try:
            Path(command).resolve().relative_to((self.install_root / "tool-envs" / backend).resolve())
            return True
        except (OSError, ValueError):
            return False

    def _installed_package_matches(self, backend: str, package_name: str, version: str) -> bool:
        python = self._tool_python(backend)
        if not python.is_file():
            return False
        try:
            result = run_hidden(
                [str(python), "-m", "pip", "show", package_name],
                cwd=str(self.install_root), capture_output=True, text=True, timeout=10.0,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
        installed = next((line.partition(":")[2].strip() for line in (result.stdout or "").splitlines() if line.lower().startswith("version:")), "")
        return installed == version

    def _repair_backend(self, backend: str, *, reason: str) -> bool:
        if backend != "serena" or not self._backend_enabled(backend):
            return False
        setup_cfg = self.config.get("setup", {})
        if not bool(setup_cfg.get("install_optional_tools", True)):
            self._backend_health[backend].update(state="degraded", repair_blocked="optional tool installation is disabled")
            return False
        package = self._package_spec(backend)
        if package is None:
            self._backend_health[backend].update(state="degraded", repair_blocked="repair requires an exact package version pin")
            return False
        lock = self._repair_locks[backend]
        if not lock.acquire(timeout=min(360.0, self.repair_timeout + 60.0)):
            self.refresh_discovery()
            return bool(self._serena)
        health = self._backend_health[backend]
        try:
            self.refresh_discovery()
            now = time.monotonic()
            last_attempt = float(health.get("last_repair_at", 0.0))
            if last_attempt and now - last_attempt < self.repair_cooldown:
                return bool(self._serena)
            health["state"] = "repairing"
            health["repair_attempts"] = int(health.get("repair_attempts", 0)) + 1
            health["last_repair_at"] = now
            health["repair_reason"] = reason[:300]
            venv = self.install_root / "tool-envs" / backend
            python = self._tool_python(backend)
            if not python.is_file():
                try:
                    created = run_hidden(
                        [sys.executable, "-m", "venv", str(venv)],
                        cwd=str(self.install_root), capture_output=True, text=True, timeout=60.0,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    health.update(state="degraded", repair_error=f"virtual environment creation failed ({type(exc).__name__})")
                    return False
                if created.returncode != 0 or not python.is_file():
                    health.update(state="degraded", repair_error="virtual environment creation failed")
                    return False
            configured_package, _package_name, _version = package
            try:
                installed = run_hidden(
                    [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "--force-reinstall", configured_package],
                    cwd=str(self.install_root), capture_output=True, text=True, timeout=self.repair_timeout,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                health.update(state="degraded", repair_error=f"isolated package repair failed ({type(exc).__name__})")
                return False
            if installed.returncode != 0:
                health.update(state="degraded", repair_error="isolated package repair failed")
                return False
            self.refresh_discovery()
            command = self._serena
            if not command:
                health.update(state="degraded", repair_error="package installed but its executable was not found")
                return False
            health.update(state="repair_pending_probe", repair_error="", last_recovery=self._timestamp())
            return True
        finally:
            lock.release()

    def _needs_package_repair(self, backend: str, exc: Exception | None) -> bool:
        command = self._serena
        if not command or not Path(command).is_file():
            return True
        if exc is None:
            return False
        message = str(exc).lower()
        return any(marker in message for marker in ("no module named", "cannot import name", "modulenotfounderror", "importerror"))

    def _recover_backend(self, backend: str, root: str, exc: Exception) -> bool:
        sessions = self._serena_sessions
        with self._lock:
            session = sessions.pop(root, None)
            self._session_access["serena"].pop(root, None)
            self._root_failures.pop((backend, root), None)
            self._root_cooldown_until.pop((backend, root), None)
            self._failures[backend] = sum(value for (name, _root), value in self._root_failures.items() if name == backend)
            self._cooldown_until[backend] = 0.0
        if session:
            session.close()
        self.refresh_discovery()
        if self._needs_package_repair(backend, exc):
            if not self._repair_backend(backend, reason=str(exc)):
                return False
        command = self._serena
        if command:
            self._backend_health[backend].update(state="recovering", last_recovery=self._timestamp())
            return True
        return False

    def _startup_preflight(self) -> None:
        if not self._backend_enabled("serena"):
            return
        try:
            self.backend_available("serena")
        except Exception as exc:
            self._backend_health["serena"].update(state="degraded", last_failure=f"startup preflight failed ({type(exc).__name__})")

    @staticmethod
    def _root(root: str) -> str:
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"root directory does not exist: {path}")
        return str(path)

    @staticmethod
    def _serena_language_args(root: str, git_ignored_dirs: set[str] | None = None) -> list[str]:
        suffixes = {
            ".cs": "csharp", ".csx": "csharp", ".py": "python", ".pyi": "python",
            ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
            ".ts": "typescript", ".tsx": "typescript", ".js": "typescript", ".jsx": "typescript",
            ".go": "go", ".rb": "ruby", ".dart": "dart", ".cpp": "cpp", ".cc": "cpp",
            ".cxx": "cpp", ".h": "cpp", ".hpp": "cpp", ".php": "php", ".r": "r",
            ".sh": "bash", ".bash": "bash", ".ps1": "powershell", ".fs": "fsharp",
            ".fsx": "fsharp", ".swift": "swift", ".ex": "elixir", ".exs": "elixir",
            ".lua": "lua", ".zig": "zig", ".scala": "scala", ".jl": "julia",
        }
        ignored = {".git", ".serena", ".venv", "venv", "node_modules", "bin", "obj", "target"}
        ignored.update(name.lower() for name in (git_ignored_dirs or set()))
        counts: Counter[str] = Counter()
        try:
            for directory, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in ignored]
                for filename in filenames:
                    language = suffixes.get(Path(filename).suffix.lower())
                    if language:
                        counts[language] += 1
        except OSError:
            return []
        if not counts:
            return []
        language = max(counts, key=lambda name: (counts[name], name == "python"))
        return ["--language", language]

    def _run_index(self, backend: str, argv: list[str], root: str, env: dict[str, str] | None = None, *, _retrying: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        kwargs: dict[str, Any] = hidden_run_kwargs(text=True, new_group=True)
        if os.name != "nt":
            kwargs["start_new_session"] = True
        proc: subprocess.Popen[str] | None = None
        try:
            merged_env = os.environ.copy()
            if env:
                merged_env.update({str(key): str(value) for key, value in env.items()})
            # Indexers can print project content (including emoji) to stderr;
            # force UTF-8 in child Python processes instead of inheriting a
            # Windows ANSI code page that turns diagnostics into a hard failure.
            merged_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
            proc = popen_managed(argv, cwd=root, env=merged_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
            try:
                stdout, stderr = proc.communicate(timeout=self.index_timeout)
            except subprocess.TimeoutExpired as exc:
                terminate_tree(proc.pid, grace_seconds=1.0, process_handle=proc)
                try:
                    stdout, stderr = proc.communicate(timeout=2.0)
                except Exception:
                    stdout, stderr = "", ""
                raise TimeoutError(f"{backend} indexing exceeded {self.index_timeout:.0f}s") from exc
            if proc.returncode != 0:
                detail = (stderr or stdout or "index command failed").strip()[-3000:]
                raise RuntimeError(f"{backend} index exited {proc.returncode}: {detail}")
            self.index_runs += 1
            self._record_success(backend, root=root)
            return {"success": True, "backend": backend, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "output": (stdout or "").strip()[-self.max_output_chars:]}
        except Exception as exc:
            if proc is not None and proc.poll() is None:
                try:
                    terminate_tree(proc.pid, grace_seconds=1.0, process_handle=proc)
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            if not _retrying and not isinstance(exc, TimeoutError) and not self._is_revision_scoped_index_error("index", str(exc)):
                if self._recover_backend(backend, root, exc):
                    command = self._serena
                    if command:
                        self._record_failure(backend, exc, operation="index", root=root)
                        return self._run_index(backend, [command, *argv[1:]], root, env=env, _retrying=True)
            msg = str(exc)
            if not self._is_revision_scoped_index_error("index", msg):
                self.index_failures += 1
            self._record_failure(backend, exc, operation="index", root=root)
            return {"success": False, "backend": backend, "error": msg, "error_type": type(exc).__name__}

    def index(self, backend: str, root: str) -> dict[str, Any]:
        backend = backend.strip().lower()
        root = self._root(root)
        if backend != "serena":
            return {"success": False, "backend": backend, "unavailable": True, "error": f"unsupported backend: {backend}"}
        if not self.enabled:
            return {"success": False, "skipped": True, "backend": backend, "reason": "code intelligence disabled"}
        if self._backend_enabled(backend):
            self.backend_available(backend)
        if not self._allowed(backend, root):
            return {"success": False, "skipped": True, "backend": backend, "reason": "circuit cooldown"}
        if backend == "serena":
            if not self.serena_enabled:
                return {"success": False, "skipped": True, "backend": backend, "reason": "Serena disabled by configuration"}
            if not self._serena:
                return {"success": False, "skipped": True, "backend": backend, "reason": "Serena not installed"}
            with self._backend_operation("serena", root):
                result = self._run_index("serena", [self._serena, "project", "index", root, *self._serena_language_args(root, self._git_ignored_directory_names(root)), "--log-level", "WARNING", "--timeout", "10"], root)
            # Indexing can invalidate server-side project state. Restart the project session lazily.
            with self._lock:
                session = self._serena_sessions.pop(root, None)
                self._session_access["serena"].pop(root, None)
            if session:
                session.close()
            return result
        return {"success": False, "error": f"unknown code-intelligence backend: {backend}"}

    def backend_available(self, backend: str) -> bool:
        """Run a cached package/command preflight and repair the managed environment if needed."""
        backend = backend.strip().lower()
        if backend not in self._repair_locks:
            return False
        if not self._backend_enabled(backend):
            self._backend_health[backend].update(state="disabled")
            return False
        health = self._backend_health[backend]
        now = time.monotonic()
        command = self._serena
        with self._lock:
            if now - float(health.get("last_preflight_at", 0.0)) < 300.0:
                return bool(command)
            health["last_preflight_at"] = now
        self.refresh_discovery()
        command = self._serena
        if not command:
            health.update(state="missing", last_failure="managed executable is missing")
            return self._repair_backend(backend, reason="managed executable is missing")
        if self._managed_command(backend, command):
            package = self._package_spec(backend)
            if package is None:
                health.update(state="degraded", repair_blocked="repair requires an exact package version pin")
                return True
            _configured, package_name, version = package
            if not self._installed_package_matches(backend, package_name, version):
                health.update(state="version_mismatch", last_failure=f"installed {package_name} version does not match configured pin {version}")
                return self._repair_backend(backend, reason=f"installed {package_name} version does not match configured pin {version}")
        health.update(state="available", repair_error="", repair_blocked="")
        return True

    def _serena_session(self, root: str) -> MCPStdioClient:
        root = self._root(root)
        if not self._serena:
            raise MCPStdioError("Serena is not installed")
        with self._lock:
            session = self._serena_sessions.get(root)
            if session is None:
                context = str(self.cfg.get("serena_context", "codex"))
                session = MCPStdioClient(
                    [self._serena, "start-mcp-server", "--transport", "stdio", "--context", context, "--project", root, "--open-web-dashboard", "false", "--log-level", "WARNING"],
                    cwd=root,
                    startup_timeout=self.startup_timeout,
                    call_timeout=self.call_timeout,
                )
                self._serena_sessions[root] = session
            evicted = self._touch_session_locked(root)
        self._close_clients(evicted)
        return session

    def _fallback_code_index(self, root: str, action: str, query: str = "", path: str = "", limit: int = 20, reason: str = "serena_soft_timeout") -> dict[str, Any]:
        if not self.code_index:
            return {"success": False, "backend": "serena", "error": reason, "degraded_reason": reason, "fallback_used": False}
        action = action.strip().lower().replace("-", "_")
        try:
            if action in {"find_symbol", "symbol", "overview", "symbols_overview"}:
                res = self.code_index.find_symbol(root, query or "*", relative_path=path or None, limit=limit, substring_matching=True)
                symbols = res.get("symbols", []) if isinstance(res, dict) else []
                return {
                    "success": True,
                    "backend": "code_index",
                    "action": action,
                    "fallback_used": True,
                    "degraded_reason": reason,
                    "symbols": symbols,
                    "matches": symbols,
                    "matches_count": len(symbols),
                }
            elif action in {"references", "find_references", "referencing"}:
                res = self.code_index.find_symbol(root, query or "*", relative_path=path or None, limit=limit)
                symbols = res.get("symbols", []) if isinstance(res, dict) else []
                return {
                    "success": True,
                    "backend": "code_index",
                    "action": action,
                    "fallback_used": True,
                    "degraded_reason": reason,
                    "references": symbols,
                    "matches": symbols,
                    "matches_count": len(symbols),
                }
            else:
                res = self.code_index.search(root, query, limit=limit)
                symbols = res.get("symbols", []) if isinstance(res, dict) else []
                return {
                    "success": True,
                    "backend": "code_index",
                    "action": action,
                    "fallback_used": True,
                    "degraded_reason": reason,
                    "results": symbols,
                    "matches": symbols,
                    "matches_count": len(symbols),
                }
        except Exception as exc:
            return {
                "success": False,
                "backend": "code_index",
                "action": action,
                "fallback_used": True,
                "degraded_reason": f"{reason}:code_index_error:{type(exc).__name__}",
                "error": str(exc),
            }

    def query_serena(self, root: str, action: str, query: str = "", path: str = "", limit: int = 20, timeout: float | None = None, soft_timeout: float | None = None) -> dict[str, Any]:
        root = self._root(root)
        eff_soft_timeout = float(soft_timeout) if soft_timeout is not None else self.soft_timeout
        lock_wait = min(eff_soft_timeout, 1.5) if eff_soft_timeout > 0 else (float(timeout) if timeout is not None else 60.0)
        try:
            with self._backend_operation("serena", root, timeout=lock_wait):
                return self._query_serena_locked(root, action, query, path, limit, timeout=timeout, soft_timeout=eff_soft_timeout)
        except (TimeoutError, MCPSoftTimeoutError) as exc:
            self.query_failures += 1
            if self.code_index is not None:
                return self._fallback_code_index(root, action, query, path, limit, reason="serena_soft_timeout")
            return {"success": False, "skipped": True, "backend": "serena", "error": str(exc), "error_type": type(exc).__name__, "fallback_used": False, "degraded_reason": "serena_soft_timeout"}

    def _query_serena_locked(self, root: str, action: str, query: str, path: str, limit: int, *, timeout: float | None = None, soft_timeout: float | None = None, _retrying: bool = False) -> dict[str, Any]:
        if not self.serena_enabled:
            if self.code_index is not None:
                return self._fallback_code_index(root, action, query, path, limit, reason="serena_disabled")
            return {"success": False, "backend": "serena", "unavailable": True, "error": "Serena disabled by configuration"}
        if not self._serena:
            self.backend_available("serena")
        if not self._serena:
            if self.code_index is not None:
                return self._fallback_code_index(root, action, query, path, limit, reason="serena_not_installed")
            return {"success": False, "backend": "serena", "unavailable": True, "error": "Serena not installed"}
        if not self._allowed("serena", root):
            if self.code_index is not None:
                return self._fallback_code_index(root, action, query, path, limit, reason="serena_circuit_cooldown")
            return {"success": False, "backend": "serena", "unavailable": True, "error": "Serena circuit cooldown"}
        action = action.strip().lower().replace("-", "_")
        if action in {"search", "pattern", "find_symbol", "symbol"} and not query.strip():
            return {"backend": "serena", "action": action, "matches": [], "symbols": []}
        try:
            client = self._serena_session(root)
            common = {"relative_path": path or None, "max_answer_chars": self.max_output_chars}

            def _invoke_client_tool(tool_name: str, tool_args: dict[str, Any]) -> Any:
                try:
                    return client.call_tool(tool_name, tool_args, timeout=timeout, soft_timeout=soft_timeout)
                except TypeError as err:
                    if "soft_timeout" in str(err):
                        return client.call_tool(tool_name, tool_args, timeout=timeout)
                    raise

            if action in {"overview", "symbols_overview"}:
                if not path:
                    return {"success": False, "backend": "serena", "error": "path is required for overview"}
                result = _invoke_client_tool("get_symbols_overview", {"relative_path": path, "depth": 1, "max_answer_chars": self.max_output_chars})
            elif action in {"references", "find_references", "referencing"}:
                if not path:
                    return {"success": False, "backend": "serena", "error": "path is required for precise Serena references"}
                result = _invoke_client_tool("find_referencing_symbols", {"name_path": query, "relative_path": path, "max_answer_chars": self.max_output_chars})
            elif action in {"search", "pattern"}:
                if "search_for_pattern" in client.tool_names():
                    result = _invoke_client_tool("search_for_pattern", {"substring_pattern": query, "relative_path": path or None, "restrict_search_to_code_files": True, "max_answer_chars": self.max_output_chars})
                else:
                    # Some Serena contexts omit pattern search; symbol lookup remains available.
                    result = _invoke_client_tool("find_symbol", {"name_path_pattern": query, **common, "depth": 1, "include_body": False, "substring_matching": True})
            else:
                result = _invoke_client_tool("find_symbol", {"name_path_pattern": query, **common, "depth": 1, "include_body": False, "substring_matching": True})
            self._raise_tool_error(result, "Serena")
            self.queries += 1
            self._record_success("serena", root=root, probe=True)
            return {"backend": "serena", "action": action, **self._trim(result)}
        except MCPSoftTimeoutError as exc:
            self.query_failures += 1
            self._record_failure("serena", exc, operation=action, root=root, emit_telemetry=False)
            if self.code_index is not None:
                fallback = self._fallback_code_index(root, action, query, path, limit, reason="serena_soft_timeout")
                self._record_failure_recovery("serena", exc, operation=action, recovered=bool(fallback.get("success")))
                return fallback
            self._record_failure_recovery("serena", exc, operation=action, recovered=False)
            return {"success": False, "backend": "serena", "error": str(exc), "error_type": "MCPSoftTimeoutError", "fallback_used": False, "degraded_reason": "serena_soft_timeout"}
        except Exception as exc:
            self._record_failure("serena", exc, operation=action, root=root, emit_telemetry=False)
            if not _retrying and self._recover_backend("serena", root, exc):
                recovered = self._query_serena_locked(root, action, query, path, limit, timeout=timeout, soft_timeout=soft_timeout, _retrying=True)
                self._record_failure_recovery("serena", exc, operation=action, recovered=bool(recovered.get("success")))
                return recovered
            self.query_failures += 1
            if self.code_index is not None:
                fallback = self._fallback_code_index(root, action, query, path, limit, reason=f"serena_error:{type(exc).__name__}")
                self._record_failure_recovery("serena", exc, operation=action, recovered=bool(fallback.get("success")))
                return fallback
            self._record_failure_recovery("serena", exc, operation=action, recovered=False)
            return {"success": False, "backend": "serena", "error": str(exc), "error_type": type(exc).__name__}

    def query(self, root: str, query: str, *, backend: str = "auto", action: str = "search", path: str = "", limit: int = 20, timeout: float | None = None, soft_timeout: float | None = None) -> dict[str, Any]:
        backend = backend.strip().lower()
        if backend not in {"auto", "serena"}:
            return {"success": False, "backend": backend, "unavailable": True, "error": f"unsupported backend: {backend}"}
        return self.query_serena(root, action, query, path, limit, timeout=timeout, soft_timeout=soft_timeout)

    @staticmethod
    def _raise_tool_error(result: dict[str, Any], backend: str) -> None:
        if not result.get("success", True):
            raise RuntimeError(str(result.get("error") or f"{backend} tool request failed"))
        for candidate in (result.get("structured"), result.get("result")):
            if not isinstance(candidate, dict):
                continue
            if candidate.get("success") is False or candidate.get("isError") is True:
                raise RuntimeError(str(candidate.get("error") or f"{backend} tool returned an error"))
            nested = candidate.get("results")
            if isinstance(nested, dict) and nested.get("error"):
                raise RuntimeError(str(nested["error"]))

    def _trim(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json_dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return value
        if len(encoded) <= self.max_output_chars:
            return value
        raw_result = value.get("result")
        trimmed_result = None
        if isinstance(raw_result, dict):
            trimmed_result = dict(list(raw_result.items())[:20])
        elif isinstance(raw_result, (list, tuple)):
            trimmed_result = list(raw_result)[:20]
        out: dict[str, Any] = {
            "success": bool(value.get("success", True)),
            "truncated": True,
            "preview": encoded[: self.max_output_chars],
        }
        if trimmed_result is not None:
            out["result"] = trimmed_result
        return out

    def reset_sessions(self, backend: str = "all", root: str | None = None) -> dict[str, Any]:
        backend = (backend or "all").strip().lower()
        if backend not in {"all", "serena"}:
            return {"success": False, "error": f"unknown backend: {backend}"}
        resolved_root = self._root(root) if root else None
        clients: list[MCPStdioClient] = []
        removed = {"serena": 0}
        with self._lock:
            sessions = self._serena_sessions
            keys = [resolved_root] if resolved_root and resolved_root in sessions else list(sessions) if not resolved_root else []
            for key in keys:
                client = sessions.pop(key, None)
                self._session_access["serena"].pop(key, None)
                if client is not None:
                    clients.append(client)
                    removed["serena"] += 1
            failure_keys = [key for key in self._root_failures if key[0] == "serena" and (resolved_root is None or key[1] == resolved_root)]
            for key in failure_keys:
                self._root_failures.pop(key, None)
                self._root_cooldown_until.pop(key, None)
            self._failures["serena"] = sum(value for (failed_backend, _root), value in self._root_failures.items() if failed_backend == "serena")
            self._cooldown_until["serena"] = 0.0
        self._close_clients(clients)
        return {"success": True, "removed": removed, "root": resolved_root, "backend": backend}

    def rediscover(self) -> dict[str, Any]:
        self.reset_sessions("all")
        self.refresh_discovery()
        return {"success": True, **self.status()}

    def status(self) -> dict[str, Any]:
        with self._lock:
            evicted = self._prune_sessions_locked()
            serena_sessions = len(self._serena_sessions)
        self._close_clients(evicted)
        def backend_status(name: str, command: str | None, sessions: int) -> dict[str, Any]:
            configured_enabled = bool(self.cfg.get(f"{name}_enabled", True))
            enabled = self._backend_enabled(name)
            health = dict(self._backend_health[name])
            command_available = bool(command and Path(command).is_file())
            state = str(health.get("state") or "unknown")
            if not enabled:
                state = "disabled"
            elif command_available and state in {"unknown", "missing"}:
                state = "available"
            reason = str(health.get("repair_error") or health.get("repair_blocked") or "")
            if not reason and (state not in {"healthy", "available"} or health.get("failure_active")):
                reason = str(health.get("last_failure") or "")
            if not configured_enabled or not self.enabled:
                reason = "disabled by configuration"
            elif not command_available and not reason:
                reason = "managed executable is missing"
            return {
                "configured_enabled": configured_enabled,
                "enabled": enabled,
                "installed": command_available,
                "command_available": command_available,
                "command": command or "",
                "state": state,
                "failures": self._failures[name],
                "cooldown": max(0.0, round(self._cooldown_until[name] - time.monotonic(), 1)),
                "sessions": sessions,
                "last_failure": str(health.get("last_failure") or ""),
                "failure_active": bool(health.get("failure_active", False)),
                "last_recovery": str(health.get("last_recovery") or ""),
                "repair_error": str(health.get("repair_error") or ""),
                "repair_blocked": str(health.get("repair_blocked") or ""),
                "repair_attempts": int(health.get("repair_attempts", 0)),
                "last_successful_probe": str(health.get("last_successful_probe") or ""),
                "last_probe_success": health.get("last_probe_success"),
                "last_successful_operation": str(health.get("last_successful_operation") or ""),
                "unavailable_reason": reason,
            }
        return {
            "enabled": self.enabled,
            "serena": backend_status("serena", self._serena, serena_sessions),
            "session_policy": {"max_per_backend": self.max_sessions, "idle_ttl_seconds": self.session_idle_ttl},
            "stats": {"index_runs": self.index_runs, "index_failures": self.index_failures, "queries": self.queries, "query_failures": self.query_failures},
        }

    def __enter__(self) -> "ExternalCodeIntelligence":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            sessions = list(self._serena_sessions.values())
            self._serena_sessions.clear()
            self._session_access["serena"].clear()
        self._close_clients(sessions)
