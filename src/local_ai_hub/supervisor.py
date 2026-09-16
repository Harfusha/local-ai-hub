from __future__ import annotations

import json
import os
import hashlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import load_config
from .ollama import OllamaRuntime
from .process_utils import find_listening_pid, pid_alive, terminate_tree, hidden_run_kwargs


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        for attempt in range(4):
            try:
                os.replace(tmp, path)
                break
            except OSError:
                if attempt < 3:
                    time.sleep(0.02)
    except Exception:
        pass


class Supervisor:
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self.config_path = self.config["_config_path"]
        self.cfg = self.config.get("headless", {})
        self.state_dir = Path(self.config["server"]["state_dir"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pid_path = self.state_dir / "supervisor.pid"
        self.lock_path = self.state_dir / "supervisor.lock"
        self.status_path = self.state_dir / "supervisor.status.json"
        self.disabled_path = self.state_dir / "service.disabled"
        self.log_path = self.state_dir / "supervisor.log"
        self.runtime = OllamaRuntime(self.config)
        self.child: subprocess.Popen[Any] | None = None
        self.stopping = False
        self.started_at = time.time()
        self.restarts = 0
        self.crashes: list[float] = []
        self._mutex_handle: int | None = None

    def log(self, message: str) -> None:
        try:
            if self.log_path.exists() and self.log_path.stat().st_size > 1_000_000:
                for idx in range(2, 0, -1):
                    src = self.log_path.with_name(f"supervisor.log.{idx}")
                    dst = self.log_path.with_name(f"supervisor.log.{idx + 1}")
                    if src.exists(): src.replace(dst)
                self.log_path.replace(self.log_path.with_name("supervisor.log.1"))
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass

    def acquire(self) -> bool:
        if os.name == "nt":
            try:
                import ctypes
                name_hash = hashlib.sha1(str(self.state_dir).lower().encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
                handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\LocalAIHubSupervisor-{name_hash}")
                if not handle or ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                    if handle:
                        ctypes.windll.kernel32.CloseHandle(handle)
                    return False
                self._mutex_handle = int(handle)
                self.lock_path.write_text(str(os.getpid()), encoding="utf-8")
                return True
            except Exception:
                # Fall back to the portable lock-file path below.
                pass
        for _ in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii")); os.close(fd)
                return True
            except FileExistsError:
                try:
                    pid = int(self.lock_path.read_text(encoding="utf-8").strip() or 0)
                    if pid_alive(pid):
                        return False
                    self.lock_path.unlink(missing_ok=True)
                except Exception:
                    return False
        return False

    def release_lock(self) -> None:
        if self._mutex_handle and os.name == "nt":
            try:
                import ctypes
                ctypes.windll.kernel32.ReleaseMutex(self._mutex_handle)
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def hub_online(self) -> bool:
        server = self.config["server"]
        bind = str(server.get("bind", "127.0.0.1"))
        host = str(server.get("client_host", "")).strip() or ("127.0.0.1" if bind in {"0.0.0.0", "::", "[::]"} else bind)
        headers: dict[str, str] = {}
        token = str(self.config.get("security", {}).get("api_token", ""))
        if token:
            headers["X-LocalAI-Token"] = token
        try:
            timeout = max(0.5, float(self.cfg.get("health_probe_timeout_seconds", 2.0)))
            with urlopen(Request(f"http://{host}:{int(server.get('port', 11435))}/health", headers=headers), timeout=timeout) as response:
                return response.status == 200
        except HTTPError as exc:
            # Admission-control 503 means the process is alive and intentionally
            # shedding load. Recycling it here would amplify overload into restart churn.
            return exc.code == 503
        except Exception:
            return False

    def write_status(self, state: str, error: str = "", ollama_online: bool | None = None) -> None:
        hub_pid = 0
        p = self.state_dir / "hub.pid"
        port_owner = find_listening_pid(int(self.config.get("server", {}).get("port", 11435)))
        if port_owner:
            hub_pid = int(port_owner)
            try:
                p.write_text(str(hub_pid), encoding="utf-8")
            except OSError:
                pass
        elif self.child is not None and self.child.poll() is None:
            hub_pid = int(self.child.pid)
            try:
                p.write_text(str(hub_pid), encoding="utf-8")
            except OSError:
                pass
        else:
            try:
                candidate = int(p.read_text(encoding="utf-8").strip() or 0)
                if pid_alive(candidate):
                    hub_pid = candidate
                else:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        atomic_json(self.status_path, {
            "state": state,
            "pid": os.getpid(),
            "hub_pid": hub_pid,
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
        kwargs: dict[str, Any] = {
            "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
            **hidden_run_kwargs(detached=True),
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        return subprocess.Popen([py_exe, "-X", "utf8", "-m", "local_ai_hub.http_server"], **kwargs)

    def terminate_child(self) -> None:
        target_pids: set[int] = set()
        child = self.child
        if child is not None and child.poll() is None:
            target_pids.add(int(child.pid))

        # Also reap port owner and hub.pid if child is not tracking it or port is still held
        port = int(self.config.get("server", {}).get("port", 11435))
        try:
            port_owner = find_listening_pid(port)
            if port_owner and int(port_owner) != os.getpid():
                target_pids.add(int(port_owner))
        except Exception:
            pass

        pid_file = self.state_dir / "hub.pid"
        if pid_file.exists():
            try:
                candidate = int(pid_file.read_text(encoding="utf-8").strip() or 0)
                if candidate and candidate != os.getpid() and pid_alive(candidate):
                    target_pids.add(candidate)
            except Exception:
                pass

        for pid in target_pids:
            try:
                terminate_tree(pid, grace_seconds=5.0)
            except Exception:
                pass

        if child is not None:
            try:
                child.wait(timeout=2.0)
            except Exception:
                try:
                    child.kill()
                    child.wait(timeout=1.0)
                except Exception:
                    pass
            self.child = None

        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    def run(self) -> int:
        if bool(self.cfg.get("respect_disabled_marker", True)) and self.disabled_path.exists():
            return 0
        if not self.acquire():
            return 0
        if bool(self.cfg.get("respect_disabled_marker", True)) and self.disabled_path.exists():
            self.release_lock(); return 0
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: setattr(self, "stopping", True))
            except Exception:
                pass

        interval = max(0.5, float(self.cfg.get("health_check_interval_seconds", 2.0)))
        unhealthy_grace = max(interval, float(self.cfg.get("unhealthy_grace_seconds", 20.0)))
        startup_grace = max(unhealthy_grace, float(self.cfg.get("startup_grace_seconds", 120.0)))
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
                now = time.time()
                manage_ollama = bool(self.cfg.get("manage_ollama", True))
                ollama_online = self.runtime.is_online() if manage_ollama else None
                if manage_ollama and not ollama_online:
                    self.runtime.ensure_running()
                    ollama_online = self.runtime.is_online()
                if self.hub_online():
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
                    self.terminate_child()

                self.crashes = [t for t in self.crashes if now - t <= rapid_window]
                if len(self.crashes) >= rapid_limit:
                    self.write_status("cooldown", "rapid crash protection", ollama_online=ollama_online)
                    time.sleep(cooldown)
                    self.crashes.clear()
                    continue
                try:
                    self.child = self.spawn_hub()
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
                    if self.hub_online():
                        break
                    if self.child is not None and self.child.poll() is not None:
                        break
                    time.sleep(0.25)
                if not self.hub_online():
                    self.log("hub failed startup health check; recycling after backoff")
                    self.terminate_child()
                    unhealthy_since = 0.0
                    self.write_status("degraded", "hub failed health check", ollama_online=ollama_online)
                    time.sleep(backoff)
                    backoff = min(max_backoff, backoff * 2)
        finally:
            self.write_status("stopping", ollama_online=False)
            self.terminate_child()
            try:
                self.pid_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.release_lock()
            self.log("supervisor stopped")
        return 0


def main() -> int:
    return Supervisor(os.environ.get("LOCAL_AI_CONFIG")).run()


if __name__ == "__main__":
    raise SystemExit(main())
