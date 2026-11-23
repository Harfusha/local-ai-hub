from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any
import uuid

from .cache import stable_hash
from .command_constants import (
    _MAX_PROJECT_COMMAND_ENV_BYTES,
    _MAX_PROJECT_COMMAND_ENV_ENTRIES,
)
from .command_environment import is_valid_project_command_env_key as _is_valid_project_command_env_key
from .command_invocation_validation import validate_invocation
from .command_models import (
    CommandInvocation,
    ProjectContextLike,
    _ResolvedProjectCommand,
)
from .command_rollback import (
    _capture_rollback_postimages,
    _close_rollback_root,
    _restore_rollback_scope,
    _snapshot_rollback_scope,
    _stable_rollback_status,
)
from .command_singleflight import _CommandSingleflightEvent
from .command_transactions import RollbackSnapshot
from .process_utils import hidden_run_kwargs
from .state_paths import configured_state_dir
from .work_fencing import WorkAttemptFence

class CommandRunMixin:
    @_stable_rollback_status
    def run(
        self,
        command: str | CommandInvocation,
        cwd: str,
        *,
        timeout: int | None = None,
        force: bool = False,
        task_id: str = "",
        criterion: str = "",
        record_verification: bool = True,
        auto_fix: bool = False,
        fix_generator: Any | None = None,
        max_repair_attempts: int = 3,
        log_callback: Any | None = None,
        snapshot: bool = False,
        rollback_on_failure: bool = False,
        sandbox: str = "local",
        docker_image: str = "python:3.11-slim",
        bypass_cache: bool = False,
        paths: list[str] | None = None,
        rollback_paths: list[str] | None = None,
        project_context: ProjectContextLike | None = None,
        env: Mapping[str, str] | None = None,
        _environment_overrides: Mapping[str, str] | None = None,
        _cache_context: str = "",
        _transaction_context: str = "",
        _work_attempt_fence: WorkAttemptFence | None = None,
        _work_order_id: str = "",
        _project_command_context: _ResolvedProjectCommand | None = None,
        request_cancel_event: threading.Event | None = None,
        stdin: str | bytes | None = None,
        input: str | bytes | None = None,
    ) -> dict[str, Any]:
        if env is not None and _environment_overrides is None:
            _environment_overrides = env
        if request_cancel_event is not None and request_cancel_event.is_set():
            return {"success": False, "cancelled": True, "request_not_sent": True, "terminal": True, "retryable": False}
        (
            project_alias,
            project_config_digest,
            project_environment_sha256,
            configured_command_sha256,
            caller_arguments_sha256,
        ) = self._project_command_fingerprints(command, _project_command_context)
        if not self.enabled:
            return {"success": False, "error": "command broker disabled"}
        auto_bound_task = False
        project_alias_required = False
        if record_verification and task_id and criterion and _project_command_context is None:
            try:
                project_context = self._cached_project_command_context(
                    cwd, configured_state_dir(self.config)
                )
                if project_context.resolution.error_codes:
                    project_alias_required = True
                else:
                    project_alias_required = criterion.strip() in project_context.settings.verification_rules
            except Exception:
                project_alias_required = True
        if not isinstance(command, (str, CommandInvocation)):
            return {"success": False, "error": "command must be a string or validated argv invocation", "preflight": True, "terminal": True, "retryable": False}
        transaction_cwd: Path | None = None
        if _transaction_context:
            if not re.fullmatch(r"[0-9a-f]{32}", _transaction_context):
                return {"success": False, "error": "invalid private transaction context", "terminal": True, "retryable": False}
            try:
                transaction_cwd = self._transaction_root_for_context(_transaction_context).resolve(strict=True)
                requested_cwd = Path(cwd).resolve(strict=True)
                if transaction_cwd != requested_cwd or not transaction_cwd.is_dir():
                    raise ValueError("private transaction cwd does not match transaction context")
            except (OSError, ValueError) as exc:
                return {"success": False, "error": str(exc)[:256], "terminal": True, "retryable": False}
        if not isinstance(_cache_context, str):
            return {
                "success": False,
                "error": "project command cache context is invalid",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
        if _environment_overrides is not None:
            if not isinstance(_environment_overrides, Mapping) or len(_environment_overrides) > _MAX_PROJECT_COMMAND_ENV_ENTRIES:
                return {
                    "success": False,
                    "error": "project command environment is invalid",
                    "preflight": True,
                    "terminal": True,
                    "retryable": False,
                }
            environment_size = 0
            for name, value in _environment_overrides.items():
                if (
                    not isinstance(name, str)
                    or not _is_valid_project_command_env_key(name)
                    or not isinstance(value, str)
                    or "\x00" in value
                ):
                    return {
                        "success": False,
                        "error": "project command environment is invalid",
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }
                environment_size += len(name.encode("utf-8")) + len(value.encode("utf-8"))
                if environment_size > _MAX_PROJECT_COMMAND_ENV_BYTES:
                    return {
                        "success": False,
                        "error": "project command environment is too large",
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }
        if rollback_on_failure and auto_fix:
            return {"success": False, "error": "rollback_on_failure is supported only for direct run actions", "rollback_unsupported_action": True, "terminal": True, "retryable": False}
        rollback_state: RollbackSnapshot | None = None
        original_command = command
        argv_override: list[str] | None = None
        argv_fingerprint = ""
        if isinstance(command, CommandInvocation):
            invocation_result = validate_invocation(command)
            if not invocation_result.get("safe"):
                return {**invocation_result, "success": False, "preflight": True}
            argv_override = list(invocation_result["argv"])
            invocation_cwd = invocation_result.get("cwd")
            if invocation_cwd is not None:
                try:
                    if Path(invocation_cwd).expanduser().resolve(strict=False) != Path(cwd).expanduser().resolve(strict=False):
                        return {
                            "success": False,
                            "error": "structured invocation working directory does not match command working directory",
                            "preflight": True,
                            "terminal": True,
                            "retryable": False,
                        }
                except (OSError, TypeError, ValueError):
                    return {"success": False, "error": "structured invocation working directory is invalid", "preflight": True, "terminal": True, "retryable": False}
            argv_fingerprint = stable_hash(argv_override)
            command = subprocess.list2cmdline(argv_override) if os.name == "nt" else shlex.join(argv_override)
        command_digest_source = f"argv:{argv_fingerprint}" if argv_override is not None else command
        command_digest_value = hashlib.sha256(command_digest_source.encode("utf-8")).hexdigest()
        context_digest, project_env_overrides, project_context_error = self._project_environment(project_context, cwd)
        project_config_digest = context_digest or project_config_digest
        if project_context_error:
            return {
                "success": False,
                "error": project_context_error,
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
        project_env_fingerprint = stable_hash(project_env_overrides) if project_context is not None else ""
        effective_timeout = max(1, int(timeout or self.timeout))
        phase_timings_ms: dict[str, float] = {}
        classification_started = time.perf_counter()
        classified_command = argv_override if argv_override is not None else original_command
        command_input_valid = self._well_formed_command_input(classified_command)
        classification = self.classify(classified_command)
        phase_timings_ms["command_classification_ms"] = round((time.perf_counter() - classification_started) * 1000, 3)
        command_class = classification.get("class")
        classification_allowed = classification.get("allowed") is True
        command_policy = self.config.get("commands", {})
        unknown_authorized = command_class != "unknown" or (
            command_policy.get("allow_unknown") is True
            and command_policy.get("allow_mutating") is True
        )
        if not command_input_valid:
            classification_allowed = False
        elif command_class == "unknown" and unknown_authorized:
            classification_allowed = True
        if command_class == "dangerous" or not classification_allowed or not unknown_authorized:
            reason = str(classification.get("reason") or "command policy denied execution")[:120]
            if classification_allowed and not unknown_authorized:
                reason = "unknown command requires explicit unknown and mutation authorization"
            with self._lock:
                self.blocked += 1
                self._blocked_by_reason[reason] = self._blocked_by_reason.get(reason, 0) + 1
            native_fallback_allowed = command_class == "unknown" and command_input_valid
            return {
                "success": False, "error": f"command blocked: {reason}",
                "classification": classification, "classification_allowed": classification_allowed,
                "execution_authorized": False, "policy_blocked": True,
                "native_fallback_allowed": native_fallback_allowed,
                "native_fallback_reason": "unknown_command" if native_fallback_allowed else "policy_denial",
                "request_not_sent": True, "terminal": True, "retryable": False,
            }
        # Unknown code may mutate regardless of the classifier's lexical heuristics.
        # Its opt-in still requires task/worktree/write-set/fence and private execution.
        is_mutating = command_class in {"mutating", "unknown"}
        tool_identity_started = time.perf_counter()
        if argv_override is not None:
            tool_identity = self._tool_identity(command, cwd, argv_override=argv_override)
        else:
            tool_identity = self._tool_identity(command, cwd)
        suppressable = command_class not in {"mutating", "unknown"}
        attempt_key = (
            self._attempt_key(command, cwd, timeout=effective_timeout, tool_identity=tool_identity, project_config_digest=project_config_digest, project_env_fingerprint=project_env_fingerprint, argv_fingerprint=argv_fingerprint, cache_context=_cache_context)
            if _cache_context
            else self._attempt_key(command, cwd, timeout=effective_timeout, tool_identity=tool_identity, project_config_digest=project_config_digest, project_env_fingerprint=project_env_fingerprint, argv_fingerprint=argv_fingerprint)
        )
        if not force and not bypass_cache and not _transaction_context and suppressable:
            suppressed, suppression_cache_healthy = self._read_cache_entry(self.suppression_cache, attempt_key)
            if suppression_cache_healthy and isinstance(suppressed, dict):
                self.suppressed += 1
                result = dict(suppressed)
                result.update({"suppression_cache_hit": True, "classification": classification})
                return self._compact(result, command)
        cwd_path = Path(cwd).expanduser().resolve(strict=False)
        if not cwd_path.is_dir():
            result = {
                "success": False,
                "error": f"working directory does not exist: {cwd_path}",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return result
        if _transaction_context:
            unavailable = None
        elif argv_override is not None:
            unavailable = self._unavailable_executable(command, cwd, argv_override=argv_override)
        else:
            unavailable = self._unavailable_executable(command, cwd)
        if unavailable:
            result = {
                "success": False, "error": f"command executable is unavailable: {unavailable}",
                "exit_code": 127, "classification": classification, "preflight": True, "terminal": True, "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, command)
        declared_paths = paths if paths is not None else rollback_paths
        if rollback_on_failure:
            if not declared_paths:
                return {
                    "success": False,
                    "error": "rollback paths are required",
                    "rollback_scope_required": True,
                    "terminal": True,
                    "retryable": False,
                }
            for p in declared_paths:
                if not isinstance(p, str) or not p.strip() or ".." in Path(p).parts or Path(p).is_absolute():
                    return {
                        "success": False,
                        "error": f"rollback path is invalid: {p}",
                        "rollback_scope_invalid": True,
                        "terminal": True,
                        "retryable": False,
                    }
        if (is_mutating or auto_fix or rollback_on_failure) and not _transaction_context:
            worktree_error = self._require_task_worktree(task_id, cwd, original_command, require_git_identity=True)
            if worktree_error:
                return {
                    "success": False,
                    "error": worktree_error,
                    "mutation_worktree_required": True,
                    "terminal": True,
                    "retryable": False,
                }
        if (is_mutating or auto_fix) and not declared_paths and not _transaction_context:
            return {"success": False, "error": "mutating command requires an explicit non-empty paths write set", "mutation_write_set_required": True, "terminal": True, "retryable": False}
        if rollback_on_failure and paths is not None and rollback_paths is not None:
            if {value.replace(chr(92), "/") for value in paths} != {value.replace(chr(92), "/") for value in rollback_paths}:
                return {"success": False, "error": "paths and rollback_paths must describe the same write set", "mutation_write_set_invalid": True, "terminal": True, "retryable": False}
        if (is_mutating or rollback_on_failure) and _environment_overrides:
            return {"success": False, "error": "mutating transaction does not accept project environment overrides", "terminal": True, "retryable": False}
        fence_required = is_mutating or auto_fix or (
            rollback_on_failure and classification.get("class") == "unknown"
        )
        if fence_required and _work_attempt_fence is None:
            return {
                "success": False,
                "error": "mutating transaction requires a current work attempt fence",
                "failure_kind": "mutation_fence_unavailable",
                "mutation_fence_required": True,
                "outcome_unknown": False,
                "terminal": True,
                "retryable": False,
            }
        if not isinstance(_work_order_id, str) or _work_order_id != _work_order_id.strip() or "\x00" in _work_order_id:
            return {"success": False, "error": "invalid work order identity",
                    "failure_kind": "work_attempt_fence_invalid", "terminal": True, "retryable": False}
        if _work_order_id and _work_attempt_fence is None:
            return {"success": False, "error": "work order identity requires a current work attempt fence",
                    "failure_kind": "work_attempt_fence_invalid", "terminal": True, "retryable": False}
        if _work_attempt_fence is not None:
            try:
                if _work_order_id and (is_mutating or auto_fix or rollback_on_failure or _transaction_context):
                    raise ValueError("work order identity is invalid for this command")
                fence_resource = cwd
                if _transaction_context:
                    fence_resource = self._transaction_source_for_context(_transaction_context)
                    if fence_resource is None:
                        raise ValueError("private transaction source identity is unavailable")
                self._assert_work_attempt_fence(
                    _work_attempt_fence, task_id=_work_order_id or task_id, resource=fence_resource
                )
                if _work_order_id:
                    authorizer = getattr(self, "bounded_work_authorizer", None)
                    if not callable(authorizer) or authorizer(_work_order_id, task_id, str(cwd), original_command) is not True:
                        raise ValueError("work order does not authorize this task, root and command")
            except (AttributeError, OSError, TypeError, ValueError, RuntimeError) as exc:
                return {
                    "success": False,
                    "error": str(exc)[:512],
                    "failure_kind": "work_attempt_fence_invalid",
                    "mutation_fence_required": True,
                    "terminal": True,
                    "retryable": False,
                }
        if sandbox == "docker" and not is_mutating and not _transaction_context:
            if not shutil.which("docker"):
                return {
                    "success": False,
                    "error": "docker executable not found for sandbox mode",
                    "terminal": True,
                    "retryable": False,
                }
            abs_cwd = str(Path(cwd).resolve())
            command = f'docker run --rm -v "{abs_cwd}:/workspace" -w /workspace {docker_image} {command}'
        if task_id and self.policy_engine:
            budget = self.policy_engine.get_budget(task_id)
            if budget.is_exhausted():
                exhausted = ", ".join(
                    f"{channel}={used}/{maximum}"
                    for channel, used, maximum in (
                        ("tokens", budget.used_tokens, budget.max_tokens),
                        ("compute_seconds", budget.used_compute_seconds, budget.max_compute_seconds),
                        ("external_calls", budget.used_external_calls, budget.max_external_calls),
                    )
                    if used >= maximum
                )
                return {
                    "success": False,
                    "error": (
                        f"task budget exhausted ({exhausted}): task_id={task_id}, "
                        f"used_tokens={budget.used_tokens}, max_tokens={budget.max_tokens}, "
                        f"used_compute_seconds={budget.used_compute_seconds}, "
                        f"max_compute_seconds={budget.max_compute_seconds}, "
                        f"used_external_calls={budget.used_external_calls}, "
                        f"max_external_calls={budget.max_external_calls}"
                    ),
                    "terminal": True,
                    "retryable": False,
                    "budget_exhausted": True,
                }
        try:
            key, state = self._key(
                command, cwd, classification,
                timeout=effective_timeout,
                tool_identity=tool_identity,
                phase_timings_ms=phase_timings_ms,
                project_config_digest=project_config_digest,
                project_env_fingerprint=project_env_fingerprint,
                argv_fingerprint=argv_fingerprint,
                cache_context=_cache_context,
            )
        except ValueError as exc:
            result = {
                "success": False,
                "error": str(exc),
                "classification": classification,
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, command)
        cache_lookup_started = time.perf_counter()
        cacheable = bool(classification["cacheable"]) and not is_mutating and not _transaction_context
        if cacheable and not force and not bypass_cache:
            cached = self._read_cached_command_result(self.success_cache, self.failure_cache, key)
            if isinstance(cached, dict):
                stale_key = key
                invalidate_repo_state = getattr(self.repo_state, "invalidate", None)
                if callable(invalidate_repo_state):
                    invalidate_repo_state(cwd)
                try:
                    if _cache_context:
                        key, state = self._key(
                            command, cwd, classification, timeout=effective_timeout, tool_identity=tool_identity, project_config_digest=project_config_digest, project_env_fingerprint=project_env_fingerprint, argv_fingerprint=argv_fingerprint, cache_context=_cache_context
                        )
                    else:
                        key, state = self._key(command, cwd, classification, timeout=effective_timeout, tool_identity=tool_identity, project_config_digest=project_config_digest, project_env_fingerprint=project_env_fingerprint, argv_fingerprint=argv_fingerprint)
                except ValueError:
                    cached = None
                else:
                    if key != stale_key:
                        cached = self._read_cached_command_result(self.success_cache, self.failure_cache, key)
            if isinstance(cached, dict):
                phase_timings_ms["result_cache_lookup_ms"] = round((time.perf_counter() - cache_lookup_started) * 1000, 3)
                self.hits += 1
                result = dict(cached)
                cached_timings = result.get("phase_timings_ms", {})
                result["phase_timings_ms"] = {**cached_timings, **phase_timings_ms}
                result.update({"cache_hit": True, "coalesced": False, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
                self._record_command_verification(
                    result,
                    task_id=task_id,
                    criterion=criterion or f"command:{self._safe_label(command)}",
                    command=command,
                    command_id=f"cache_{uuid.uuid4().hex}",
                    command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    repository_revision=str(state.get("fingerprint", "")),
                    duration_ms=float(result.get("duration_ms", 0) or 0),
                    cached=True,
                    project_alias=project_alias,
                    project_config_digest=project_config_digest,
                    project_environment_sha256=project_environment_sha256,
                    configured_command_sha256=configured_command_sha256,
                    caller_arguments_sha256=caller_arguments_sha256,
                    project_alias_required=project_alias_required,
                    repository_root=str(state.get("root") or cwd),
                )
                return self._compact(result, command)
        phase_timings_ms["result_cache_lookup_ms"] = round((time.perf_counter() - cache_lookup_started) * 1000, 3)

        singleflight = not is_mutating and not bypass_cache and not _transaction_context
        event: threading.Event | None = None
        owner = False
        if singleflight:
            refreshed_for_inflight = False
            while True:
                with self._lock:
                    event = self._inflight.get(key)
                    if event is None:
                        event = _CommandSingleflightEvent(); self._inflight[key] = event; owner = True
                        break
                    if refreshed_for_inflight:
                        owner = False; self.coalesced += 1
                        break
                invalidate_repo_state = getattr(self.repo_state, "invalidate", None)
                if not callable(invalidate_repo_state):
                    refreshed_for_inflight = True
                    continue
                invalidate_repo_state(cwd)
                try:
                    key, state = self._key(
                        command, cwd, classification,
                        timeout=effective_timeout,
                        tool_identity=tool_identity,
                        phase_timings_ms=phase_timings_ms,
                        project_config_digest=project_config_digest,
                        project_env_fingerprint=project_env_fingerprint,
                        argv_fingerprint=argv_fingerprint,
                        cache_context=_cache_context,
                    )
                except ValueError as exc:
                    return self._compact({
                        "success": False,
                        "error": str(exc),
                        "classification": classification,
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }, command)
                refreshed_for_inflight = True
        if singleflight and not owner:
            # A second agent should benefit from single-flight without being trapped
            # behind a very long build/test command. The owner keeps running and will
            # populate the cache; the waiter gets a bounded in-progress response.
            wait_budget = min(float(effective_timeout) + 5.0, self.coalesce_wait_seconds)
            if request_cancel_event is None:
                finished = event.wait(wait_budget)
            else:
                wait_deadline = time.monotonic() + wait_budget
                finished = event.is_set()
                while not finished and time.monotonic() < wait_deadline:
                    if request_cancel_event.is_set():
                        return {"success": False, "cancelled": True, "coalesced": True, "terminal": True, "retryable": False}
                    finished = event.wait(min(0.05, max(0.0, wait_deadline - time.monotonic())))
            if not finished:
                with self._lock:
                    self.coalesced_timeouts += 1
                    active = self._public_active(dict(self._active_commands.get(key, {})))
                return {
                    "success": False, "in_progress": True, "retryable": True,
                    "error": "identical command is still running in another agent; do not start a duplicate",
                    "classification": classification, "repo_state": state, "active": active,
                }
            with self._lock:
                last_result = self._last.get(key)
            if last_result is None:
                owner_result = getattr(event, "owner_result", None)
                waiter_result = {
                    "success": False,
                    "error": "command ended without a definitive cacheable result",
                    "outcome_unknown": True,
                    "fail_closed": True,
                    "retryable": False,
                    "cache_hit": False,
                    "coalesced": True,
                    "classification": classification,
                    "repo_state": state,
                }
                if isinstance(owner_result, Mapping):
                    if owner_result.get("error"):
                        waiter_result["error"] = str(owner_result["error"])
                    for flag in ("timed_out", "cancelled", "aborted_interactive", "cleanup_unconfirmed"):
                        if owner_result.get(flag):
                            waiter_result[flag] = True
                return self._compact(waiter_result, command)
            result = dict(last_result)
            result.update({"cache_hit": False, "coalesced": True, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
            return self._compact(result, command)

        # Acquire rollback handles only after every preflight and early-return path.
        # Otherwise a rejected task can retain the root directory handle on Windows.
        scope_paths = declared_paths
        if scope_paths is not None:
            scope_snapshot, scope_error = _snapshot_rollback_scope(cwd, scope_paths)
            if scope_error:
                key = "rollback_scope_required" if scope_error == "rollback paths are required" else "rollback_scope_invalid"
                return {"success": False, "error": scope_error, key: True, "terminal": True, "retryable": False}
            if rollback_on_failure and (_transaction_context or not is_mutating):
                rollback_state = scope_snapshot
            elif scope_snapshot is not None:
                _close_rollback_root(scope_snapshot.root_guard)
        elif rollback_on_failure:
            rollback_state, scope_error = _snapshot_rollback_scope(cwd, rollback_paths)
            if scope_error:
                key = "rollback_scope_required" if scope_error == "rollback paths are required" else "rollback_scope_invalid"
                return {"success": False, "error": scope_error, key: True, "terminal": True, "retryable": False}

        self.misses += 1
        started_wall = time.time()
        # Only the singleflight owner binds its transport lifetime to execution.
        # A disconnected waiter must never signal another request's process.
        cancel_event = request_cancel_event if request_cancel_event is not None else threading.Event()
        execution_id = uuid.uuid4().hex
        execution_key = key if singleflight else f"mutation:{execution_id}"
        with self._lock:
            self._active_commands[execution_key] = {
                "command": self._safe_label(command), "cwd": Path(cwd).name or str(Path(cwd)),
                "class": str(classification.get("class", "")),
                "started_at": started_wall,
                "timeout_seconds": effective_timeout, "execution_id": execution_id,
            }
            self._cancel_events[execution_key] = cancel_event
            self._active_cancel_keys[execution_key] = self._cancel_key(command, cwd)
        git_snapshot = None
        if snapshot:
            try:
                cp_rev = subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=cwd, capture_output=True, text=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if cp_rev.returncode == 0:
                    cp_untracked = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard"],
                        cwd=cwd, capture_output=True, text=True, check=False,
                        timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                    )
                    git_snapshot = {
                        "cwd": cwd,
                        "untracked": set(cp_untracked.stdout.splitlines()),
                    }
            except Exception:
                pass
        try:
            if (
                is_mutating
                or auto_fix
                or (rollback_on_failure and classification.get("class") == "unknown")
            ) and not _transaction_context:
                result = self._run_private_transaction(
                    command, cwd, task_id=task_id, paths=list(declared_paths or []),
                    timeout=effective_timeout, docker_image=docker_image,
                    cancel_event=cancel_event, log_callback=log_callback,
                    command_key=key, attempt_key=attempt_key,
                    work_attempt_fence=_work_attempt_fence,
                )
            elif _transaction_context:
                transaction_cwd = transaction_cwd or Path(cwd).resolve(strict=True)
                argv = self._transaction_docker_argv(
                    _transaction_context, transaction_cwd, original_command, docker_image,
                    read_only_mount=False,
                )
                result = self._execute(
                    argv, str(transaction_cwd), int(timeout or self.timeout),
                    cancel_event, log_callback=log_callback,
                )
                if result.get("timed_out") or result.get("cancelled") or result.get("cleanup_unconfirmed"):
                    if not self._transaction_stop_container(_transaction_context):
                        result.update({"success": False, "cleanup_unconfirmed": True, "outcome_unknown": True, "fail_closed": True, "retryable": False, "terminal": True})
            else:
                execute_options: dict[str, Any] = {}
                if argv_override is not None:
                    execute_options["argv_override"] = argv_override
                if project_env_overrides:
                    execute_options["env_overrides"] = project_env_overrides
                if _environment_overrides:
                    execute_options["environment_overrides"] = _environment_overrides
                if stdin is not None or input is not None:
                    execute_options["stdin"] = stdin if stdin is not None else input
                result = self._execute(
                    command,
                    cwd,
                    int(timeout or self.timeout),
                    cancel_event,
                    log_callback=log_callback,
                    **execute_options,
                )
            execution_timings = result.pop("phase_timings_ms", {})
            result["phase_timings_ms"] = {**phase_timings_ms, **execution_timings}
            # CPython compileall reports missing targets as a diagnostic while
            # still exiting 0. A green exit code must not hide that no target
            # was compiled.
            combined_output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
            compileall_command = " ".join(argv_override).lower() if argv_override is not None else command.lower()
            if result.get("success") and "compileall" in compileall_command and re.search(r"can't\s+list\s+['\"]?[^\r\n]+", combined_output, re.I):
                result.update({
                    "success": False,
                    "exit_code": 1,
                    "error": "compileall reported an unavailable target",
                    "terminal": True,
                    "retryable": False,
                    "target_missing": True,
                })
            if result.get("cleanup_unconfirmed"):
                self._mark_rollback_outcome_unknown(
                    result,
                    command_key=key,
                    attempt_key=attempt_key,
                    error=RuntimeError(str(result.get("error") or "process-tree cleanup unconfirmed")),
                    rollback_paths=scope_paths,
                )
            elif rollback_state is not None and rollback_on_failure and not result.get("success"):
                try:
                    _capture_rollback_postimages(rollback_state)
                    _restore_rollback_scope(cwd, rollback_state)
                    result["rolled_back"] = True
                except Exception as rb_exc:
                    self._mark_rollback_outcome_unknown(
                        result, command_key=key, attempt_key=attempt_key, error=rb_exc,
                        rollback_paths=rollback_paths,
                    )
            elif snapshot and git_snapshot:
                result["snapshot_taken"] = True
            result["diagnostics"] = self._extract_diagnostics(result)
            expected_no_match = self._expected_search_no_match(command, classification, result, argv_override)
            if not expected_no_match and not result.get("success") and not result.get("cancelled"):
                result["failed_tests"] = self._extract_failed_tests(result)
                result["error_distillation"] = self._distill_error(result)
                result["error_distillation_source"] = "deterministic"
            diag_paths = [d["path"] for d in result.get("diagnostics", []) if d.get("path")]
            if (
                not result.get("success")
                and not expected_no_match
                and (not result.get("cancelled") or result.get("outcome_unknown"))
                and self.incident_store is not None
                and not result.get("incident_recorded")
            ):
                try:
                    from .agent_incidents import ToolOutcome, _extract_root_cause_and_fix
                    outcome = ToolOutcome(
                        tool_name="command",
                        command=command,
                        error=(
                            f"rollback failed; filesystem outcome unknown: {result.get('rollback_error', '')}"
                            if result.get("outcome_unknown")
                            else str(result.get("error") or result.get("stderr") or ("exit code " + str(result.get("exit_code", 1))))
                        ),
                        exit_code=int(result.get("exit_code", 1)),
                        state_revision=str(state.get("fingerprint", "")),
                        repository_root=cwd,
                        timed_out=bool(result.get("timed_out")),
                        cancelled=bool(result.get("cancelled")),
                        metadata={"outcome_unknown": True, "rollback_error": result.get("rollback_error", "")} if result.get("outcome_unknown") else {},
                        affected_paths=tuple(
                            scope_paths or result.get("rollback_paths") or set(diag_paths)
                        ),
                    )
                    inc = self.incident_store.capture(outcome)
                    _, suggested_fix, _ = _extract_root_cause_and_fix(
                        outcome.error, outcome.tool_name, outcome.timed_out
                    )
                    if inc:
                        result["incident_id"] = inc.incident_id
                        result["incident_recorded"] = True
                    if inc and (inc.root_cause or inc.has_verified_fix() or suggested_fix):
                        result["remediation"] = {
                            "incident_id": inc.incident_id,
                            "root_cause": inc.root_cause,
                            "verified_fix": inc.verified_fix if inc.has_verified_fix() else None,
                            "suggested_fix": suggested_fix or None,
                            "confidence": inc.confidence,
                            "attempts": inc.attempts,
                        }
                except Exception:
                    pass

            if self.incident_store is not None and not expected_no_match:
                try:
                    target_paths = set(diag_paths)
                    for cp in state.get("changed_paths", []):
                        target_paths.add(str(cp))
                    # Historical incidents are actionable only when the current
                    # command failed; successful runs must not emit stale alarms.
                    if target_paths and not result.get("success") and not result.get("cancelled"):
                        regs = self.incident_store.find_regressions(
                            list(target_paths),
                            root=cwd,
                            state_revision=str(state.get("fingerprint") or ""),
                        )
                        if regs:
                            result["regression_warnings"] = regs
                    search_query = command
                    if not result.get("success") and result.get("error_distillation"):
                        search_query = f"{command} {result['error_distillation']}"
                    pitfalls = self.incident_store.find_negative_knowledge(query=search_query, limit=3, root=cwd)
                    if pitfalls:
                        result["known_pitfalls"] = [
                            {"incident_id": p.get("incident_id"), "root_cause": p.get("root_cause"), "verified_fix": p.get("verified_fix")}
                            for p in pitfalls if p.get("root_cause") or p.get("verified_fix")
                        ]
                except Exception:
                    pass

            raw = dict(result)
            uncertain_outcome = any(
                bool(result.get(flag))
                for flag in (
                    "timed_out", "cancelled", "aborted_interactive", "outcome_unknown",
                    "in_progress", "cleanup_unconfirmed", "output_capture_unconfirmed",
                    "log_callback_delivery_unconfirmed",
                )
            )
            if cacheable and not bypass_cache and not uncertain_outcome:
                (self.success_cache if result.get("success") else self.failure_cache).set(key, raw)
            if not result.get("outcome_unknown"):
                self._record_command_verification(
                    result,
                    task_id=task_id,
                    criterion=criterion or f"command:{self._safe_label(command)}",
                    command=command,
                    command_id=execution_id,
                    command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    repository_revision=str(state.get("fingerprint", "")),
                    duration_ms=float(result.get("duration_ms", 0) or 0),
                    project_alias=project_alias,
                    project_config_digest=project_config_digest,
                    project_environment_sha256=project_environment_sha256,
                    configured_command_sha256=configured_command_sha256,
                    caller_arguments_sha256=caller_arguments_sha256,
                    project_alias_required=project_alias_required,
                    repository_root=str(state.get("root") or cwd),
                )
            if not force and not bypass_cache and not is_mutating and not uncertain_outcome and self._non_retryable_failure(raw):
                raw.update({"terminal": True, "retryable": False})
                self.suppression_cache.set(attempt_key, raw)
            if singleflight:
                with self._lock:
                    if len(self._last) > 128:
                        old_keys = list(self._last.keys())[:64]
                        for k in old_keys:
                            self._last.pop(k, None)
                    if uncertain_outcome:
                        self._last.pop(key, None)
                    else:
                        self._last[key] = raw
            result.update({"cache_hit": False, "coalesced": False, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
        except subprocess.TimeoutExpired:
            timeout_result = {"success": False, "error": "command timed out", "timed_out": True, "classification": classification, "cache_hit": False}
            if rollback_state is not None:
                try:
                    _capture_rollback_postimages(rollback_state)
                    _restore_rollback_scope(cwd, rollback_state)
                    timeout_result["rolled_back"] = True
                except Exception as rb_exc:
                    self._mark_rollback_outcome_unknown(
                        timeout_result, command_key=key, attempt_key=attempt_key, error=rb_exc,
                        rollback_paths=scope_paths,
                    )
                    self._capture_rollback_unknown_incident(
                        timeout_result, command=command,
                        repository_revision=str(state.get("fingerprint", "")),
                    )
            return timeout_result
        finally:
            if rollback_state is not None:
                try:
                    _close_rollback_root(rollback_state.root_guard)
                except OSError:
                    pass
            with self._lock:
                if singleflight:
                    self._inflight.pop(key, None)
                self._active_commands.pop(execution_key, None)
                self._cancel_events.pop(execution_key, None)
                self._active_cancel_keys.pop(execution_key, None)
                if event is not None:
                    completed_result = locals().get("result")
                    if not isinstance(completed_result, dict):
                        completed_result = locals().get("timeout_result")
                    if isinstance(event, _CommandSingleflightEvent) and isinstance(completed_result, dict):
                        event.owner_result = dict(completed_result)
                    event.set()

        return self._finalize_run_result(
            result,
            command=command,
            cwd=cwd,
            execution_id=execution_id,
            task_id=task_id,
            auto_fix=auto_fix,
            max_repair_attempts=max_repair_attempts,
            criterion=criterion,
            declared_paths=declared_paths,
            effective_timeout=effective_timeout,
            fix_generator=fix_generator,
            docker_image=docker_image,
            work_attempt_fence=_work_attempt_fence,
            request_cancel_event=request_cancel_event,
        )

    def _finalize_run_result(
        self,
        result: dict[str, Any],
        *,
        command: str | CommandInvocation,
        cwd: str,
        execution_id: str,
        task_id: str,
        auto_fix: bool,
        max_repair_attempts: int,
        criterion: str,
        declared_paths: list[str] | None,
        effective_timeout: int,
        fix_generator: Any | None,
        docker_image: str,
        work_attempt_fence: WorkAttemptFence | None,
        request_cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if task_id and self.policy_engine:
            try:
                from .agent_policy import BudgetCost

                elapsed_s = float(result.get("duration_ms", 0) or 0) / 1000.0
                self.policy_engine.consume(
                    task_id,
                    BudgetCost(compute_seconds=elapsed_s, external_calls=1),
                )
            except Exception:
                # The command has run, but failed accounting cannot authorize a
                # positive receipt or silently turn durable state into memory state.
                result = {**result, "success": False, "budget_accounting_unavailable": True,
                          "error": "budget accounting unavailable", "terminal": True, "retryable": False}

        compacted = self._compact(result, command)
        compacted["execution_id"] = execution_id
        # Work orders own their model-call and time budgets. Do not introduce
        # an unaccounted nested inference during their broker validation.
        if work_attempt_fence is None and (request_cancel_event is None or not request_cancel_event.is_set()):
            evidence = self._local_diagnostic_context(compacted, cwd)
            if evidence is not None:
                compacted["local_diagnostic_status"] = "unavailable"
                diagnostic_started = time.monotonic()
                diagnosis = self._distill_error_with_model(
                    {"summary": evidence["summary"], "exit_code": compacted["exit_code"]},
                    cancel_event=request_cancel_event, timeout_seconds=10.0,
                )
                if diagnosis and (request_cancel_event is None or not request_cancel_event.is_set()):
                    compacted["local_diagnostic_status"] = "completed"
                    compacted["local_diagnostic"] = {
                        "text": diagnosis, "artifact_id": evidence["artifact_id"], "advisory": True,
                    }
                elif request_cancel_event is not None and request_cancel_event.is_set():
                    compacted["local_diagnostic_status"] = "cancelled"
                elif time.monotonic() - diagnostic_started >= 10.0:
                    compacted["local_diagnostic_status"] = "timed_out"
        if task_id:
            compacted["task_id"] = task_id
            if criterion:
                compacted["criterion"] = criterion
        if auto_fix and not compacted.get("success") and not compacted.get("cancelled"):
            repaired = self.repair_loop(
                command,
                cwd,
                max_attempts=max_repair_attempts,
                task_id=task_id,
                criterion=criterion,
                paths=declared_paths,
                timeout=effective_timeout,
                fix_generator=fix_generator,
                initial_result=compacted,
                docker_image=docker_image,
                _work_attempt_fence=work_attempt_fence,
            )
            repaired["execution_id"] = execution_id
            return repaired
        return compacted
