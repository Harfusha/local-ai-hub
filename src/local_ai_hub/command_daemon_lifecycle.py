from __future__ import annotations

from collections.abc import Sequence
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
from typing import Any

from .command_daemon_process import _stop_daemon_tree
from .command_jobs import (
    assign_process_to_job,
    close_job_object,
    create_named_daemon_job as _create_named_daemon_job,
    daemon_job_name as _daemon_job_name,
    duplicate_job_handle_into_process as _duplicate_job_handle_into_process,
    terminate_job_object,
)
from .command_models import CommandInvocation
from .process_utils import (
    _resume_suspended_process,
    hidden_run_kwargs,
    process_identity,
)
from .state_paths import configured_state_dir

class CommandDaemonLifecycleMixin:
    def _stop_daemon(
        self, daemon_id: str, *, expected_task_id: str | None = None
    ) -> dict[str, Any]:
        """Terminate a background daemon process tree cleanly."""
        with self._daemons_lock:
            info = self._daemons.get(daemon_id)
            if not info:
                return {"success": False, "error": f"daemon not found: {daemon_id}"}
            if expected_task_id is not None and (
                not expected_task_id
                or not info.get("task_id")
                or info.get("task_id") != expected_task_id
            ):
                return {
                    "success": False,
                    "error": "daemon belongs to a different or unknown task",
                    "policy_blocked": True,
                    "terminal": True,
                    "retryable": False,
                }
            proc = info["process"]
            tree_stopped = info.get("process_tree_stopped") is True
            if not tree_stopped:
                try:
                    # The leader may have exited while descendants remain in its
                    # process group/tree; stop the owned tree even after leader exit.
                    tree_stopped = _stop_daemon_tree(info)
                except Exception:
                    tree_stopped = False
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    # Retry tree cleanup below; killing only the leader can orphan descendants.
                    pass
            if not tree_stopped:
                try:
                    tree_stopped = _stop_daemon_tree(info)
                except Exception:
                    tree_stopped = False
            if proc.poll() is None:
                return {
                    "success": False,
                    "daemon_id": daemon_id,
                    "status": "running",
                    "running": True,
                    "alive": True,
                    "process_tree_stopped": False,
                    "pid": info["pid"],
                    "tree_control_capability": info.get("tree_control_capability", "unsupported"),
                    "error": (
                        "stable daemon tree control is unsupported on this platform"
                        if info.get("tree_control_capability") == "unsupported"
                        else "daemon did not stop within the bounded termination window"
                    ),
                }
            if not tree_stopped:
                return {
                    "success": False,
                    "daemon_id": daemon_id,
                    "status": "cleanup_unconfirmed",
                    "running": False,
                    "alive": False,
                    "process_tree_stopped": False,
                    "pid": info["pid"],
                    "tree_control_capability": info.get("tree_control_capability", "unsupported"),
                    "error": (
                        "stable daemon tree control is unsupported on this platform"
                        if info.get("tree_control_capability") == "unsupported"
                        else "daemon leader stopped but process-tree cleanup could not be confirmed"
                    ),
                }
            info["process_tree_stopped"] = True
            timer = info.get("ttl_timer")
            if timer is not None:
                timer.cancel()
            reader = info.get("reader_thread")
            if reader is not None:
                reader.join(timeout=2.5)
            self._close_daemon_log(info)
            self._release_daemon_slot(info)
            info["stopped_at"] = time.time()
            if len(self._daemons) > 50:
                dead = [d for d, inf in self._daemons.items() if inf["process"].poll() is not None]
                if len(dead) > 20:
                    dead.sort(key=lambda d: float(self._daemons[d].get("stopped_at", self._daemons[d].get("started_at", 0))))
                    for old_d in dead[:len(dead) - 20]:
                        self._close_daemon_log(self._daemons[old_d])
                        self._daemons.pop(old_d, None)
            self._persist_daemon_registry()
            return {
                "success": True,
                "daemon_id": daemon_id,
                "status": "stopped",
                "running": False,
                "alive": False,
                "process_tree_stopped": True,
                "exit_code": proc.poll(),
            }
    def daemon_status(
        self, daemon_id: str | None = None, *, task_id: str | None = None
    ) -> dict[str, Any]:
        """Check status of one or all background daemons."""
        now = time.time()
        with self._daemons_lock:
            if daemon_id:
                info = self._daemons.get(daemon_id)
                if not info or (task_id is not None and info.get("task_id") != task_id):
                    return {"success": False, "error": f"daemon not found: {daemon_id}"}
                proc = info["process"]
                alive = proc.poll() is None
                if not alive:
                    tree_stopped = info.get("process_tree_stopped") is True
                    reader = info.get("reader_thread")
                    if reader is not None:
                        reader.join(timeout=0.2)
                    if reader is None or not reader.is_alive():
                        self._close_daemon_log(info)
                    if tree_stopped:
                        timer = info.get("ttl_timer")
                        if timer is not None:
                            timer.cancel()
                        self._release_daemon_slot(info)
                self._flush_daemon_log(info)
                with info.get("log_lock", threading.Lock()):
                    log_tail = bytes(info.get("log_buffer", b""))[-8192:].decode("utf-8", errors="replace")
                log_tail = "\n".join(log_tail.splitlines()[-30:])
                return {
                    "success": True,
                    "daemon_id": daemon_id,
                    "alive": alive,
                    "running": alive,
                    "pid": info["pid"],
                    "tree_control_capability": info.get("tree_control_capability", "unsupported"),
                    "status": "running" if alive else ("stopped" if info.get("process_tree_stopped") is True else "cleanup_unconfirmed"),
                    "process_tree_stopped": info.get("process_tree_stopped") is True,
                    "exit_code": proc.poll(),
                    "uptime_seconds": round(now - float(info["started_at"]), 1),
                    "owner_id": info.get("owner_id", ""),
                    "ttl_remaining_seconds": max(0.0, round(float(info.get("expires_at", now)) - now, 1)),
                    "name": info["name"],
                    "command": self._safe_label(info["command"]),
                    "log_tail": log_tail,
                }
            items = []
            for d_id, info in self._daemons.items():
                if task_id is not None and info.get("task_id") != task_id:
                    continue
                proc = info["process"]
                alive = proc.poll() is None
                if not alive:
                    tree_stopped = info.get("process_tree_stopped") is True
                    reader = info.get("reader_thread")
                    if reader is not None:
                        reader.join(timeout=0.2)
                    if reader is None or not reader.is_alive():
                        self._close_daemon_log(info)
                    if tree_stopped:
                        timer = info.get("ttl_timer")
                        if timer is not None:
                            timer.cancel()
                        self._release_daemon_slot(info)
                items.append({
                    "daemon_id": d_id,
                    "alive": alive,
                    "running": alive,
                    "pid": info["pid"],
                    "tree_control_capability": info.get("tree_control_capability", "unsupported"),
                    "status": "running" if alive else ("stopped" if info.get("process_tree_stopped") is True else "cleanup_unconfirmed"),
                    "process_tree_stopped": info.get("process_tree_stopped") is True,
                    "exit_code": proc.poll(),
                    "uptime_seconds": round(now - float(info["started_at"]), 1),
                    "owner_id": info.get("owner_id", ""),
                    "ttl_remaining_seconds": max(0.0, round(float(info.get("expires_at", now)) - now, 1)),
                    "name": info["name"],
                    "command": self._safe_label(info["command"]),
                })
            return {"success": True, "daemons": items, "count": len(items)}
    def spawn_daemon(
        self,
        command: str | Sequence[str],
        cwd: str,
        name: str = "",
        env: dict[str, str] | None = None,
        *,
        task_id: str = "",
    ) -> dict[str, Any]:
        """Spawn a detached background daemon process with bounded logging and lifecycle tracking."""
        argv, command_label, command_error = self._daemon_argv(command)
        if command_error or argv is None:
            return {"success": False, "error": command_error or "daemon command could not be parsed"}
        authorization = self.authorize_auxiliary_action(
            "spawn_daemon", endpoint="commands.spawn_daemon", task_id=task_id
        )
        if not authorization.get("allowed", False):
            return {
                "success": False,
                "error": authorization.get("reason", "daemon action denied by policy"),
                "policy": authorization,
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        invocation: str | CommandInvocation = (
            command
            if isinstance(command, str)
            else CommandInvocation(argv=argv, cwd=cwd, shell=False)
        )
        worktree_error = self._require_task_worktree(task_id, cwd, invocation)
        if worktree_error:
            return {
                "success": False,
                "error": worktree_error,
                "mutation_worktree_required": True,
                "terminal": True,
                "retryable": False,
            }
        classification_command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        classification = self.classify(classification_command)
        if classification.get("class") == "dangerous" or (
            not classification.get("allowed", False)
        ):
            return {
                "success": False,
                "error": f"daemon command blocked: {classification.get('reason', 'policy')}",
                "classification": classification,
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        if not isinstance(name, str) or len(name) > 128 or any(ord(ch) < 32 for ch in name):
            return {"success": False, "error": "daemon name must be a control-free string of at most 128 characters"}
        resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
        if not resolved_cwd.is_dir():
            return {"success": False, "error": f"working directory does not exist: {cwd}"}
        try:
            proc_env = self._daemon_environment(env)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        import uuid
        ownership_token_digest = None
        if sys.platform == "linux":
            ownership_token = uuid.uuid4().hex
            proc_env["LOCAL_AI_HUB_DAEMON_OWNERSHIP_TOKEN"] = ownership_token
            ownership_token_digest = hashlib.sha256(ownership_token.encode("ascii")).hexdigest()

        self._refresh_daemon_capacity()
        if not self._daemon_slots.acquire(blocking=False):
            return {"success": False, "error": "maximum active daemon count reached", "retryable": False}

        daemon_id = f"dmn_{uuid.uuid4().hex}"
        state_dir = configured_state_dir(self.config)
        log_dir = state_dir / "daemons"
        log_path = log_dir / f"{daemon_id}.log"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_fh = log_path.open("w+b")
        except OSError as exc:
            self._daemon_slots.release()
            return {"success": False, "error": f"could not prepare daemon log: {exc}"}
        read_fh = None
        write_fh = None

        kwargs: dict[str, Any] = {
            "cwd": str(resolved_cwd),
            "stdout": None,
            "stderr": subprocess.STDOUT,
            "env": proc_env,
        }
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        else:
            kwargs["start_new_session"] = True

        job_handle = None
        process = None
        job_name = _daemon_job_name(daemon_id) if os.name == "nt" else None
        try:
            if os.name == "nt":
                job_handle = _create_named_daemon_job(daemon_id)
                if not job_handle:
                    raise OSError("unable to create a named daemon Job Object")
            read_fd, write_fd = os.pipe()
            read_fh = os.fdopen(read_fd, "rb", buffering=0)
            write_fh = os.fdopen(write_fd, "wb", buffering=0)
            kwargs["stdout"] = write_fh
            launch_authorization = self.authorize_auxiliary_action(
                "spawn_daemon", endpoint="commands.spawn_daemon", task_id=task_id
            )
            if not launch_authorization.get("allowed", False):
                if job_handle:
                    close_job_object(job_handle)
                for handle in (read_fh, write_fh):
                    if handle is not None:
                        try:
                            handle.close()
                        except OSError:
                            pass
                log_fh.close()
                self._daemon_slots.release()
                try:
                    log_path.unlink()
                except OSError:
                    pass
                return {
                    "success": False,
                    "error": launch_authorization.get("reason", "daemon action denied by policy"),
                    "policy": launch_authorization,
                    "policy_blocked": True,
                    "terminal": True,
                    "retryable": False,
                }
            launch_worktree_error = self._require_task_worktree(
                task_id, resolved_cwd, invocation
            )
            if launch_worktree_error:
                raise OSError(
                    "registered task worktree changed before daemon launch: "
                    f"{launch_worktree_error}"
                )
            process = subprocess.Popen(argv, **kwargs)
            started_at = time.time()
            info = {
                "daemon_id": daemon_id,
                "process": process,
                "pid": process.pid,
                "process_group_id": process.pid,
                "identity": process_identity(process.pid),
                "job_name": job_name,
                "tree_control_capability": "named_job_object" if os.name == "nt" else "process_group",
                "owner_id": self._daemon_owner_id,
                "task_id": str(task_id),
                "name": name or daemon_id,
                "command": command_label,
                "cwd": str(resolved_cwd),
                "log_path": str(log_path),
                "log_fh": log_fh,
                "log_buffer": bytearray(),
                "log_lock": threading.Lock(),
                "_log_closed": False,
                "started_at": started_at,
                "expires_at": started_at + self.daemon_ttl_seconds,
                "_slot_acquired": True,
                "_slot_released": False,
                "reader_thread": None,
                "ownership_token_digest": ownership_token_digest,
            }
            if job_handle:
                process._local_ai_job_handle = job_handle
                if not assign_process_to_job(job_handle, process.pid):
                    raise OSError("unable to assign suspended daemon to its Job Object")
                resume_worktree_error = self._require_task_worktree(
                    task_id, resolved_cwd, invocation
                )
                if resume_worktree_error:
                    raise OSError(
                        "registered task worktree changed before daemon resume: "
                        f"{resume_worktree_error}"
                    )
                resume_authorization = self.authorize_auxiliary_action(
                    "spawn_daemon", endpoint="commands.spawn_daemon.resume", task_id=task_id
                )
                if not resume_authorization.get("allowed", False):
                    registry_persisted = False
                    try:
                        cleanup_confirmed = _stop_daemon_tree(info)
                    except Exception:
                        cleanup_confirmed = False
                    if cleanup_confirmed:
                        try:
                            process.wait(timeout=2.0)
                            cleanup_confirmed = process.poll() is not None
                        except Exception:
                            cleanup_confirmed = False
                    for handle in (read_fh, write_fh):
                        if handle is not None:
                            try:
                                handle.close()
                            except OSError:
                                pass
                    if cleanup_confirmed:
                        self._close_daemon_log(info)
                        self._daemon_slots.release()
                        try:
                            log_path.unlink()
                        except OSError:
                            pass
                    else:
                        registry_persisted = True
                        info["cleanup_unconfirmed"] = True
                        self._close_daemon_log(info)
                        with self._daemons_lock:
                            self._daemons[daemon_id] = info
                            registry_persisted = self._persist_daemon_registry()
                        if not registry_persisted:
                            cleanup_confirmed = self._retry_stop_unpersisted_daemon(daemon_id, info)
                            registry_persisted = bool(
                                info.get("registry_persisted", registry_persisted)
                            )
                            if cleanup_confirmed:
                                try:
                                    log_path.unlink()
                                except OSError:
                                    pass
                                self._daemon_slots.release()
                        try:
                            if not cleanup_confirmed:
                                self._schedule_daemon_expiry(info)
                        except RuntimeError:
                            info["ttl_stop_failed"] = True
                    return {
                        "success": False,
                        "error": resume_authorization.get("reason", "daemon action denied by policy"),
                        "policy": resume_authorization,
                        "policy_blocked": True,
                        "daemon_id": daemon_id if not cleanup_confirmed else None,
                        "cleanup_unconfirmed": not cleanup_confirmed,
                        "outcome_unknown": not cleanup_confirmed,
                        "registry_persisted": registry_persisted,
                        "terminal": True,
                        "retryable": False,
                    }
                if not isinstance(info.get("identity"), dict):
                    raise OSError("unable to establish daemon process identity before resume")
                with self._daemons_lock:
                    self._daemons[daemon_id] = info
                    if not self._persist_daemon_registry():
                        self._daemons.pop(daemon_id, None)
                        raise OSError("unable to persist daemon Job Object ownership before resume")
                if not _duplicate_job_handle_into_process(job_handle, process):
                    raise OSError("unable to anchor named daemon Job Object in daemon process")
                resume_worktree_error = self._require_task_worktree(
                    task_id, resolved_cwd, invocation
                )
                if resume_worktree_error:
                    raise OSError(
                        "registered task worktree changed before daemon resume: "
                        f"{resume_worktree_error}"
                    )
                if not _resume_suspended_process(process):
                    raise OSError("unable to resume suspended daemon process")
            write_fh.close()
            write_fh = None
        except (OSError, ValueError) as exc:
            if job_handle:
                terminate_job_object(job_handle)
            if process is not None:
                kill_fn = getattr(process, "kill", None)
                if callable(kill_fn):
                    try:
                        kill_fn()
                    except OSError:
                        pass
                wait_fn = getattr(process, "wait", None)
                if callable(wait_fn):
                    try:
                        wait_fn(timeout=2.0)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            if job_handle:
                close_job_object(job_handle)
            with self._daemons_lock:
                self._daemons.pop(daemon_id, None)
                self._persist_daemon_registry()
            for handle in (read_fh, write_fh):
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
            log_fh.close()
            self._daemon_slots.release()
            return {"success": False, "error": f"failed to spawn daemon: {exc}"}

        reader = threading.Thread(
            target=self._capture_daemon_output,
            args=(read_fh, info, self.daemon_log_max_bytes),
            name=f"local-ai-daemon-log-{daemon_id}",
            daemon=True,
        )
        info["reader_thread"] = reader
        with self._daemons_lock:
            if len(self._daemons) > 50:
                dead = [d for d, inf in self._daemons.items() if inf["process"].poll() is not None]
                if len(dead) > 20:
                    dead.sort(key=lambda d: float(self._daemons[d].get("stopped_at", self._daemons[d].get("started_at", 0))))
                    for old_d in dead[:len(dead) - 20]:
                        self._close_daemon_log(self._daemons[old_d])
                        self._daemons.pop(old_d, None)
            self._daemons[daemon_id] = info
        try:
            reader.start()
        except RuntimeError as exc:
            try:
                tree_stopped = _stop_daemon_tree(info)
            except Exception:
                tree_stopped = False
            if tree_stopped:
                try:
                    process.wait(timeout=2.0)
                    tree_stopped = process.poll() is not None
                except Exception:
                    tree_stopped = False
            try:
                read_fh.close()
            except OSError:
                pass
            info["reader_thread"] = None
            self._close_daemon_log(info)
            registry_persisted = True
            if not tree_stopped:
                info["cleanup_unconfirmed"] = True
                with self._daemons_lock:
                    registry_persisted = self._persist_daemon_registry()
                if not registry_persisted:
                    tree_stopped = self._retry_stop_unpersisted_daemon(daemon_id, info)
                    registry_persisted = bool(info.get("registry_persisted", registry_persisted))
                if not tree_stopped:
                    try:
                        self._schedule_daemon_expiry(info)
                    except RuntimeError:
                        info["ttl_stop_failed"] = True
                    return {
                        "success": False,
                        "error": f"failed to start daemon log reader and process cleanup is unconfirmed: {exc}",
                        "daemon_id": daemon_id,
                        "cleanup_unconfirmed": True,
                        "registry_persisted": registry_persisted,
                        "outcome_unknown": True,
                        "terminal": True,
                        "retryable": False,
                    }
            with self._daemons_lock:
                self._daemons.pop(daemon_id, None)
            self._release_daemon_slot(info)
            return {
                "success": False,
                "error": f"failed to start daemon log reader: {exc}",
                "registry_persisted": registry_persisted,
            }
        try:
            self._schedule_daemon_expiry(info)
        except RuntimeError as exc:
            stopped = self._stop_daemon(daemon_id)
            return {
                "success": False,
                "error": f"failed to schedule daemon TTL cleanup: {exc}",
                "daemon_id": daemon_id if not stopped.get("success") else None,
                "cleanup_success": bool(stopped.get("success")),
            }
        watcher = threading.Thread(
            target=self._watch_daemon_exit,
            args=(daemon_id, process),
            name=f"local-ai-daemon-watch-{daemon_id}",
            daemon=True,
        )
        info["watcher_thread"] = watcher
        try:
            watcher.start()
        except RuntimeError as exc:
            stopped = self._stop_daemon(daemon_id)
            return {
                "success": False,
                "error": f"failed to start daemon lifecycle watcher: {exc}",
                "cleanup_success": bool(stopped.get("success")),
            }
        with self._daemons_lock:
            registry_saved = self._persist_daemon_registry()
        if not registry_saved:
            stopped = self._stop_daemon(daemon_id)
            return {
                "success": False,
                "error": "daemon registry could not be written; newly started process was stopped",
                "cleanup_success": bool(stopped.get("success")),
            }

        return {
            "success": True,
            "daemon_id": daemon_id,
            "pid": process.pid,
            "name": name or daemon_id,
            "command": command_label,
            "status": "running",
            "log_path": str(log_path),
            "owner_id": self._daemon_owner_id,
            "ttl_seconds": self.daemon_ttl_seconds,
            "tree_control_capability": info.get("tree_control_capability", "unsupported"),
        }
    def stop_daemon(self, daemon_id: str, *, task_id: str = "") -> dict[str, Any]:
        authorization = self.authorize_auxiliary_action(
            "stop_daemon", endpoint="commands.stop_daemon", task_id=task_id
        )
        if not authorization.get("allowed", False):
            return {
                "success": False,
                "error": authorization.get("reason", "daemon action denied by policy"),
                "policy": authorization,
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        return self._stop_daemon(daemon_id, expected_task_id=task_id)
