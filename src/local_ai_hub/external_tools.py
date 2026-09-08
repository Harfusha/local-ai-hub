from __future__ import annotations

import json
import hashlib
import os
import queue
import shlex
import shutil
import subprocess
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

from . import __version__
from .process_utils import hidden_run_kwargs, terminate_tree


class MCPStdioError(RuntimeError):
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
        # Windows process code page is a legacy charmap (for example cp1252).
        merged_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        stderr_lines: deque[str] = deque(maxlen=80)
        try:
            proc = subprocess.Popen(
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
                    "protocolVersion": "2025-11-25",
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
            proc.stdin.write(json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except Exception as exc:
            raise MCPStdioError(f"MCP write failed: {type(exc).__name__}") from exc

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any], *, timeout: float | None = None, ensure_started: bool = True) -> Any:
        if ensure_started:
            self._spawn()
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + (self.call_timeout if timeout is None else max(0.05, float(timeout)))
        while time.monotonic() < deadline:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                detail = " | ".join(list(self._stderr)[-3:])
                raise MCPStdioError(f"MCP process exited{': ' + detail if detail else ''}")
            try:
                item = self._responses.get(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
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

    def call_tool(self, name: str, args: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
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
            result = self._request("tools/call", {"name": name, "arguments": filtered}, timeout=timeout)
            return self._normalize_tool_result(result)

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

    def _stop_process(self) -> None:
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
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            terminate_tree(proc.pid, grace_seconds=1.0)
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass
        # Popen does not guarantee pipe file objects are closed merely because
        # the child exited. Closing them also unblocks line-reader threads.
        for stream in (proc.stdout, proc.stderr):
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
    """Managed Serena + CodeGraphContext integration for preprocessing and local agents."""

    _CGC_BASE_IGNORE_DIRS = {
        ".git", ".idea", ".serena", ".venv", ".vscode", "__pycache__", ".pytest_cache",
        ".tox", ".mypy_cache", "build", "dist", "env", "node_modules", "obj", "out",
        "target", "tmp", "venv",
    }
    _CGC_SAFE_GIT_IGNORE_DIR_NAMES = {
        ".tmp", ".vs", ".woodbound", "Builds", "Library", "Logs", "Temp", "UserSettings",
        "artifacts", "coverage", "htmlcov",
    }

    def __init__(self, config: dict[str, Any], telemetry: Any | None = None):
        self.config = config
        self.telemetry = telemetry
        self.cfg = config.get("code_intelligence", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.serena_enabled = self.enabled and bool(self.cfg.get("serena_enabled", True))
        self.codegraph_enabled = self.enabled and bool(self.cfg.get("codegraph_enabled", True))
        self.install_root = Path(__file__).resolve().parents[2]
        self.call_timeout = float(self.cfg.get("query_timeout_seconds", 20.0))
        self.startup_timeout = float(self.cfg.get("startup_timeout_seconds", 45.0))
        self.index_timeout = float(self.cfg.get("index_timeout_seconds", 30.0))
        self.max_output_chars = max(1000, int(self.cfg.get("max_output_chars", 9000)))
        self._lock = threading.RLock()
        self._serena_sessions: dict[str, MCPStdioClient] = {}
        # CodeGraphContext sandboxes project paths to the MCP server cwd (plus
        # CGC_ALLOWED_ROOTS). Keep one process per project so every query is both
        # security-compatible and isolated from another repository's graph context.
        self._codegraph_sessions: dict[str, MCPStdioClient] = {}
        self.max_sessions = max(1, int(self.cfg.get("max_sessions_per_backend", 8)))
        self.session_idle_ttl = max(1.0, float(self.cfg.get("session_idle_ttl_seconds", 900.0)))
        self._session_access: dict[str, dict[str, float]] = {"serena": {}, "codegraph": {}}
        self._failures: dict[str, int] = {"serena": 0, "codegraph": 0}
        self._cooldown_until: dict[str, float] = {"serena": 0.0, "codegraph": 0.0}
        self._root_failures: dict[tuple[str, str], int] = {}
        self._root_cooldown_until: dict[tuple[str, str], float] = {}
        self.failure_threshold = max(1, int(self.cfg.get("failure_threshold", 2)))
        self.cooldown_seconds = max(1.0, float(self.cfg.get("cooldown_seconds", 60.0)))
        self._serena = self._resolve_command("serena") if self.serena_enabled else None
        self._codegraph = self._resolve_command("codegraph") if self.codegraph_enabled else None
        self.index_runs = 0
        self.index_failures = 0
        self.queries = 0
        self.query_failures = 0

    def _resolve_command(self, backend: str) -> str | None:
        explicit = str(self.cfg.get(f"{backend}_command", "") or "").strip()
        if explicit:
            parts = shlex.split(explicit, posix=os.name != "nt")
            candidate = os.path.expandvars(os.path.expanduser(parts[0].strip('"\''))) if parts else ""
            if candidate and (Path(candidate).exists() or shutil.which(candidate)):
                return str(Path(candidate).resolve()) if Path(candidate).exists() else str(shutil.which(candidate))
        suffix = ".exe" if os.name == "nt" else ""
        bindir = "Scripts" if os.name == "nt" else "bin"
        if backend == "serena":
            candidates = [
                self.install_root / "tool-envs" / "serena" / bindir / f"serena{suffix}",
            ]
            names = ["serena"]
        else:
            candidates = [
                self.install_root / "tool-envs" / "codegraph" / bindir / f"cgc{suffix}",
                self.install_root / "tool-envs" / "codegraph" / bindir / f"codegraphcontext{suffix}",
            ]
            names = ["cgc", "codegraphcontext"]
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
            self._codegraph = self._resolve_command("codegraph") if self.codegraph_enabled else None

    @staticmethod
    def _git_ignored_directory_names(root: str) -> set[str]:
        """Return literal directory names Git already excludes from this worktree."""
        try:
            probe = subprocess.run(
                ["git", "-C", root, "rev-parse", "--show-toplevel"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2,
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
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
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
                if name and (is_global or name in ExternalCodeIntelligence._CGC_SAFE_GIT_IGNORE_DIR_NAMES) and not any(char in name for char in "*?["):
                    names.add(name)
        return names

    def _prune_sessions_locked(self, backend: str) -> list[MCPStdioClient]:
        """Remove idle/LRU project MCP processes while holding ``self._lock``."""
        sessions = self._serena_sessions if backend == "serena" else self._codegraph_sessions
        access = self._session_access[backend]
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

    def _touch_session_locked(self, backend: str, root: str) -> list[MCPStdioClient]:
        self._session_access[backend][root] = time.monotonic()
        return self._prune_sessions_locked(backend)

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

    def _record_success(self, backend: str, *, root: str | None = None) -> None:
        if root is not None:
            self._root_failures.pop((backend, root), None)
            self._root_cooldown_until.pop((backend, root), None)
        self._failures[backend] = sum(value for (name, _root), value in self._root_failures.items() if name == backend)
        self._cooldown_until[backend] = 0.0

    @staticmethod
    def _is_revision_scoped_index_error(operation: str, message: str) -> bool:
        if operation != "index":
            return False
        lowered = message.lower()
        return any(marker in lowered for marker in (
            "indexing exceeded",
            "no associated project configuration",
            "no configuration file found",
            "project configuration auto-generation failed",
            "project root is missing",
        ))

    def _record_failure(self, backend: str, exc: Exception, *, operation: str, root: str | None = None) -> None:
        message = str(exc)
        if backend == "codegraph" and any(marker in message.lower() for marker in ("no module named 'codegraphcontext'", "no module named codegraphcontext", "cannot import name")):
            self.codegraph_enabled = False
            self._codegraph = None
            self._cooldown_until[backend] = 0.0
            self._failures[backend] = 0
            return
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
        self._root_failures[key] = self._root_failures.get(key, 0) + 1
        self._failures[backend] = sum(value for (name, _root), value in self._root_failures.items() if name == backend)
        if self._root_failures[key] >= self.failure_threshold:
            self._root_cooldown_until[key] = time.monotonic() + self.cooldown_seconds
        if self.telemetry is not None:
            try:
                self.telemetry.record_error("code_intelligence", f"{backend}:{operation}", exc, retryable=True, recovered=True)
            except Exception:
                pass

    @staticmethod
    def _root(root: str) -> str:
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"root directory does not exist: {path}")
        return str(path)

    def _codegraph_env(self, root: str) -> dict[str, str]:
        state_dir = Path(self.config["server"]["state_dir"]).expanduser().resolve()
        root_key = hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]
        db_path = state_dir / "codegraph" / f"{root_key}-kuzudb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        ignored_dirs = set(self._CGC_BASE_IGNORE_DIRS)
        ignored_dirs.update(self._git_ignored_directory_names(root))
        return {
            "CGC_OUTPUT_FORMAT": str(self.cfg.get("codegraph_output_format", "gcf")),
            "CGC_ALLOWED_ROOTS": root,
            "CGC_RUNTIME_DB_TYPE": "kuzudb",
            "CGC_RUNTIME_DB_PATH": str(db_path),
            "IGNORE_DIRS": ",".join(sorted(ignored_dirs)),
            # Large tracked evidence/export files are not useful graph source and
            # can make the first worktree index hit CGC's process timeout.
            "MAX_FILE_SIZE_MB": str(self.cfg.get("codegraph_max_file_size_mb", 5)),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

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

    def _run_index(self, backend: str, argv: list[str], root: str, env: dict[str, str] | None = None) -> dict[str, Any]:
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
            proc = subprocess.Popen(argv, cwd=root, env=merged_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
            try:
                stdout, stderr = proc.communicate(timeout=self.index_timeout)
            except subprocess.TimeoutExpired as exc:
                terminate_tree(proc.pid, grace_seconds=1.0)
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
                    terminate_tree(proc.pid, grace_seconds=1.0)
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            msg = str(exc)
            if not self._is_revision_scoped_index_error("index", msg) and not (backend == "codegraph" and any(m in msg.lower() for m in ("no module named", "cannot import"))):
                self.index_failures += 1
            self._record_failure(backend, exc, operation="index", root=root)
            return {"success": False, "backend": backend, "error": msg, "error_type": type(exc).__name__}

    def index(self, backend: str, root: str) -> dict[str, Any]:
        backend = backend.strip().lower()
        root = self._root(root)
        if not self.enabled:
            return {"success": False, "skipped": True, "backend": backend, "reason": "code intelligence disabled"}
        if backend == "serena" and self.serena_enabled and not self._serena:
            self.refresh_discovery()
        elif backend == "codegraph" and self.codegraph_enabled and not self._codegraph:
            self.refresh_discovery()
        if not self._allowed(backend, root):
            return {"success": False, "skipped": True, "backend": backend, "reason": "circuit cooldown"}
        if backend == "serena":
            if not self.serena_enabled or not self._serena:
                return {"success": False, "skipped": True, "backend": backend, "reason": "Serena not installed"}
            result = self._run_index("serena", [self._serena, "project", "index", root, *self._serena_language_args(root, self._git_ignored_directory_names(root)), "--log-level", "WARNING", "--timeout", "5"], root)
            # Indexing can invalidate server-side project state. Restart the project session lazily.
            with self._lock:
                session = self._serena_sessions.pop(root, None)
                self._session_access["serena"].pop(root, None)
            if session:
                session.close()
            return result
        if backend == "codegraph":
            if not self.codegraph_enabled or not self._codegraph:
                return {"success": False, "skipped": True, "backend": backend, "reason": "CodeGraphContext not installed"}
            result = self._run_index("codegraph", [self._codegraph, "index", "--no-progress", root], root, env=self._codegraph_env(root))
            # Re-open the graph lazily after indexing so a long-lived MCP process
            # cannot retain a stale embedded database/context.
            with self._lock:
                session = self._codegraph_sessions.pop(root, None)
                self._session_access["codegraph"].pop(root, None)
            if session:
                session.close()
            return result
        return {"success": False, "error": f"unknown code-intelligence backend: {backend}"}

    def backend_available(self, backend: str) -> bool:
        """Check whether an enabled backend can be launched, refreshing discovery once."""
        backend = backend.strip().lower()
        if backend == "serena":
            enabled = self.serena_enabled
            command = self._serena
        elif backend == "codegraph":
            enabled = self.codegraph_enabled
            command = self._codegraph
        else:
            return False
        if not enabled:
            return False
        if not command:
            self.refresh_discovery()
            command = self._serena if backend == "serena" else self._codegraph
        return bool(command)

    def _serena_session(self, root: str) -> MCPStdioClient:
        root = self._root(root)
        if not self._serena:
            raise MCPStdioError("Serena is not installed")
        with self._lock:
            session = self._serena_sessions.get(root)
            if session is None:
                context = str(self.cfg.get("serena_context", "ide-assistant"))
                session = MCPStdioClient(
                    [self._serena, "start-mcp-server", "--transport", "stdio", "--context", context, "--project", root, "--open-web-dashboard", "false", "--log-level", "WARNING"],
                    cwd=root,
                    startup_timeout=self.startup_timeout,
                    call_timeout=self.call_timeout,
                )
                self._serena_sessions[root] = session
            evicted = self._touch_session_locked("serena", root)
        self._close_clients(evicted)
        return session

    def _codegraph_client(self, root: str) -> MCPStdioClient:
        root = self._root(root)
        if not self._codegraph:
            raise MCPStdioError("CodeGraphContext is not installed")
        with self._lock:
            session = self._codegraph_sessions.get(root)
            if session is None:
                env = self._codegraph_env(root)
                session = MCPStdioClient(
                    [self._codegraph, "mcp", "start"], cwd=root, env=env,
                    startup_timeout=self.startup_timeout, call_timeout=self.call_timeout,
                )
                self._codegraph_sessions[root] = session
            evicted = self._touch_session_locked("codegraph", root)
        self._close_clients(evicted)
        return session

    def query_serena(self, root: str, action: str, query: str = "", path: str = "", limit: int = 20) -> dict[str, Any]:
        root = self._root(root)
        if not self.serena_enabled or not self._serena:
            return {"success": False, "backend": "serena", "unavailable": True, "error": "Serena not installed"}
        if not self._allowed("serena", root):
            return {"success": False, "backend": "serena", "unavailable": True, "error": "Serena circuit cooldown"}
        action = action.strip().lower().replace("-", "_")
        try:
            client = self._serena_session(root)
            common = {"relative_path": path or None, "max_answer_chars": self.max_output_chars}
            if action in {"overview", "symbols_overview"}:
                if not path:
                    return {"success": False, "backend": "serena", "error": "path is required for overview"}
                result = client.call_tool("get_symbols_overview", {"relative_path": path, "depth": 1, "max_answer_chars": self.max_output_chars})
            elif action in {"references", "find_references", "referencing"}:
                if not path:
                    return {"success": False, "backend": "serena", "error": "path is required for precise Serena references; use CodeGraph relationships when the file is unknown"}
                result = client.call_tool("find_referencing_symbols", {"name_path": query, "relative_path": path, "max_answer_chars": self.max_output_chars})
            elif action in {"search", "pattern"}:
                result = client.call_tool("search_for_pattern", {"substring_pattern": query, "relative_path": path or None, "restrict_search_to_code_files": True, "max_answer_chars": self.max_output_chars})
            else:
                result = client.call_tool("find_symbol", {"name_path_pattern": query, **common, "depth": 1, "include_body": False, "substring_matching": True})
            self.queries += 1
            self._record_success("serena", root=root)
            return {"backend": "serena", "action": action, **self._trim(result)}
        except Exception as exc:
            self.query_failures += 1
            self._record_failure("serena", exc, operation=action, root=root)
            with self._lock:
                session = self._serena_sessions.pop(root, None)
                self._session_access["serena"].pop(root, None)
            if session:
                session.reset()
            return {"success": False, "backend": "serena", "error": str(exc), "error_type": type(exc).__name__}

    def query_codegraph(self, root: str, action: str, query: str = "", path: str = "", limit: int = 20) -> dict[str, Any]:
        root = self._root(root)
        if not self.codegraph_enabled or not self._codegraph:
            return {"success": False, "backend": "codegraph", "unavailable": True, "error": "CodeGraphContext not installed"}
        if not self._allowed("codegraph", root):
            return {"success": False, "backend": "codegraph", "unavailable": True, "error": "CodeGraphContext circuit cooldown"}
        action = action.strip().lower().replace("-", "_")
        try:
            client = self._codegraph_client(root)
            if action in {"dead_code", "dead"}:
                result = client.call_tool("find_dead_code", {"repo_path": root, "exclude_decorated_with": []})
            elif action in {"complexity", "cyclomatic_complexity"}:
                result = client.call_tool("calculate_cyclomatic_complexity", {"function_name": query, "path": path or None, "repo_path": root})
            elif action in {"search", "find"}:
                result = client.call_tool("find_code", {"query": query, "fuzzy_search": True, "edit_distance": 2, "repo_path": root})
            elif action in {"stats", "repository_stats"}:
                result = client.call_tool("get_repository_stats", {"repo_path": root})
            else:
                qtype = {
                    "callers": "callers", "callees": "callees", "calls": "callees",
                    "imports": "imports", "importers": "importers", "inheritance": "inheritance",
                    "hierarchy": "hierarchy", "relationships": "all", "relationship": "all",
                }.get(action, action or "all")
                result = client.call_tool("analyze_code_relationships", {"query_type": qtype, "target": query, "context": path or None, "repo_path": root})
            self.queries += 1
            self._record_success("codegraph", root=root)
            return {"backend": "codegraph", "action": action, **self._trim(result)}
        except Exception as exc:
            self.query_failures += 1
            self._record_failure("codegraph", exc, operation=action, root=root)
            with self._lock:
                session = self._codegraph_sessions.pop(root, None)
                self._session_access["codegraph"].pop(root, None)
            if session is not None:
                session.reset()
            return {"success": False, "backend": "codegraph", "error": str(exc), "error_type": type(exc).__name__}

    def query(self, root: str, query: str, *, backend: str = "auto", action: str = "search", path: str = "", limit: int = 20) -> dict[str, Any]:
        backend = backend.strip().lower()
        if backend == "serena":
            return self.query_serena(root, action, query, path, limit)
        if backend in {"codegraph", "graph"}:
            return self.query_codegraph(root, action, query, path, limit)
        relationship_actions = {"callers", "callees", "calls", "imports", "importers", "inheritance", "hierarchy", "relationships", "relationship", "dead_code", "complexity"}
        if action.strip().lower().replace("-", "_") in relationship_actions and self.codegraph_enabled:
            primary = self.query_codegraph(root, action, query, path, limit)
            if primary.get("success"):
                return primary
        primary = self.query_serena(root, action, query, path, limit) if self.serena_enabled else {"success": False}
        if primary.get("success"):
            return primary
        return self.query_codegraph(root, "search" if action in {"find_symbol", "symbol", "search"} else action, query, path, limit)

    def _trim(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return value
        if len(encoded) <= self.max_output_chars:
            return value
        return {"success": bool(value.get("success", True)), "truncated": True, "preview": encoded[: self.max_output_chars]}

    def reset_sessions(self, backend: str = "all", root: str | None = None) -> dict[str, Any]:
        backend = (backend or "all").strip().lower()
        if backend not in {"all", "serena", "codegraph", "graph"}:
            return {"success": False, "error": f"unknown backend: {backend}"}
        if backend == "graph":
            backend = "codegraph"
        resolved_root = self._root(root) if root else None
        clients: list[MCPStdioClient] = []
        removed = {"serena": 0, "codegraph": 0}
        with self._lock:
            for name, sessions in (("serena", self._serena_sessions), ("codegraph", self._codegraph_sessions)):
                if backend not in {"all", name}:
                    continue
                keys = [resolved_root] if resolved_root and resolved_root in sessions else list(sessions) if not resolved_root else []
                for key in keys:
                    client = sessions.pop(key, None)
                    self._session_access[name].pop(key, None)
                    if client is not None:
                        clients.append(client); removed[name] += 1
                failure_keys = [key for key in self._root_failures if key[0] == name and (resolved_root is None or key[1] == resolved_root)]
                for key in failure_keys:
                    self._root_failures.pop(key, None)
                    self._root_cooldown_until.pop(key, None)
                self._failures[name] = sum(value for (failed_backend, _root), value in self._root_failures.items() if failed_backend == name)
                self._cooldown_until[name] = 0.0
        self._close_clients(clients)
        return {"success": True, "removed": removed, "root": resolved_root, "backend": backend}

    def rediscover(self) -> dict[str, Any]:
        self.reset_sessions("all")
        self.refresh_discovery()
        return {"success": True, **self.status()}

    def status(self) -> dict[str, Any]:
        with self._lock:
            evicted = self._prune_sessions_locked("serena") + self._prune_sessions_locked("codegraph")
            serena_sessions = len(self._serena_sessions)
            codegraph_sessions = len(self._codegraph_sessions)
        self._close_clients(evicted)
        return {
            "enabled": self.enabled,
            "serena": {"enabled": self.serena_enabled, "installed": bool(self._serena), "command": self._serena or "", "failures": self._failures["serena"], "cooldown": max(0.0, round(self._cooldown_until["serena"] - time.monotonic(), 1)), "sessions": serena_sessions},
            "codegraph": {"enabled": self.codegraph_enabled, "installed": bool(self._codegraph), "command": self._codegraph or "", "failures": self._failures["codegraph"], "cooldown": max(0.0, round(self._cooldown_until["codegraph"] - time.monotonic(), 1)), "sessions": codegraph_sessions, "unavailable_reason": "codegraph installation is incomplete" if not self.codegraph_enabled and self.enabled else ""},
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
            graph_sessions = list(self._codegraph_sessions.values())
            self._codegraph_sessions.clear()
            self._session_access["serena"].clear()
            self._session_access["codegraph"].clear()
        self._close_clients(sessions + graph_sessions)
