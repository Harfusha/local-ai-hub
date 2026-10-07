from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import load_config
from .ollama import OllamaRuntime
from .llama_cpp_runtime import llama_cpp_managed_selected
from .process_utils import (
    close_pidfd,
    find_listening_pid,
    hidden_run_kwargs,
    open_pidfd,
    pid_alive,
    process_owner_record,
    process_owner_state,
    terminate_owned_process,
    terminate_process_handle,
)


def atomic_json(path: Path, data: dict[str, Any]) -> bool:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json_dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        for attempt in range(4):
            try:
                os.replace(tmp, path)
                return True
            except OSError:
                if attempt < 3:
                    time.sleep(0.02)
        return False
    except Exception:
        return False


class Supervisor:
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self.config_path = self.config["_config_path"]
        self.cfg = self.config.get("headless", {})
        self.state_dir = Path(self.config["server"]["state_dir"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pid_path = self.state_dir / "supervisor.pid"
        self.owner_path = self.state_dir / "supervisor.owner.json"
        self.lock_path = self.state_dir / "supervisor.lock"
        self.lock_guard_path = self.state_dir / "supervisor.lock.guard"
        self.status_path = self.state_dir / "supervisor.status.json"
        self.hub_pid_path = self.state_dir / "hub.pid"
        self.hub_owner_path = self.state_dir / "hub.owner.json"
        self.disabled_path = self.state_dir / "service.disabled"
        self.log_path = self.state_dir / "supervisor.log"
        self.runtime = OllamaRuntime(self.config)
        self.child: subprocess.Popen[Any] | None = None
        self.child_owner: dict[str, Any] | None = None
        self.child_pidfd: int | None = None
        self.child_ready = False
        self.stopping = False
        self.started_at = time.time()
        self.restarts = 0
        self.spawns = 0
        self.crashes: list[float] = []
        self._lock_fd: int | None = None
        self._log_lock = threading.RLock()

    def log(self, message: str) -> None:
        try:
            self._append_bounded_log(
                self.log_path,
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} {str(message)[:4096]}\n",
            )
        except OSError:
            pass

    def _append_bounded_log(self, path: Path, line: str, *, max_bytes: int = 1_000_000, backups: int = 3) -> None:
        encoded = line.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            encoded = encoded[: max_bytes - 1] + b"\n"
        with self._log_lock:
            try:
                current_size = path.stat().st_size
            except FileNotFoundError:
                current_size = 0
            if current_size + len(encoded) > max_bytes:
                path.with_name(f"{path.name}.{backups}").unlink(missing_ok=True)
                for index in range(backups - 1, 0, -1):
                    source = path.with_name(f"{path.name}.{index}")
                    if source.exists():
                        source.replace(path.with_name(f"{path.name}.{index + 1}"))
                if path.exists():
                    path.replace(path.with_name(f"{path.name}.1"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as log_file:
                log_file.write(encoded)

    def _drain_hub_stderr(self, stream: Any) -> None:
        stderr_path = self.state_dir / "logs" / "hub_stderr.log"
        try:
            while True:
                chunk = stream.readline(8192)
                if not chunk:
                    break
                self._append_bounded_log(stderr_path, chunk.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    @staticmethod
    def _read_owner(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _remove_stale_owner(self, pid_path: Path, owner_path: Path, role: str) -> None:
        if self._lock_fd is None:
            return
        owner = self._read_owner(owner_path)
        if owner is None or process_owner_state(owner, self.state_dir, role) != "stale":
            return
        try:
            current_owner = owner_path.read_text(encoding="utf-8")
            current_pid = pid_path.read_text(encoding="utf-8").strip()
            if current_owner == json_dumps(owner, ensure_ascii=False, separators=(",", ":")) and current_pid == str(owner.get("pid", "")):
                pid_path.unlink(missing_ok=True)
                owner_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _lock_guard(self) -> bool:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(self.lock_guard_path, flags, 0o600)
        except OSError:
            return False
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError):
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def _unlock_guard(self) -> None:
        fd = self._lock_fd
        self._lock_fd = None
        if fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass
        finally:
            os.close(fd)

    def acquire(self) -> bool:
        owner = process_owner_record(os.getpid(), self.state_dir, "supervisor")
        if owner is None or not self._lock_guard():
            return False
        acquired = False
        published_lock = False
        try:
            if self.lock_path.exists():
                raw = self.lock_path.read_text(encoding="utf-8")
                legacy_pid = 0
                legacy_format = False
                try:
                    existing = json.loads(raw)
                except (ValueError, TypeError):
                    legacy_format = True
                    try:
                        legacy_pid = int(raw.strip() or 0)
                    except ValueError:
                        return False
                    if legacy_pid and pid_alive(legacy_pid):
                        return False
                    existing = None
                state = process_owner_state(existing, self.state_dir, "supervisor")
                legacy_stale = legacy_format and (legacy_pid == 0 or not pid_alive(legacy_pid))
                if state == "owned" or (state == "unknown" and not legacy_stale):
                    return False
                # The OS guard serializes this stale-owner check and replacement.
                self.lock_path.unlink(missing_ok=True)
            if not atomic_json(self.lock_path, owner):
                return False
            published_lock = True
            if not atomic_json(self.owner_path, owner):
                return False
            self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
            acquired = True
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if not acquired:
                if published_lock:
                    try:
                        if self._read_owner(self.lock_path) == owner:
                            self.lock_path.unlink(missing_ok=True)
                        if self._read_owner(self.owner_path) == owner:
                            self.owner_path.unlink(missing_ok=True)
                        if self.pid_path.read_text(encoding="utf-8").strip() == str(owner["pid"]):
                            self.pid_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self._unlock_guard()

    def release_lock(self) -> None:
        try:
            owner = json.loads(self.lock_path.read_text(encoding="utf-8"))
            if process_owner_state(owner, self.state_dir, "supervisor") == "owned" and int(owner.get("pid", 0)) == os.getpid():
                self.lock_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        try:
            owner = self._read_owner(self.owner_path)
            if owner and int(owner.get("pid", 0)) == os.getpid() and process_owner_state(owner, self.state_dir, "supervisor") == "owned":
                self.pid_path.unlink(missing_ok=True)
                self.owner_path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError):
            pass
        self._unlock_guard()

    def _owned_hub_child(self) -> bool:
        child = self.child
        owner = self.child_owner
        if child is None or owner is None:
            return False
        try:
            if child.poll() is not None or int(owner.get("pid", 0)) != int(child.pid):
                return False
        except (OSError, TypeError, ValueError, AttributeError):
            return False
        return process_owner_state(owner, self.state_dir, "hub") == "owned"

    def hub_online(self) -> bool:
        if not self.child_ready or not self._owned_hub_child():
            return False
        server = self.config["server"]
        bind = str(server.get("bind", "127.0.0.1"))
        host = str(server.get("client_host", "")).strip() or ("127.0.0.1" if bind in {"0.0.0.0", "::", "[::]"} else bind)
        headers: dict[str, str] = {}
        token = str(self.config.get("security", {}).get("api_token", ""))
        if token:
            headers["X-LocalAI-Token"] = token
        try:
            timeout = max(0.1, min(5.0, float(self.cfg.get("health_probe_timeout_seconds", 2.0))))
            with urlopen(Request(f"http://{host}:{int(server.get('port', 11435))}/health", headers=headers), timeout=timeout) as response:
                if response.status != 200:
                    return False
            listener_pid = find_listening_pid(int(server.get("port", 11435)))
            return listener_pid == int(self.child.pid)
        except HTTPError as exc:
            # Admission-control 503 means the process is alive and intentionally
            # shedding load. Recycling it here would amplify overload into restart churn.
            return exc.code == 503
        except Exception:
            return False

    def hub_ready(self) -> bool:
        if not self._owned_hub_child():
            return False
        server = self.config["server"]
        bind = str(server.get("bind", "127.0.0.1"))
        host = str(server.get("client_host", "")).strip() or (
            "127.0.0.1" if bind in {"0.0.0.0", "::", "[::]"} else bind
        )
        headers: dict[str, str] = {}
        security = self.config.get("security", {})
        token = str(security.get("api_token", "") or "")
        if token:
            headers["X-LocalAI-Token"] = token
        try:
            timeout = max(0.1, min(3.0, float(self.cfg.get("readiness_probe_timeout_seconds", 1.0))))
            with urlopen(Request(f"http://{host}:{int(server.get('port', 11435))}/ready", headers=headers), timeout=timeout) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict) or payload.get("ready") is not True:
                    return False
            listener_pid = find_listening_pid(int(server.get("port", 11435)))
            return listener_pid == int(self.child.pid)
        except Exception:
            return False

    def write_status(self, state: str, error: str = "", ollama_online: bool | None = None) -> None:
        hub_pid = 0
        supervisor_owner = process_owner_record(os.getpid(), self.state_dir, "supervisor")
        if supervisor_owner:
            atomic_json(self.owner_path, supervisor_owner)
            self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        hub_owner = self.child_owner
        if self.child is not None and self.child.poll() is None:
            if hub_owner is None:
                hub_owner = process_owner_record(int(self.child.pid), self.state_dir, "hub")
                self.child_owner = hub_owner
            if hub_owner and process_owner_state(hub_owner, self.state_dir, "hub") == "owned":
                hub_pid = int(hub_owner["pid"])
        if not hub_pid:
            existing_hub_owner = self._read_owner(self.hub_owner_path)
            if existing_hub_owner and process_owner_state(existing_hub_owner, self.state_dir, "hub") == "owned":
                hub_owner = existing_hub_owner
                hub_pid = int(existing_hub_owner["pid"])
        if hub_pid and hub_owner:
            atomic_json(self.hub_owner_path, hub_owner)
            self.hub_pid_path.write_text(str(hub_pid), encoding="utf-8")
        else:
            self._remove_stale_owner(self.hub_pid_path, self.hub_owner_path, "hub")
        atomic_json(self.status_path, {
            "state": state,
            "pid": os.getpid(),
            "hub_pid": hub_pid,
            "supervisor_owner": supervisor_owner,
            "hub_owner": hub_owner if hub_pid else None,
            "hub_ready": self.hub_ready() if state != "stopping" else False,
            "heartbeat": time.time(),
            "started_at": self.started_at,
            "restarts": self.restarts,
            "last_error": str(error)[:240],
            "ollama_online": False if state == "stopping" else ollama_online,
        })

    def spawn_hub(self) -> subprocess.Popen[Any]:
        env = os.environ.copy()
        env["LOCAL_AI_CONFIG"] = self.config_path
        source_root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        py_exe = sys.executable
        if sys.platform == "win32":
            pyw_candidate = Path(sys.executable).parent / "pythonw.exe"
            if pyw_candidate.exists():
                py_exe = str(pyw_candidate)
        logs_dir = self.state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {
            "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE,
            **hidden_run_kwargs(detached=True),
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        return subprocess.Popen([py_exe, "-X", "utf8", "-m", "local_ai_hub.http_server"], **kwargs)

    def _persist_hub_owner(self, owner: dict[str, Any]) -> bool:
        if not atomic_json(self.hub_owner_path, owner):
            return False
        temp_pid = self.hub_pid_path.with_suffix(self.hub_pid_path.suffix + ".tmp")
        try:
            temp_pid.write_text(str(owner["pid"]), encoding="utf-8")
            os.replace(temp_pid, self.hub_pid_path)
            return True
        except OSError:
            try:
                temp_pid.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _start_child(self) -> subprocess.Popen[Any]:
        self.child_ready = False
        child = self.spawn_hub()
        self.child = child
        # Open pidfd before any poll/wait can reap a fast-exiting child.
        self.child_pidfd = open_pidfd(int(child.pid))
        owner = process_owner_record(int(child.pid), self.state_dir, "hub")
        self.child_owner = owner
        if owner is None or not self._persist_hub_owner(owner):
            stopped = terminate_process_handle(child, self.child_pidfd, grace_seconds=2.0)
            if stopped:
                close_pidfd(self.child_pidfd)
                self.child_pidfd = None
                self.child = None
                self.child_owner = None
                self._remove_stale_owner(self.hub_pid_path, self.hub_owner_path, "hub")
            else:
                self.log("hub child tracking failed; retained-handle termination unavailable")
            raise RuntimeError("could not persist hub process owner after spawn")
        stderr_stream = getattr(child, "stderr", None)
        if stderr_stream is not None:
            threading.Thread(target=self._drain_hub_stderr, args=(stderr_stream,), daemon=True).start()
        return child

    def terminate_child(self) -> bool:
        child = self.child
        if child is not None and child.poll() is None:
            if not terminate_process_handle(child, self.child_pidfd, grace_seconds=5.0):
                self.log("hub child not signaled; safe retained process handle unavailable")
                return False
        elif child is None:
            owner = self._read_owner(self.hub_owner_path)
            if owner and process_owner_state(owner, self.state_dir, "hub") == "owned":
                if not terminate_owned_process(owner, self.state_dir, "hub", grace_seconds=5.0):
                    self.log("hub owner not signaled; safe platform process handle unavailable")
                    return False
        if child is not None:
            try:
                child.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                if child.poll() is None:
                    return False
            close_pidfd(self.child_pidfd)
            self.child_pidfd = None
            self.child = None
            self.child_owner = None
            self.child_ready = False
        self._remove_stale_owner(self.hub_pid_path, self.hub_owner_path, "hub")
        return True

    def run(self) -> int:
        if bool(self.cfg.get("respect_disabled_marker", True)) and self.disabled_path.exists():
            return 0
        if not self.acquire():
            return 0
        if bool(self.cfg.get("respect_disabled_marker", True)) and self.disabled_path.exists():
            self.release_lock(); return 0
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        supervisor_owner = process_owner_record(os.getpid(), self.state_dir, "supervisor")
        if supervisor_owner:
            atomic_json(self.owner_path, supervisor_owner)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: setattr(self, "stopping", True))
            except Exception:
                pass

        interval = min(30.0, max(0.5, float(self.cfg.get("health_check_interval_seconds", 2.0))))
        unhealthy_grace = min(300.0, max(interval, float(self.cfg.get("unhealthy_grace_seconds", 20.0))))
        startup_grace = min(300.0, max(unhealthy_grace, float(self.cfg.get("startup_grace_seconds", 120.0))))
        initial_backoff = max(0.25, float(self.cfg.get("restart_backoff_initial_seconds", 1.0)))
        max_backoff = max(initial_backoff, float(self.cfg.get("restart_backoff_max_seconds", 30.0)))
        rapid_window = max(10.0, float(self.cfg.get("rapid_crash_window_seconds", 60.0)))
        rapid_limit = max(2, int(self.cfg.get("rapid_crash_limit", 8)))
        cooldown = max(5.0, float(self.cfg.get("rapid_crash_cooldown_seconds", 60.0)))
        backoff = initial_backoff
        unhealthy_since = 0.0
        self.log("supervisor started")
        try:
            while not self.stopping:
                if bool(self.cfg.get("respect_disabled_marker", True)) and self.disabled_path.exists():
                    self.log("disabled marker observed; stopping")
                    self.stopping = True
                    break
                if self.child is None:
                    try:
                        owner = find_listening_pid(int(self.config.get("server", {}).get("port", 11435)))
                    except Exception:
                        owner = None
                    if owner and int(owner) != os.getpid():
                        self.log(f"reaping stale hub listener pid {int(owner)} before managed start")
                        if not self.terminate_child():
                            self.log("hub listener retained; safe termination unavailable")
                            time.sleep(interval)
                            continue
                now = time.time()
                manage_ollama = bool(self.cfg.get("manage_ollama", True))
                manage_llama_cpp = llama_cpp_managed_selected(self.config)
                ollama_online = self.runtime.ensure_running() if manage_ollama or manage_llama_cpp else None
                if self.child_ready and self.hub_online():
                    unhealthy_since = 0.0
                    backoff = initial_backoff
                    self.write_status("running", ollama_online=ollama_online)
                    time.sleep(interval)
                    continue

                if unhealthy_since == 0.0:
                    unhealthy_since = now
                if self.child is not None and self.child.poll() is None and now - unhealthy_since < unhealthy_grace:
                    self.write_status("starting", ollama_online=ollama_online)
                    time.sleep(interval)
                    continue
                if self.child is not None and self.child.poll() is None:
                    self.log("hub unhealthy beyond grace; recycling")
                    if not self.terminate_child():
                        self.write_status("degraded", "safe hub termination unavailable", ollama_online=ollama_online)
                        time.sleep(backoff)
                        backoff = min(max_backoff, backoff * 2)
                        continue

                self.crashes = [t for t in self.crashes if now - t <= rapid_window]
                if len(self.crashes) >= rapid_limit:
                    self.write_status("cooldown", "rapid crash protection", ollama_online=ollama_online)
                    time.sleep(cooldown)
                    self.crashes.clear()
                    continue
                try:
                    is_restart = self.spawns > 0
                    self._start_child()
                    self.spawns += 1
                    if is_restart:
                        self.restarts += 1
                        self.crashes.append(now)
                    self.write_status("starting", ollama_online=ollama_online)
                except Exception as exc:
                    self.log(f"hub spawn failed: {type(exc).__name__}: {exc}")
                    self.write_status("degraded", type(exc).__name__, ollama_online=ollama_online)

                # Cold startup may initialize several local derived stores and model
                # metadata. Do not recycle a live child using the much shorter runtime
                # unhealthy grace; that creates a self-sustaining restart storm.
                deadline = time.time() + startup_grace
                while not self.stopping and time.time() < deadline:
                    if self.hub_ready():
                        self.child_ready = True
                        break
                    if self.child is not None and self.child.poll() is not None:
                        break
                    time.sleep(0.25)
                if not self.child_ready or not self.hub_online():
                    self.log("hub failed startup health check; recycling after backoff")
                    if not self.terminate_child():
                        self.write_status("degraded", "safe hub termination unavailable", ollama_online=ollama_online)
                        time.sleep(backoff)
                        backoff = min(max_backoff, backoff * 2)
                        continue
                    unhealthy_since = 0.0
                    self.write_status("degraded", "hub failed health check", ollama_online=ollama_online)
                    time.sleep(backoff)
                    backoff = min(max_backoff, backoff * 2)
        finally:
            self.write_status("stopping", ollama_online=False)
            if not self.terminate_child():
                self.log("shutdown left hub running; safe termination unavailable")
            self.release_lock()
            self.log("supervisor stopped")
        return 0


def main() -> int:
    config_path = os.environ.get("LOCAL_AI_CONFIG")
    if "--config" in sys.argv:
        try:
            config_path = sys.argv[sys.argv.index("--config") + 1]
        except IndexError:
            pass
    return Supervisor(config_path).run()


if __name__ == "__main__":
    raise SystemExit(main())
