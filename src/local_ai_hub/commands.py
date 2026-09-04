from __future__ import annotations

import os
import re
import signal
import ntpath
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .cache import SQLiteCache, TieredCache, stable_hash
from .repo_state import RepoStateTracker
from .process_utils import hidden_run_kwargs, terminate_tree


class CommandBroker:
    """Safe shared command runner with repo-state-aware cache and single-flight."""

    READ_ONLY = {"git", "rg", "ripgrep", "grep", "findstr", "where", "which"}
    VALIDATORS = {"pytest", "phpunit", "phpstan", "ruff", "mypy", "eslint", "tsc", "cargo", "dotnet", "go", "npm", "pnpm", "yarn", "bun", "composer", "make", "cmake", "ctest", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat"}
    MUTATING_WORDS = {
        "commit", "push", "pull", "merge", "rebase", "reset", "clean", "checkout", "switch", "restore", "add", "stash", "apply",
        "install", "update", "upgrade", "publish", "deploy", "migrate", "migration", "seed", "format", "fix", "write", "delete", "remove",
    }
    DANGEROUS_EXES = {"rm", "del", "erase", "rmdir", "shutdown", "reboot", "poweroff", "mkfs", "diskpart", "format"}

    def __init__(self, config: dict[str, Any], artifacts: Any, repo_state: RepoStateTracker):
        self.config = config
        self.artifacts = artifacts
        self.repo_state = repo_state
        cfg = config.get("commands", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.timeout = int(cfg.get("timeout_seconds", 900))
        self.max_output_chars = int(cfg.get("max_output_chars", 2_000_000))
        self.inline_chars = int(cfg.get("inline_output_chars", 5000))
        self.coalesce_wait_seconds = max(1.0, float(cfg.get("coalesced_wait_seconds", 90.0)))
        self.terminate_grace_seconds = max(0.1, float(cfg.get("terminate_grace_seconds", 2.0)))
        self.post_kill_drain_seconds = max(0.1, float(cfg.get("post_kill_drain_seconds", 2.0)))
        state_dir = Path(config["server"]["state_dir"])
        l1_entries = int(cfg.get("l1_entries", 128))
        self.success_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:success", int(cfg.get("success_ttl_seconds", 43200)), int(cfg.get("max_entries", 5000))), l1_entries, int(cfg.get("l1_ttl_seconds", 900)))
        self.failure_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:failure", int(cfg.get("failure_ttl_seconds", 180)), int(cfg.get("max_failure_entries", 1000))), max(32, l1_entries // 2), min(300, int(cfg.get("l1_ttl_seconds", 900))))
        self.suppression_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:suppression", int(cfg.get("suppression_ttl_seconds", 900)), int(cfg.get("max_suppression_entries", 2000))), max(32, l1_entries // 2), min(300, int(cfg.get("l1_ttl_seconds", 900))))
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._last: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.coalesced = 0
        self.coalesced_timeouts = 0
        self.executed = 0
        self.blocked = 0
        self.suppressed = 0
        self.cancelled = 0
        self._blocked_by_reason: dict[str, int] = {}
        self._active_commands: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_cancel_keys: dict[str, tuple[str, str]] = {}
        self.incident_store: Any = None
        self.verification_store: Any = None

    def set_incident_store(self, incident_store: Any) -> None:
        self.incident_store = incident_store

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    @staticmethod
    def _tokens(command: str) -> list[str]:
        try:
            tokens = shlex.split(command, posix=(os.name != "nt"))
            if os.name == "nt":
                return [t[1:-1] if (len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")))) else t for t in tokens]
            return tokens
        except ValueError:
            return []

    PURE_VALIDATORS = {"pytest", "phpunit", "phpstan", "pest", "ruff", "mypy", "eslint", "tsc", "pyflakes"}

    def classify(self, command: str) -> dict[str, Any]:
        tokens = self._tokens(command)
        if not tokens:
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "empty or unparsable command"}
        raw_exe = tokens[0].strip('"').replace("/", "\\")
        # ntpath handles Windows-style paths even when tests run on Linux. This is
        # important for Composer wrappers such as .\vendor\bin\phpunit.bat.
        exe = ntpath.basename(raw_exe).lower() or Path(tokens[0].strip('"')).name.lower()
        exe_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", exe)
        lower = [t.lower() for t in tokens[1:]]
        cfg = self.config.get("commands", {})

        if exe_base in self.DANGEROUS_EXES:
            return {"class": "dangerous", "cacheable": False, "allowed": False, "reason": "dangerous executable"}
        if (any(x in {"&&", "||", ";", "|", "&", ">", ">>", "<", "<<"} for x in tokens)
                or any(op in command for op in ("&&", "||", ";", "`", "$("))):
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "shell operators are not accepted"}

        if exe_base == "git":
            unsafe_git_flags = {"--paginate", "-p", "-c", "--config-env", "--exec-path"}
            if any(flag in unsafe_git_flags or flag.startswith("--exec-path=") for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "git flags may execute a pager or external program"}
            sub = lower[0] if lower else ""
            if sub in {"status", "diff", "show", "log", "grep", "ls-files", "rev-parse", "branch", "tag", "describe"}:
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only git"}
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"git {sub} may mutate"}

        if exe_base in {"rg", "ripgrep", "grep", "findstr", "where", "which"}:
            if exe_base in {"rg", "ripgrep"} and any(flag == "--pre" or flag.startswith("--pre=") for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "ripgrep preprocessor may execute arbitrary programs"}
            return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read/search command"}

        if exe_base in {"python", "python3", "py"}:
            dash_m = None
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-m" and idx < len(tokens) - 1:
                    dash_m = tokens[idx + 1].lower()
                    break
            if dash_m in {"pytest", "ruff", "mypy", "unittest", "flake8", "compileall", "pyflakes"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": f"python -m {dash_m} validation"}
            if dash_m in {"build", "wheel"}:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} packaging"}
            if dash_m in {"local_ai_hub", "local_ai_hub.generator"}:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} dynamic artifacts generator"}
            non_flag_args = [t for t in tokens[1:] if not t.startswith("-")]
            if non_flag_args:
                script_name = Path(non_flag_args[0].replace("\\", "/")).name.lower()
                sub_args = [t.lower() for t in non_flag_args[1:]]
                if script_name in {"hubctl.py", "hubctl"}:
                    sub = sub_args[0] if sub_args else ""
                    if sub == "tasks":
                        is_mutating = any(t in lower for t in {"--complete", "--fail"})
                        if is_mutating:
                            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "hubctl tasks status mutation"}
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "hubctl tasks status check"}
                    if sub in {"status", "service-status", "agent-state", "dashboard", "watch", "memory", "doctor", "logs"}:
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": f"hubctl {sub} status check"}
                    if sub == "generate":
                        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "hubctl generate dynamic artifacts"}
                    if sub in {"start", "stop", "restart", "cleanup"}:
                        return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"hubctl {sub} service lifecycle mutation"}
                if script_name in {"setup.py", "setup"}:
                    if any(t in lower for t in {"--generate-only", "--help", "-h"}):
                        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "setup.py generate dynamic artifacts"}
                if any(f in arg.lower() for arg in non_flag_args for f in ("test", "validate", "check", "flow", "status", "audit", "doctor", "selftest", "report")):
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "python validation script"}

        if exe_base == "hubctl":
            sub = lower[0] if lower else ""
            if sub == "tasks":
                is_mutating = any(t in lower for t in {"--complete", "--fail"})
                if is_mutating:
                    return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "hubctl tasks status mutation"}
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "hubctl tasks status check"}
            if sub in {"status", "service-status", "agent-state", "dashboard", "watch", "memory", "doctor", "logs"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": f"hubctl {sub} status check"}
            if sub == "generate":
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "hubctl generate dynamic artifacts"}
            if sub in {"start", "stop", "restart", "cleanup"}:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"hubctl {sub} service lifecycle mutation"}

        if exe_base in {"pwsh", "powershell"}:
            if any(f in t.lower() for t in tokens[1:] for f in ("invoke-woodboundcli", "test", "validate", "check", "status")):
                return {"class": "validation", "cacheable": False, "allowed": bool(cfg.get("allow_validation", True)), "reason": "powershell validation/cli invocation"}

        if exe_base == "php" and lower:
            php_target = ntpath.basename(lower[0].replace("/", "\\"))
            if any(name in php_target for name in ("phpunit", "phpstan", "pest")):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "PHP validation tool"}

        if exe_base in self.PURE_VALIDATORS or any(name in exe_base for name in ("phpunit", "phpstan", "pytest", "pest")):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": f"{exe_base} validation tool"}

        positional_verbs = [t.lower() for t in tokens[1:] if not t.startswith(("-", "/"))]
        primary_verb = positional_verbs[0] if positional_verbs else ""

        # Package/build tools often execute arbitrary user-defined scripts. Treat
        # only well-known validation/build verbs as safe instead of assuming that
        # every invocation of npm/make/gradle is a validator.
        package_tools = {"npm", "pnpm", "yarn", "bun"}
        if exe_base in package_tools:
            mutating = {"install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade", "publish", "link", "unlink", "pack", "version"}
            if primary_verb in mutating:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} {primary_verb} changes dependencies or publishes artifacts"}
            script = ""
            if primary_verb in {"run", "run-script"} and len(positional_verbs) > 1:
                script = positional_verbs[1]
            elif primary_verb:
                script = primary_verb
            safe_validation = {"test", "lint", "check", "typecheck", "type-check", "analyse", "analyze", "audit"}
            safe_build = {"build", "compile"}
            if script in safe_validation:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": f"{exe_base} safe validation script"}
            if script in safe_build:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} safe build script"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} script is not in the safe validation/build allowlist"}

        if exe_base == "composer":
            if primary_verb in {"install", "update", "upgrade", "remove", "require", "create-project", "dump-autoload", "global"}:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"composer {primary_verb} may change dependencies or generated files"}
            if primary_verb in {"validate", "audit", "test", "phpunit", "phpstan", "analyse", "analyze", "check"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "composer validation command"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "composer command is not in the safe validation allowlist"}

        if exe_base == "make":
            if any(v in {"clean", "install", "uninstall", "deploy", "publish", "release"} for v in positional_verbs):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "make target may mutate or deploy"}
            safe_validation = {"test", "tests", "check", "lint", "validate", "verify", "typecheck"}
            safe_build = {"build", "compile", "all"}
            if positional_verbs and all(v in safe_validation for v in positional_verbs):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "make validation target"}
            if positional_verbs and all(v in safe_build for v in positional_verbs):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "make build target"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "make target is not in the safe validation/build allowlist"}

        if exe_base == "cargo":
            if primary_verb in {"fmt"} and "--check" not in lower:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "cargo fmt changes source without --check"}
            if primary_verb in {"test", "check", "clippy", "bench"} or (primary_verb == "fmt" and "--check" in lower):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "cargo validation command"}
            if primary_verb == "build":
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "cargo build"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "cargo command is not in the safe validation/build allowlist"}

        if exe_base in {"go", "dotnet", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "cmake", "ctest"}:
            if any(v in self.MUTATING_WORDS or v in {"tidy", "publish", "deploy", "release"} for v in positional_verbs):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} command may mutate project or publish artifacts"}
            validation_words = {"test", "tests", "check", "verify", "lint", "vet", "clippy", "ctest"}
            build_words = {"build", "compile", "package", "assemble"}
            if exe_base == "ctest" or any(v in validation_words for v in positional_verbs):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": f"{exe_base} validation command"}
            if exe_base == "cmake" or any(v in build_words for v in positional_verbs):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} build command"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} command is not in the safe validation/build allowlist"}

        if exe_base in self.VALIDATORS:
            if primary_verb in self.MUTATING_WORDS:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"mutating verb {primary_verb}"}
            if any(x in positional_verbs for x in ("build", "compile")):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "build command"}
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "reason": "validation/test command"}

        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "command not in safe broker allowlist"}

    @staticmethod
    def _safe_label(command: str) -> str:
        # Local dashboard metadata only; redact common credential-bearing options.
        text = re.sub(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)", r"\1***", command.strip())
        text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1***", text)
        return text[:240]

    def _tool_identity(self, command: str, cwd: str) -> dict[str, Any]:
        tokens = self._tokens(command)
        if not tokens:
            return {}
        raw = tokens[0].strip('"')
        candidate = Path(raw)
        if not candidate.is_absolute():
            local = (Path(cwd) / candidate).resolve(strict=False)
            resolved = local if local.exists() else Path(shutil.which(raw) or raw)
        else:
            resolved = candidate
        try:
            stat = resolved.stat()
            return {"path": str(resolved.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except Exception:
            return {"path": str(resolved)}

    def _key(self, command: str, cwd: str, classification: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        state = self.repo_state.fingerprint(cwd)
        env_keys = self.config.get("commands", {}).get("environment_keys", ["CI", "NODE_ENV", "APP_ENV", "PYTHONPATH"])
        env = {str(k): os.environ.get(str(k), "") for k in env_keys}
        key = stable_hash({
            "command": command.strip(), "cwd": str(Path(cwd).resolve()), "class": classification.get("class"),
            "repo": state.get("fingerprint"), "env": env, "python": sys.version_info[:3], "tool": self._tool_identity(command, cwd),
        })
        return key, state

    def _attempt_key(self, command: str, cwd: str) -> str:
        return stable_hash({
            "command": " ".join(self._tokens(command)),
            "cwd": str(Path(cwd).resolve()),
            "tool": self._tool_identity(command, cwd),
        })

    def _unavailable_executable(self, command: str, cwd: str) -> str | None:
        tokens = self._tokens(command)
        if not tokens:
            return None
        raw = tokens[0].strip('"')
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        has_path = any(marker in raw for marker in ("/", "\\"))
        if has_path:
            return None if candidate.exists() else raw
        return None if shutil.which(raw) else raw

    @staticmethod
    def _non_retryable_failure(result: dict[str, Any]) -> bool:
        if result.get("success") or result.get("timed_out"):
            return False
        text = (str(result.get("error", "")) + "\n" + str(result.get("stderr", ""))).lower()
        return int(result.get("exit_code", 0) or 0) == 127 or any(marker in text for marker in (
            "failed to spawn process", "command not found", "is not recognized as an internal", "no such file or directory",
        ))

    def _execute(self, command: str, cwd: str, timeout: int, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        tokens = self._tokens(command)
        started = time.perf_counter()
        if os.name == "nt":
            raw0 = tokens[0].strip('"') if tokens else ""
            suffix = Path(raw0).suffix.lower()
            resolved = shutil.which(raw0) or shutil.which(raw0, path=cwd)
            if (resolved and Path(resolved).suffix.lower() in {".bat", ".cmd"}) or suffix in {".bat", ".cmd"}:
                argv = command
            else:
                argv = tokens
        else:
            argv = tokens
        kwargs: dict[str, Any] = {
            "cwd": str(Path(cwd).resolve()), "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "text": True, "encoding": "utf-8", "errors": "replace",
        }
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(argv, **kwargs)
        except OSError as exc:
            return {
                "success": False, "exit_code": 127, "timed_out": False,
                "stdout": "", "stderr": str(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": f"failed to spawn process: {exc}",
            }
        timed_out = False
        cancelled = False
        deadline = time.monotonic() + max(1, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if remaining <= 0:
                timed_out = True
                break
            try:
                stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if timed_out or cancelled:
            # Kill the complete child tree/session, not just the wrapper process.
            try:
                terminate_tree(process.pid, grace_seconds=self.terminate_grace_seconds)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                stdout, stderr = process.communicate(timeout=self.post_kill_drain_seconds)
            except Exception:
                stdout, stderr = "", ""
        stdout = (stdout or "")[-self.max_output_chars:]
        stderr = (stderr or "")[-self.max_output_chars:]
        self.executed += 1
        return {
            "success": (not timed_out) and (not cancelled) and process.returncode == 0,
            "exit_code": -9 if timed_out or cancelled else int(process.returncode or 0),
            "timed_out": timed_out, "cancelled": cancelled, "stdout": stdout, "stderr": stderr,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            **({"error": "command cancelled"} if cancelled else {"error": f"command timed out after {timeout}s"} if timed_out else {}),
        }

    @staticmethod
    def _cancel_key(command: str, cwd: str) -> str:
        return stable_hash({"command": command.strip(), "cwd": str(Path(cwd).resolve())})

    def cancel(self, command: str, cwd: str, tenant: str) -> dict[str, Any]:
        """Request bounded cancellation of one currently running broker command."""
        lookup = self._cancel_key(command, cwd)
        tenant_key = str(tenant)[:80]
        with self._lock:
            key = next((item for item, value in self._active_cancel_keys.items() if value == (lookup, tenant_key)), "")
            event = self._cancel_events.get(key) if key else None
            active = dict(self._active_commands.get(key, {})) if key else {}
            if event is None:
                return {"success": False, "terminal": True, "retryable": False, "error": "no matching active command"}
            event.set()
            self.cancelled += 1
        return {"success": True, "cancellation_requested": True, "active": active}

    @staticmethod
    def _extract_diagnostics(result: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
        text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))).strip()
        diagnostics: list[dict[str, Any]] = []
        patterns = [
            re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+)(?::(?P<col>\d+))?[:\s]+(?P<msg>.+)$"),
            re.compile(r"^FAILED\s+(?P<path>[^:\s]+)(?:::(?P<msg>.+))?$"),
        ]
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            matched = None
            for pattern in patterns:
                m = pattern.match(line)
                if m:
                    matched = m; break
            if matched:
                data = matched.groupdict()
                diagnostics.append({
                    "path": data.get("path", ""),
                    "line": int(data.get("line") or 0),
                    "column": int(data.get("col") or 0),
                    "message": str(data.get("msg") or line)[:500],
                })
            elif any(x in line.lower() for x in ("error", "fatal", "exception", "traceback", "assertionerror", "panic")):
                diagnostics.append({"path": "", "line": 0, "column": 0, "message": line[:500]})
            if len(diagnostics) >= limit:
                break
        return diagnostics

    @staticmethod
    def _deterministic_summary(result: dict[str, Any], limit: int = 60) -> str:
        text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))).strip()
        lines = text.splitlines()
        if len(lines) <= limit:
            return text
        needles = ("error", "fail", "fatal", "warning", "assert", "exception", "traceback", "passed", "failed", "success", "tests", "errors")
        selected = [line for line in lines if any(n in line.lower() for n in needles)]
        # Keep final framework summary because pytest/phpunit/cargo/go normally report counts there.
        tail = lines[-min(12, len(lines)):]
        for line in tail:
            if line not in selected:
                selected.append(line)
        if len(selected) < limit // 2:
            selected = lines[: max(8, limit // 5)] + selected
        return "\n".join(selected[:limit])

    def run(self, command: str, cwd: str, tenant: str, *, timeout: int | None = None, force: bool = False, task_id: str = "", criterion: str = "") -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "command broker disabled"}
        classification = self.classify(command)
        attempt_key = self._attempt_key(command, cwd)
        if not force:
            suppressed = self.suppression_cache.get(attempt_key)
            if isinstance(suppressed, dict):
                self.suppressed += 1
                result = dict(suppressed)
                result.update({"suppression_cache_hit": True, "classification": classification})
                return self._compact(result, tenant, command)
        if not classification["allowed"]:
            with self._lock:
                self.blocked += 1
                reason = str(classification.get("reason", "policy"))[:120]
                self._blocked_by_reason[reason] = self._blocked_by_reason.get(reason, 0) + 1
            result = {
                "success": False, "error": f"command blocked: {classification['reason']}",
                "classification": classification, "policy_blocked": True, "terminal": True, "retryable": False,
            }
            if not force:
                self.suppression_cache.set(attempt_key, result)
            return result
        cwd_path = Path(cwd).expanduser().resolve(strict=False)
        if not cwd_path.is_dir():
            result = {
                "success": False,
                "error": f"working directory does not exist: {cwd_path}",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force:
                self.suppression_cache.set(attempt_key, result)
            return result
        unavailable = self._unavailable_executable(command, cwd)
        if unavailable:
            result = {
                "success": False, "error": f"command executable is unavailable: {unavailable}",
                "exit_code": 127, "classification": classification, "preflight": True, "terminal": True, "retryable": False,
            }
            if not force:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        key, state = self._key(command, cwd, classification)
        if classification["cacheable"] and not force:
            cached = self.success_cache.get(key) or self.failure_cache.get(key)
            if isinstance(cached, dict):
                self.hits += 1
                result = dict(cached)
                result.update({"cache_hit": True, "coalesced": False, "classification": classification, "repo_state": state})
                if result.get("success") and task_id and self.verification_store is not None:
                    try:
                        from .agent_verification import VerificationReceipt
                        rcpt = VerificationReceipt.create(
                            task_id=task_id,
                            criterion=criterion or f"command:{self._safe_label(command)}",
                            passed=True,
                            command_id=command,
                            evidence_id=str(result.get("artifact_id") or ""),
                            repository_revision=str(state.get("fingerprint", "")),
                            details={"exit_code": 0, "cached": True},
                        )
                        self.verification_store.record(rcpt)
                        result["verification_receipt"] = rcpt.to_dict()
                    except Exception:
                        pass
                return self._compact(result, tenant, command)

        with self._lock:
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event(); self._inflight[key] = event; owner = True
            else:
                owner = False; self.coalesced += 1
        if not owner:
            # A second agent should benefit from single-flight without being trapped
            # behind a very long build/test command. The owner keeps running and will
            # populate the cache; the waiter gets a bounded in-progress response.
            wait_budget = min(max(1.0, float(timeout or self.timeout) + 5.0), self.coalesce_wait_seconds)
            if not event.wait(wait_budget):
                with self._lock:
                    self.coalesced_timeouts += 1
                    active = dict(self._active_commands.get(key, {}))
                return {
                    "success": False, "in_progress": True, "retryable": True,
                    "error": "identical command is still running in another agent; do not start a duplicate",
                    "classification": classification, "repo_state": state, "active": active,
                }
            with self._lock:
                result = dict(self._last.get(key, {"success": False, "error": "coalesced command failed"}))
            result.update({"cache_hit": True, "coalesced": True, "classification": classification, "repo_state": state})
            return self._compact(result, tenant, command)

        self.misses += 1
        started_wall = time.time()
        cancel_event = threading.Event()
        with self._lock:
            self._active_commands[key] = {
                "command": self._safe_label(command), "cwd": Path(cwd).name or str(Path(cwd)),
                "tenant": str(tenant)[:80], "class": str(classification.get("class", "")),
                "started_at": started_wall, "timeout_seconds": int(timeout or self.timeout),
            }
            self._cancel_events[key] = cancel_event
            self._active_cancel_keys[key] = (self._cancel_key(command, cwd), str(tenant)[:80])
        try:
            result = self._execute(command, cwd, int(timeout or self.timeout), cancel_event)
            diag_paths = [d["path"] for d in result.get("diagnostics", []) if d.get("path")]
            if not result.get("success") and not result.get("cancelled") and self.incident_store is not None:
                try:
                    from .agent_incidents import ToolOutcome
                    inc = self.incident_store.capture(ToolOutcome(
                        tool_name="command",
                        command=command,
                        error=str(result.get("error") or result.get("stderr") or ("exit code " + str(result.get("exit_code", 1)))),
                        exit_code=int(result.get("exit_code", 1)),
                        state_revision=str(state.get("fingerprint", "")),
                        timed_out=bool(result.get("timed_out")),
                        cancelled=bool(result.get("cancelled")),
                        affected_paths=tuple(set(diag_paths)),
                    ))
                    if inc and (inc.root_cause or inc.verified_fix):
                        result["remediation"] = {
                            "incident_id": inc.incident_id,
                            "root_cause": inc.root_cause,
                            "verified_fix": inc.verified_fix,
                            "confidence": inc.confidence,
                            "attempts": inc.attempts,
                        }
                except Exception:
                    pass

            if self.incident_store is not None:
                try:
                    target_paths = set(diag_paths)
                    for cp in state.get("changed_paths", []):
                        target_paths.add(str(cp))
                    if target_paths:
                        regs = self.incident_store.find_regressions(list(target_paths))
                        if regs:
                            result["regression_warnings"] = regs
                except Exception:
                    pass

            raw = dict(result)
            if classification["cacheable"] and not result.get("cancelled"):
                (self.success_cache if result.get("success") else self.failure_cache).set(key, raw)
            if result.get("success") and task_id and self.verification_store is not None:
                try:
                    from .agent_verification import VerificationReceipt
                    rcpt = VerificationReceipt.create(
                        task_id=task_id,
                        criterion=criterion or f"command:{self._safe_label(command)}",
                        passed=True,
                        command_id=command,
                        evidence_id=str(result.get("artifact_id") or ""),
                        repository_revision=str(state.get("fingerprint", "")),
                        details={"exit_code": 0, "duration_ms": result.get("duration_ms", 0)},
                    )
                    self.verification_store.record(rcpt)
                    result["verification_receipt"] = rcpt.to_dict()
                except Exception:
                    pass
            if not force and self._non_retryable_failure(raw):
                raw.update({"terminal": True, "retryable": False})
                self.suppression_cache.set(attempt_key, raw)
            with self._lock:
                self._last[key] = raw
                if len(self._last) > 128:
                    for k in list(self._last.keys())[:-64]:
                        self._last.pop(k, None)
            result.update({"cache_hit": False, "coalesced": False, "classification": classification, "repo_state": state})
            return self._compact(result, tenant, command)
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "command timed out", "classification": classification, "cache_hit": False}
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                self._active_commands.pop(key, None)
                self._cancel_events.pop(key, None)
                self._active_cancel_keys.pop(key, None)
                event.set()

    def _compact(self, result: dict[str, Any], tenant: str, command: str) -> dict[str, Any]:
        stdout = str(result.get("stdout", "")); stderr = str(result.get("stderr", ""))
        combined_chars = len(stdout) + len(stderr)
        result["summary"] = self._deterministic_summary(result)
        diagnostics = self._extract_diagnostics(result)
        if result.get("remediation"):
            rem = result["remediation"]
            fix_msg = rem.get("verified_fix") or rem.get("root_cause")
            if fix_msg:
                diagnostics.insert(0, {
                    "path": "",
                    "line": 0,
                    "column": 0,
                    "message": f"Remediation guidance: {fix_msg}",
                })
        result["diagnostics"] = diagnostics
        if combined_chars > self.inline_chars:
            full = f"$ {command}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            result["artifact_id"] = self.artifacts.put(full, tenant, "command")
            result["stdout"] = stdout[: self.inline_chars // 2]
            result["stderr"] = stderr[-self.inline_chars // 2:]
            result["output_truncated"] = True
        else:
            result["output_truncated"] = False
        return result

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            active = [dict(v, age_ms=max(0, int((now - float(v.get("started_at", now))) * 1000))) for v in self._active_commands.values()]
            blocked_by_reason = dict(sorted(self._blocked_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))[:12])
        return {
            "enabled": self.enabled, "hits": self.hits, "misses": self.misses, "cancelled": self.cancelled,
            "coalesced_waiters": self.coalesced, "coalesced_wait_timeouts": self.coalesced_timeouts, "executed": self.executed,
            "blocked": self.blocked, "blocked_by_reason": blocked_by_reason,
            "suppressed": self.suppressed, "suppression_cache": self.suppression_cache.stats(),
            "active_count": len(active), "active": active[:24],
            "success_cache": self.success_cache.stats(), "failure_cache": self.failure_cache.stats(),
        }
