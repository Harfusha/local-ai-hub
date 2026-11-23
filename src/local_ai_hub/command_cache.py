from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from .cache import stable_hash
from .command_constants import (
    _MAX_PROJECT_COMMAND_ENV_BYTES,
    _MAX_PROJECT_COMMAND_ENV_ENTRIES,
)
from .command_environment import resolve_project_environment
from .command_models import (
    CommandInvocation,
    ProjectContextLike,
    _ResolvedProjectCommand,
)
from .command_project_cache import _project_config_cache_key
from .command_streams import StreamMultiplexer

class CommandCacheMixin:
    def _attempt_key(
        self,
        command: str,
        cwd: str,
        *,
        timeout: int,
        tool_identity: dict[str, Any] | None = None,
        project_config_digest: str = "",
        project_env_fingerprint: str = "",
        argv_fingerprint: str = "",
        cache_context: str = "",
    ) -> str:
        tokens = self._tokens(command)
        cmd_str = " ".join(tokens) if tokens else command.strip()
        key_identity = {
            "command": cmd_str,
            "cwd": str(Path(cwd).resolve()),
            "tool": tool_identity if tool_identity is not None else self._tool_identity(command, cwd),
            "timeout_seconds": int(timeout),
        }
        if project_config_digest:
            key_identity["project_config_digest"] = project_config_digest
        if project_env_fingerprint:
            key_identity["project_env_fingerprint"] = project_env_fingerprint
        if argv_fingerprint:
            key_identity["argv_fingerprint"] = argv_fingerprint
        key_identity["policy"] = self._cache_policy_identity()
        if cache_context:
            key_identity["context"] = cache_context
        return stable_hash(key_identity)
    def _cache_policy_identity(self) -> dict[str, Any]:
        commands_config = self.config.get("commands", {})
        return {
            "blocking": self.policy_blocking,
            **{
                name: bool(commands_config.get(name, default))
                for name, default in (
                    ("allow_read", True), ("allow_validation", True),
                    ("allow_build", True), ("allow_mutating", False),
                    ("allow_unknown", False),
                )
            },
            "extra_allowed_tools": sorted(
                str(tool).strip().lower()
                for tool in commands_config.get("extra_allowed_tools", [])
            ),
        }
    def _cached_project_command_context(self, root: str, state_dir: Path) -> Any:
        from .project_config import resolve_project_context

        cache_key = _project_config_cache_key(Path(root), state_dir)
        if cache_key is not None:
            with self._project_command_context_cache_lock:
                context = self._project_command_context_cache.get(cache_key)
                if context is not None:
                    self._project_command_context_cache.move_to_end(cache_key)
                    return context

        context = resolve_project_context(root, state_dir)
        if cache_key is not None and _project_config_cache_key(Path(root), state_dir) == cache_key:
            with self._project_command_context_cache_lock:
                self._project_command_context_cache[cache_key] = context
                self._project_command_context_cache.move_to_end(cache_key)
                while len(self._project_command_context_cache) > 64:
                    self._project_command_context_cache.popitem(last=False)
        return context
    @staticmethod
    def _cancel_key(command: str, cwd: str) -> str:
        return stable_hash({"command": command.strip(), "cwd": str(Path(cwd).resolve())})
    def _key(
        self,
        command: str,
        cwd: str,
        classification: dict[str, Any],
        *,
        timeout: int = 60,
        tool_identity: dict[str, Any] | None = None,
        phase_timings_ms: dict[str, float] | None = None,
        project_config_digest: str = "",
        project_env_fingerprint: str = "",
        argv_fingerprint: str = "",
        cache_context: str = "",
    ) -> tuple[str, dict[str, Any]]:
        fingerprint_started = time.perf_counter()
        state = self.repo_state.fingerprint(cwd)
        if phase_timings_ms is not None:
            phase_timings_ms["repository_fingerprint_ms"] = round((time.perf_counter() - fingerprint_started) * 1000, 3)
        env_keys = self.config.get("commands", {}).get("environment_keys", ["CI", "NODE_ENV", "APP_ENV", "PYTHONPATH"])
        env = {str(k): os.environ.get(str(k), "") for k in env_keys}
        resolved_tool_identity = tool_identity if tool_identity is not None else self._tool_identity(command, cwd)
        key_identity = {
            "command": command.strip(), "cwd": str(Path(cwd).resolve()), "class": classification.get("class"),
            "repo": state.get("fingerprint"), "env": env, "python": sys.version_info[:3], "tool": resolved_tool_identity,
            "timeout_seconds": int(timeout),
        }
        if project_config_digest:
            key_identity["project_config_digest"] = project_config_digest
        if project_env_fingerprint:
            key_identity["project_env_fingerprint"] = project_env_fingerprint
        if argv_fingerprint:
            key_identity["argv_fingerprint"] = argv_fingerprint
        key_identity["policy"] = self._cache_policy_identity()
        if cache_context:
            key_identity["context"] = cache_context
        key = stable_hash(key_identity)
        return key, state
    @staticmethod
    def _project_command_fingerprints(
        command: str | CommandInvocation,
        context: _ResolvedProjectCommand | None,
    ) -> tuple[str, str, str, str, str]:
        """Return the project-command identities bound to verification receipts."""
        if not isinstance(context, _ResolvedProjectCommand) or context.command != command:
            return "", "", "", "", ""

        project_environment_sha256 = hashlib.sha256(
            json.dumps(
                context.environment,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        configured = context.configured_command
        if isinstance(configured, CommandInvocation):
            configured_text = json.dumps(
                {
                    "argv": configured.argv,
                    "cwd": configured.cwd,
                    "shell": configured.shell,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            configured_text = configured
        configured_command_sha256 = hashlib.sha256(
            configured_text.encode("utf-8")
        ).hexdigest()
        caller_arguments_sha256 = hashlib.sha256(
            json.dumps(
                list(context.caller_arguments),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return (
            context.alias,
            context.config_digest,
            project_environment_sha256,
            configured_command_sha256,
            caller_arguments_sha256,
        )
    @staticmethod
    def _project_environment(
        project_context: ProjectContextLike | None,
        cwd: str,
    ) -> tuple[str, dict[str, str], str | None]:
        return resolve_project_environment(
            project_context,
            cwd,
            host_environment=os.environ,
            max_entries=_MAX_PROJECT_COMMAND_ENV_ENTRIES,
            max_bytes=_MAX_PROJECT_COMMAND_ENV_BYTES,
        )
    @staticmethod
    def _public_active(active: dict[str, Any]) -> dict[str, Any]:
        """Expose bounded active-command metadata."""
        return dict(active)
    @staticmethod
    def _read_cache_entry(cache: Any, key: str) -> tuple[Any | None, bool]:
        checked = getattr(cache, "get_checked", None)
        if callable(checked):
            value, healthy = checked(key)
            return (value if healthy else None), healthy
        return cache.get(key), True
    @classmethod
    def _read_cached_command_result(cls, success_cache: Any, failure_cache: Any, key: str) -> Any | None:
        value, healthy = cls._read_cache_entry(success_cache, key)
        if not healthy:
            return None
        if value is not None:
            return value
        value, healthy = cls._read_cache_entry(failure_cache, key)
        return value if healthy else None
    def cancel(self, command: str, cwd: str, *, execution_id: str = "") -> dict[str, Any]:
        """Request bounded cancellation of one currently running broker command."""
        lookup = self._cancel_key(command, cwd)
        with self._lock:
            if execution_id:
                matches = [
                    item for item, active in self._active_commands.items()
                    if active.get("execution_id") == execution_id
                ]
            else:
                matches = [item for item, value in self._active_cancel_keys.items() if value == lookup]
            if len(matches) > 1:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "error": "multiple matching active commands; provide execution_id",
                    "execution_ids": [str(self._active_commands[item].get("execution_id", "")) for item in matches],
                }
            key = matches[0] if matches else ""
            event = self._cancel_events.get(key) if key else None
            active = self._public_active(dict(self._active_commands.get(key, {}))) if key else {}
            if event is None:
                return {"success": False, "terminal": True, "retryable": False, "error": "no matching active command"}
            event.set()
            self.cancelled += 1
        return {"success": True, "cancellation_requested": True, "execution_id": active.get("execution_id", ""), "active": active}
    def run_parallel(
        self, commands: list[dict[str, Any] | str], cwd: str | None = None, *,
        max_concurrency: int = 4, timeout: int | None = None,
        multiplexer: StreamMultiplexer | None = None,
    ) -> dict[str, Any]:
        from .command_batches import run_parallel
        return run_parallel(self.run, commands, cwd=cwd, max_concurrency=max_concurrency,
                            timeout=timeout, multiplexer=multiplexer or StreamMultiplexer())
    def run_project_command(
        self,
        alias: str,
        cwd: str,
        *,
        args: Sequence[str] = (),
        timeout: int | None = None,
        force: bool = False,
        bypass_cache: bool = False,
        task_id: str = "",
        criterion: str = "",
        log_callback: Any | None = None,
        snapshot: bool = False,
        rollback_on_failure: bool = False,
        rollback_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run an explicit project command alias through normal broker policy."""
        from .project_config import ProjectConfigError

        try:
            resolved = self._resolve_project_command(alias, cwd, args=args)
        except ProjectConfigError as exc:
            return {
                "success": False,
                "error": f"project command unavailable: {exc.code}",
                "project_command_error": exc.code,
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
        except (OSError, RuntimeError, TypeError, ValueError):
            return {
                "success": False,
                "error": "project command configuration could not be resolved",
                "project_command_error": "configuration_resolution_failed",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }

        return self.run(
            resolved.command,
            cwd,
            timeout=timeout,
            force=force,
            bypass_cache=bypass_cache,
            task_id=task_id,
            criterion=criterion,
            log_callback=log_callback,
            snapshot=snapshot,
            rollback_on_failure=rollback_on_failure,
            rollback_paths=rollback_paths,
            _environment_overrides=resolved.environment,
            _cache_context=resolved.cache_context,
            _project_command_context=resolved,
        )
