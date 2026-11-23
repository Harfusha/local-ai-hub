from __future__ import annotations

from collections.abc import Sequence
import getpass
import hashlib
import json
import logging
import ntpath
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
from typing import Any
import uuid

from .command_daemon_process import (
    _RecoveredDaemonProcess,
    _daemon_process_group_owned,
    _process_group_liveness,
    _process_leader_exited,
    _stop_daemon_tree,
)
from .command_jobs import (
    close_job_object,
    daemon_job_name as _daemon_job_name,
    open_named_daemon_job as _open_named_daemon_job,
    windows_job_contains_process as _windows_job_contains_process,
    windows_job_has_processes as _windows_job_has_processes,
)
from .process_utils import process_identity

class CommandDaemonRegistryMixin:
    @classmethod
    def _capture_daemon_output(cls, read_fh: Any, info: dict[str, Any], max_bytes: int) -> None:
        try:
            while True:
                chunk = read_fh.read(64 * 1024)
                if not chunk:
                    break
                with info["log_lock"]:
                    buffer = info["log_buffer"]
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        del buffer[: len(buffer) - max_bytes]
        except (OSError, ValueError):
            pass
        finally:
            try:
                read_fh.close()
            except Exception:
                pass
            cls._flush_daemon_log(info)
    @classmethod
    def _close_daemon_log(cls, info: dict[str, Any]) -> None:
        """Close a daemon log handle exactly once, including natural exits."""
        if info.get("_log_closed"):
            return
        cls._flush_daemon_log(info)
        try:
            info["log_fh"].close()
        except Exception:
            pass
        info["_log_closed"] = True
    @classmethod
    def _daemon_argv(cls, command: str | Sequence[str]) -> tuple[list[str] | None, str, str | None]:
        if isinstance(command, str):
            if not command.strip() or len(command) > 8192:
                return None, "", "daemon command must be a non-empty string of at most 8192 characters"
            argv = cls._tokens(command)
            executable = ""
            if argv:
                executable = (ntpath.basename(argv[0]) if os.name == "nt" else Path(argv[0]).name).casefold()
            explicit_shells = {"sh", "bash", "dash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
            if cls._needs_shell(command) and executable not in explicit_shells:
                return None, "", "daemon command contains shell syntax; implicit shell execution is not allowed"
            label = cls._safe_label(command)
        elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
            if not command or len(command) > 128:
                return None, "", "daemon argv must contain 1 to 128 arguments"
            if any(not isinstance(arg, str) or "\x00" in arg or len(arg) > 8192 for arg in command):
                return None, "", "daemon argv entries must be NUL-free strings of at most 8192 characters"
            argv = list(command)
            if not argv[0]:
                return None, "", "daemon argv[0] must name an executable"
            if sum(len(arg.encode("utf-8")) for arg in argv) > 32 * 1024:
                return None, "", "daemon argv exceeds the 32 KiB size limit"
            label = cls._safe_label(shlex.join(argv))
        else:
            return None, "", "daemon command must be a string or structured argv list"
        if not argv:
            return None, "", "daemon command could not be parsed"
        return argv, label, None
    @staticmethod
    def _daemon_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
        """Inherit a minimal OS runtime environment; add only explicit, bounded overrides."""
        key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        inherited_allowlist = {
            "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
            "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "VIRTUAL_ENV", "LANG", "LANGUAGE", "TZ",
        }
        result = {
            key: value
            for key, value in os.environ.items()
            if key_pattern.fullmatch(key)
            and (key.upper() in inherited_allowlist or key.upper().startswith("LC_"))
            and isinstance(value, str)
            and "\x00" not in value
        }
        if extra is None:
            return result
        if not isinstance(extra, dict) or len(extra) > 128:
            raise ValueError("daemon environment must be a mapping with at most 128 entries")
        total_bytes = 0
        for key, value in extra.items():
            if not isinstance(key, str) or not key_pattern.fullmatch(key):
                raise ValueError("daemon environment contains an invalid variable name")
            normalized_key = key.upper()
            if normalized_key in {
                "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            } or normalized_key.startswith("GIT_CONFIG_"):
                raise ValueError("daemon environment cannot override Git repository paths")
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError(f"daemon environment value for {key} must be a NUL-free string")
            total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
            if len(key) > 255 or len(value) > 32_767 or total_bytes > 64 * 1024:
                raise ValueError("daemon environment exceeds the supported size limit")
            if os.name == "nt":
                for existing in list(result):
                    if existing.casefold() == key.casefold():
                        del result[existing]
            result[key] = value
        return result
    def _expire_daemon(self, daemon_id: str) -> None:
        for attempt in range(3):
            result = self._stop_daemon(daemon_id)
            if result.get("process_tree_stopped") is True or result.get("status") == "not_found":
                return
            if attempt < 2:
                time.sleep(0.25)
        with self._daemons_lock:
            info = self._daemons.get(daemon_id)
            if info is not None:
                info["ttl_stop_failed"] = True
    @staticmethod
    def _flush_daemon_log(info: dict[str, Any]) -> None:
        log_fh = info.get("log_fh")
        log_buffer = info.get("log_buffer")
        if log_fh is None or not isinstance(log_buffer, bytearray) or info.get("_log_closed"):
            return
        log_lock = info.get("log_lock")
        try:
            if log_lock is None:
                log_fh.seek(0)
                log_fh.truncate()
                log_fh.write(bytes(log_buffer))
                log_fh.flush()
            else:
                with log_lock:
                    log_fh.seek(0)
                    log_fh.truncate()
                    log_fh.write(bytes(log_buffer))
                    log_fh.flush()
        except (OSError, ValueError):
            pass
    @staticmethod
    def _get_daemon_owner_id() -> str:
        try:
            owner = getpass.getuser()
        except Exception:
            owner = f"uid:{os.getuid()}" if hasattr(os, "getuid") else "local-ai-hub"
        return hashlib.sha256(f"local-ai-daemon-owner:{owner}".encode("utf-8")).hexdigest()[:32]
    def _load_daemon_registry(self) -> None:
        """Reattach exact live leaders or Linux groups with a recorded launch marker."""
        registry = self._daemon_registry_path
        try:
            if registry.is_symlink() or registry.stat().st_size > 256 * 1024:
                return
            with registry.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        registry_version = payload.get("version")
        if type(registry_version) is not int or registry_version not in (2, 3, 4):
            return
        if os.name == "nt" and registry_version != 4:
            return  # Legacy Windows rows have no stable tree owner.
        if os.name != "nt" and registry_version == 4:
            return
        rows = payload.get("daemons")
        if not isinstance(rows, list):
            return
        expected_dir = self._daemon_state_dir.resolve(strict=False)
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            daemon_id = row.get("daemon_id")
            pid = row.get("pid")
            identity = row.get("identity")
            ownership_token_digest = row.get("ownership_token_digest")
            process_group_id = row.get("process_group_id")
            if (
                not isinstance(daemon_id, str)
                or not re.fullmatch(r"dmn_[0-9a-f]{32}", daemon_id)
                or isinstance(pid, bool)
                or not isinstance(pid, int)
                or not isinstance(identity, dict)
                or identity.get("pid") != pid
                or row.get("owner_id") != self._daemon_owner_id
            ):
                continue
            if registry_version == 2 and process_group_id is None:
                # Version 2 was emitted only after start_new_session/new_group.
                process_group_id = pid
            if (
                isinstance(process_group_id, bool)
                or not isinstance(process_group_id, int)
                or process_group_id != pid
            ):
                continue
            current_identity = process_identity(pid)
            leader_matches = current_identity == identity
            orphan_group_verified = (
                registry_version in (2, 3)
                and current_identity is None
                and _process_leader_exited(pid)
                and _process_group_liveness(process_group_id) is True
                and _daemon_process_group_owned(process_group_id, ownership_token_digest)
            )
            job_handle = None
            if os.name == "nt":
                job_name = row.get("job_name")
                if not isinstance(job_name, str) or job_name != _daemon_job_name(daemon_id):
                    continue
                job_handle = _open_named_daemon_job(job_name)
                if not job_handle:
                    continue
                if leader_matches:
                    tree_verified = _windows_job_contains_process(job_handle, pid, identity)
                else:
                    # A missing leader is acceptable only while the named Job
                    # Object itself still proves live owned members.
                    tree_verified = current_identity is None and _windows_job_has_processes(job_handle)
                if not tree_verified:
                    close_job_object(job_handle)
                    continue
            elif not (leader_matches or orphan_group_verified):
                continue
            if not self._daemon_slots.acquire(blocking=False):
                # A persisted PID is not a stable process-tree handle. Do not
                # signal it when this broker cannot adopt it.
                if job_handle:
                    close_job_object(job_handle)
                continue
            log_path = self._daemon_state_dir / f"{daemon_id}.log"
            log_fh = None
            try:
                if log_path.is_symlink() or log_path.resolve(strict=False).parent != expected_dir:
                    self._daemon_slots.release()
                    if job_handle:
                        close_job_object(job_handle)
                    continue
                log_fh = log_path.open("r+b")
                log_fh.seek(0, os.SEEK_END)
                size = log_fh.tell()
                log_fh.seek(max(0, size - self.daemon_log_max_bytes), os.SEEK_SET)
                log_buffer = bytearray(log_fh.read(self.daemon_log_max_bytes))
            except OSError:
                if log_fh is not None:
                    try:
                        log_fh.close()
                    except OSError as cleanup_error:
                        logging.getLogger(__name__).warning(
                            "Recovered daemon log cleanup failed (%s)",
                            type(cleanup_error).__name__,
                        )
                self._daemon_slots.release()
                if job_handle:
                    close_job_object(job_handle)
                continue
            try:
                started_at = float(row.get("started_at"))
                expires_at = float(row.get("expires_at"))
            except (TypeError, ValueError, OverflowError):
                log_fh.close()
                self._daemon_slots.release()
                if job_handle:
                    close_job_object(job_handle)
                continue
            if not (0 < started_at < float("inf") and started_at <= expires_at < float("inf")):
                log_fh.close()
                self._daemon_slots.release()
                if job_handle:
                    close_job_object(job_handle)
                continue
            name = row.get("name")
            command = row.get("command")
            info = {
                "daemon_id": daemon_id,
                "process": _RecoveredDaemonProcess(
                    pid, identity, process_group_id, job_handle,
                    ownership_token_digest=ownership_token_digest,
                ),
                "pid": pid,
                "process_group_id": process_group_id,
                "job_name": row.get("job_name") if os.name == "nt" else None,
                "tree_control_capability": "named_job_object" if os.name == "nt" else "unsupported",
                "identity": identity,
                "ownership_token_digest": ownership_token_digest,
                "owner_id": self._daemon_owner_id,
                "task_id": row.get("task_id") if isinstance(row.get("task_id"), str) else "",
                "name": self._safe_label(name) if isinstance(name, str) else daemon_id,
                "command": self._safe_label(command) if isinstance(command, str) else "",
                "cwd": "",
                "log_path": str(log_path),
                "log_fh": log_fh,
                "log_buffer": log_buffer,
                "log_lock": threading.Lock(),
                "reader_thread": None,
                "_log_closed": False,
                "started_at": started_at,
                "expires_at": expires_at,
                "_slot_acquired": True,
                "_slot_released": False,
            }
            self._daemons[daemon_id] = info
        for info in self._daemons.values():
            try:
                self._schedule_daemon_expiry(info)
            except RuntimeError:
                info["ttl_timer"] = None
    def _persist_daemon_registry(self) -> bool:
        """Atomically persist bounded, secret-redacted daemon identity metadata."""
        try:
            self._daemon_state_dir.mkdir(parents=True, exist_ok=True)
            registry = self._daemon_registry_path
            if registry.is_symlink():
                return False
            rows: list[dict[str, Any]] = []
            for daemon_id, info in self._daemons.items():
                process = info["process"]
                process_status = process.poll()
                pid = int(info["pid"])
                identity = info.get("identity")
                if not isinstance(identity, dict) or identity.get("pid") != pid:
                    continue
                current_identity = process_identity(pid)
                if os.name != "nt" and current_identity is not None and current_identity != identity:
                    continue
                process_group_id = info.get("process_group_id")
                group_verified = (
                    process_status is not None
                    and current_identity is None
                    and process_group_id == pid
                    and _daemon_process_group_owned(
                        process_group_id, info.get("ownership_token_digest")
                    )
                )
                if process_status is not None and not group_verified:
                    continue
                row = {
                    "daemon_id": daemon_id,
                    "pid": pid,
                    "identity": identity,
                    "owner_id": info["owner_id"],
                    "task_id": str(info.get("task_id", "")),
                    "name": self._safe_label(str(info.get("name", daemon_id)))[:128],
                    "command": self._safe_label(str(info.get("command", ""))),
                    "started_at": float(info["started_at"]),
                    "expires_at": float(info["expires_at"]),
                }
                if os.name == "nt":
                    job_name = info.get("job_name")
                    if not isinstance(job_name, str) or job_name != _daemon_job_name(daemon_id):
                        continue
                    row["job_name"] = job_name
                    row["process_group_id"] = pid
                if process_group_id == pid and os.name != "nt":
                    row["process_group_id"] = pid
                    digest = info.get("ownership_token_digest")
                    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                        row["ownership_token_digest"] = digest
                rows.append(row)
                if len(rows) >= 50:
                    break
            payload = json.dumps(
                {"version": 4 if os.name == "nt" else 3, "daemons": rows},
                ensure_ascii=True, separators=(",", ":")
            )
            temp_path = registry.with_name(f"registry.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, registry)
            except Exception:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise
            return True
        except (OSError, TypeError, ValueError, OverflowError):
            return False
    def _refresh_daemon_capacity(self) -> None:
        now = time.time()
        changed = False
        with self._daemons_lock:
            for info in self._daemons.values():
                if info["process"].poll() is None:
                    continue
                reader = info.get("reader_thread")
                if reader is not None:
                    reader.join(timeout=0.1)
                self._close_daemon_log(info)
                info.setdefault("stopped_at", now)
                self._release_daemon_slot(info)
                changed = True
            if changed:
                self._persist_daemon_registry()
    def _release_daemon_slot(self, info: dict[str, Any]) -> None:
        if not info.get("_slot_acquired") or info.get("_slot_released"):
            return
        info["_slot_released"] = True
        try:
            self._daemon_slots.release()
        except ValueError:
            pass
    def _retry_stop_unpersisted_daemon(self, daemon_id: str, info: dict[str, Any]) -> bool:
        """Retry one bounded stop when an unconfirmed daemon cannot be durably tracked."""
        try:
            stopped = _stop_daemon_tree(info)
        except Exception:
            stopped = False
        if not stopped:
            return False
        process = info.get("process")
        if process is None:
            return False
        try:
            if process.poll() is None:
                process.wait(timeout=2.0)
            if process.poll() is None:
                return False
        except Exception:
            return False
        with self._daemons_lock:
            self._daemons.pop(daemon_id, None)
            info["registry_persisted"] = self._persist_daemon_registry()
        return True
    def _schedule_daemon_expiry(self, info: dict[str, Any]) -> None:
        previous = info.get("ttl_timer")
        if previous is not None:
            previous.cancel()
        delay = max(0.0, float(info["expires_at"]) - time.time())
        timer = threading.Timer(delay, self._expire_daemon, args=(info["daemon_id"],))
        timer.daemon = True
        info["ttl_timer"] = timer
        timer.start()
    def _watch_daemon_exit(self, daemon_id: str, process: subprocess.Popen[Any]) -> None:
        """Reap descendants promptly when a daemon leader exits on its own."""
        while True:
            try:
                process.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
            except (OSError, ValueError):
                return
        status = self.daemon_status(daemon_id)
        if status.get("process_tree_stopped") is not True:
            self._expire_daemon(daemon_id)
