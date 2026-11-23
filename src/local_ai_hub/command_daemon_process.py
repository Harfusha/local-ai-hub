from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any

from .command_jobs import (
    close_job_object,
    terminate_job_object,
    wait_windows_job_empty as _wait_windows_job_empty,
    windows_job_has_processes as _windows_job_has_processes,
)
from .process_utils import process_identity, terminate_tree

def _daemon_process_group_alive(process_group_id: int) -> bool:
    """Return true only when a POSIX process group can be verified as present."""
    if (
        os.name == "nt"
        or isinstance(process_group_id, bool)
        or not isinstance(process_group_id, int)
        or process_group_id <= 0
        or not hasattr(os, "killpg")
    ):
        return False
    try:
        os.killpg(process_group_id, 0)
    except PermissionError:
        return False
    except (OSError, NotImplementedError):
        return False
    return True
def _linux_group_member_owns_token(
    process_group_id: int,
    ownership_token_digest: str | None,
    proc_root: str | os.PathLike[str] = "/proc",
) -> bool:
    if (
        isinstance(process_group_id, bool)
        or not isinstance(process_group_id, int)
        or process_group_id <= 0
        or not isinstance(ownership_token_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", ownership_token_digest)
    ):
        return False
    marker_prefix = b"LOCAL_AI_HUB_DAEMON_OWNERSHIP_TOKEN="

    def signature(data: bytes) -> tuple[int, bytes] | None:
        end = data.rfind(b")")
        fields = data[end + 1 :].split() if end >= 0 else []
        if len(fields) <= 19:
            return None
        try:
            return int(fields[2]), fields[19]
        except (IndexError, ValueError):
            return None

    try:
        entries = os.scandir(proc_root)
    except OSError:
        return False
    inspected = 0
    try:
        for entry in entries:
            inspected += 1
            if inspected > 4096:
                return False
            if not entry.name.isdecimal():
                continue
            proc_dir = Path(proc_root) / entry.name
            try:
                with (proc_dir / "stat").open("rb") as stream:
                    before = signature(stream.read(4096))
                if before is None or before[0] != process_group_id:
                    continue
                with (proc_dir / "environ").open("rb") as stream:
                    environ = stream.read(128 * 1024 + 1)
                if len(environ) > 128 * 1024:
                    continue
                marker = next(
                    (
                        value[len(marker_prefix):]
                        for value in environ.split(b"\0")
                        if value.startswith(marker_prefix)
                    ),
                    None,
                )
                if marker is None or hashlib.sha256(marker).hexdigest() != ownership_token_digest:
                    continue
                with (proc_dir / "stat").open("rb") as stream:
                    after = signature(stream.read(4096))
                if after == before:
                    return True
            except (OSError, ValueError, TypeError):
                continue
    finally:
        entries.close()
    return False
def _daemon_process_group_owned(
    process_group_id: int, ownership_token_digest: str | None
) -> bool:
    """Require a stable Linux process-group member carrying our launch token."""
    if os.name == "nt" or not _daemon_process_group_alive(process_group_id):
        return False
    return _linux_group_member_owns_token(process_group_id, ownership_token_digest)
def _terminate_owned_linux_daemon_group(
    process_group_id: int, ownership_token_digest: str, *, grace_seconds: float = 1.5
) -> bool:
    """Stop only a Linux daemon group that still proves possession of its launch token."""
    if not _daemon_process_group_owned(process_group_id, ownership_token_digest):
        return False
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + max(0.1, min(float(grace_seconds), 2.0))
    while time.monotonic() < deadline:
        alive = _process_group_liveness(process_group_id)
        if alive is False:
            return True
        if alive is None:
            return False
        time.sleep(0.025)

    # Recheck the unforgeable launch marker immediately before signalling again;
    # a numeric PGID alone is never a process-tree capability.
    if not _daemon_process_group_owned(process_group_id, ownership_token_digest):
        return False
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        alive = _process_group_liveness(process_group_id)
        if alive is False:
            return True
        if alive is None:
            return False
        time.sleep(0.025)
    return _process_group_liveness(process_group_id) is False
def _process_exited_without_reaping(process: Any) -> bool:
    """Observe a POSIX child without releasing its process-group identity."""
    lock = getattr(process, "_waitpid_lock", None)
    if (os.name == "posix" and lock is not None and
            all(hasattr(os, name) for name in ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT"))):
        try:
            with lock:
                if process.returncode is not None:
                    return True
                info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                return info is not None and info.si_pid == process.pid
        except (OSError, ValueError, AttributeError):
            pass
    return process.poll() is not None
def _process_group_liveness(process_group_id: int) -> bool | None:
    """Return True/False only when POSIX can establish process-group liveness."""
    if (
        os.name != "posix"
        or isinstance(process_group_id, bool)
        or not isinstance(process_group_id, int)
        or process_group_id <= 1
    ):
        return None
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError):
        return None
    return True
def _process_leader_exited(pid: int) -> bool:
    """Prove leader absence; permission and platform uncertainty are not absence."""
    if os.name != "posix" or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError, ValueError):
        return False
    return False
class _RecoveredDaemonProcess:
    """Minimal poll/wait/kill facade for a daemon verified after a Hub restart."""

    def __init__(
        self, pid: int, identity: dict[str, Any], process_group_id: int | None = None,
        job_handle: int | None = None,
        ownership_token_digest: str | None = None,
    ):
        self.pid = pid
        self.identity = identity
        self.process_group_id = process_group_id
        self.ownership_token_digest = ownership_token_digest
        self._local_ai_job_handle = job_handle

    def poll(self) -> int | None:
        if os.name == "nt" and self._local_ai_job_handle:
            return 0 if _windows_job_has_processes(self._local_ai_job_handle) is False else None
        current_identity = process_identity(self.pid)
        if current_identity == self.identity:
            return None
        if (
            current_identity is None
            and self.process_group_id == self.pid
            and _process_leader_exited(self.pid)
            and _process_group_liveness(self.process_group_id) is True
            and _daemon_process_group_owned(
                self.process_group_id, self.ownership_token_digest
            )
        ):
            return None
        return 0

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(f"pid {self.pid}", timeout)
            time.sleep(0.025)
        return 0

    def kill(self) -> bool:
        if os.name != "nt" and sys.platform == "linux":
            if (
                self.process_group_id == self.pid
                and process_identity(self.pid) is None
                and _process_leader_exited(self.pid)
                and _process_group_liveness(self.process_group_id) is True
                and _daemon_process_group_owned(
                    self.process_group_id, self.ownership_token_digest
                )
            ):
                return bool(terminate_tree(
                    self.pid,
                    process_group=self.process_group_id,
                    grace_seconds=0.1,
                ))
        if os.name != "nt" and self.poll() is not None:
            return False
        raise OSError("no stable process-tree ownership handle")
def _stop_daemon_tree(info: dict[str, Any]) -> bool:
    """Stop a daemon tree through its live owner handle or process group."""
    process = info["process"]
    if os.name != "nt" and sys.platform == "linux":
        pgid = info.get("process_group_id")
        digest = info.get("ownership_token_digest")
        if (
            isinstance(pgid, int)
            and not isinstance(pgid, bool)
            and pgid > 1
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return _terminate_owned_linux_daemon_group(pgid, digest)
    if os.name != "nt" and isinstance(process, _RecoveredDaemonProcess):
        if sys.platform == "linux":
            pgid = info.get("process_group_id")
            digest = info.get("ownership_token_digest")
            if (
                isinstance(pgid, int)
                and not isinstance(pgid, bool)
                and pgid > 1
                and isinstance(digest, str)
                and _daemon_process_group_owned(pgid, digest)
            ):
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    return True
                except OSError:
                    return False
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if not _daemon_process_group_alive(pgid):
                        return True
                    time.sleep(0.05)
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    return True
                except OSError:
                    return False
                kill_deadline = time.monotonic() + 0.5
                while time.monotonic() < kill_deadline:
                    if _process_group_liveness(pgid) is False:
                        return True
                    time.sleep(0.02)
                return _process_group_liveness(pgid) is False
        # PID/start-time metadata cannot pin a POSIX group across restart.
        return False
    job_handle = getattr(process, "_local_ai_job_handle", None)
    if os.name == "nt" and isinstance(job_handle, int) and not isinstance(job_handle, bool):
        try:
            if not terminate_job_object(job_handle):
                return False
            if not _wait_windows_job_empty(job_handle):
                return False
            if not close_job_object(job_handle):
                return False
            process._local_ai_job_handle = None
            return True
        except Exception:
            return False
    if os.name != "nt":
        pid = info.get("pid")
        process_group_id = info.get("process_group_id")
        identity = info.get("identity")
        if (
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > 0
            and getattr(process, "pid", None) == pid
            and getattr(process, "_waitpid_lock", None) is not None
            and process_group_id == pid
            and isinstance(identity, dict)
            and identity.get("pid") == pid
        ):
            # The original Popen handle keeps the leader unreaped while the
            # captured identity and session PGID are checked and signalled.
            try:
                return bool(terminate_tree(
                    pid,
                    process_group=process_group_id,
                    expected_identity=identity,
                    grace_seconds=1.5,
                    process_handle=process,
                ))
            except Exception:
                return False
    # Numeric PID/PGID alone is not a continuously owned signal capability.
    return False
