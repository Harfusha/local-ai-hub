from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from local_ai_hub.config import load_config
from local_ai_hub.client import HubClient
from local_ai_hub.process_utils import (
    find_listening_pid,
    hidden_run_kwargs,
    pid_alive,
    process_owner_record,
    process_owner_state,
    process_parent_pid,
    terminate_owned_process,
)
from local_ai_hub.ollama import OllamaRuntime

ROOT_CONFIG = ROOT / "config.toml"
CFG = load_config(os.environ.get("LOCAL_AI_CONFIG") or (str(ROOT_CONFIG) if ROOT_CONFIG.is_file() else None))
_ACTIVE_CONFIG = Path(str(CFG.get("_config_path", ""))).expanduser()
_ACTIVE_CONFIG_ARG = str(_ACTIVE_CONFIG) if _ACTIVE_CONFIG.is_file() else None
STATE = Path(CFG["server"]["state_dir"])
STATE.mkdir(parents=True, exist_ok=True)
DISABLED = STATE / "service.disabled"
MANAGED = STATE / "service.managed"
_venv_py = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = _venv_py if _venv_py.exists() else Path(sys.executable)
PYWIN = PY.with_name("pythonw.exe") if os.name == "nt" else PY
if os.name == "nt" and not PYWIN.exists():
    PYWIN = PY


def run(cmd: list[object], timeout: float = 12.0) -> subprocess.CompletedProcess[bytes]:
    argv = [str(x) for x in cmd]
    try:
        return subprocess.run(argv, check=False, timeout=max(1.0, timeout), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_run_kwargs())
    except subprocess.TimeoutExpired:
        # Service management is best-effort; never leave installer/control commands hung.
        return subprocess.CompletedProcess(argv, 124)
    except OSError:
        return subprocess.CompletedProcess(argv, 127)

def mark_disabled(disabled: bool) -> None:
    if disabled:
        DISABLED.write_text(f"disabled {time.time()}\n", encoding="utf-8")
    else:
        DISABLED.unlink(missing_ok=True)


def mark_managed() -> None:
    MANAGED.write_text(f"managed {time.time()}\n", encoding="utf-8")


def spawn_detached() -> None:
    if supervisor_pid() > 0:
        return
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        script_path = ROOT / "tools" / "service_entry.py"
        if powershell and script_path.exists():
            def psq(val: object) -> str:
                return "'" + str(val).replace("'", "''") + "'"
            cmdline = f'"{PYWIN}" "{script_path}"'
            if _ACTIVE_CONFIG_ARG:
                cmdline += f' --config "{_ACTIVE_CONFIG_ARG}"'
            script = (
                f"$proc = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
                f"-Arguments @{{CommandLine = {psq(cmdline)}; CurrentDirectory = {psq(str(ROOT))}}}; "
                f"exit [int]($proc.ReturnValue)"
            )
            cp = run([powershell, "-NoProfile", "-NonInteractive", "-Command", script], timeout=10.0)
            if cp.returncode == 0:
                return
    env = os.environ.copy()
    if _ACTIVE_CONFIG_ARG:
        env["LOCAL_AI_CONFIG"] = _ACTIVE_CONFIG_ARG
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    kwargs = {"env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, **hidden_run_kwargs(detached=True)}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    subprocess.Popen([str(PYWIN if os.name == "nt" else PY), "-X", "utf8", "-m", "local_ai_hub.supervisor"], **kwargs)


def supervisor_pid() -> int:
    try:
        pid = int((STATE / "supervisor.pid").read_text(encoding="utf-8").strip() or 0)
        owner = _read_owner("supervisor")
        if pid > 0 and owner and int(owner.get("pid", 0)) == pid and process_owner_state(owner, STATE, "supervisor") == "owned":
            return pid
    except Exception:
        pass
    return 0


def _read_owner(role: str) -> dict | None:
    try:
        value = json.loads((STATE / f"{role}.owner.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _role_stopped(role: str) -> bool:
    """Return true only when role PID metadata proves no live process remains."""
    pid_path = STATE / f"{role}.pid"
    try:
        pid_text = pid_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pid_text = ""
    except OSError:
        return False
    if not pid_text:
        owner = _read_owner(role)
        return not owner or process_owner_state(owner, STATE, role) == "stale"
    try:
        pid = int(pid_text)
    except ValueError:
        return False
    return pid <= 0 or not pid_alive(pid)


def all_supervisor_pids() -> list[int]:
    pids: set[int] = set()
    sup_pid = supervisor_pid()
    if sup_pid > 0 and pid_alive(sup_pid):
        pids.add(sup_pid)
    if os.name == "nt":
        try:
            script = "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*service_entry.py*' -or $_.CommandLine -like '*local_ai_hub.supervisor*' } | Select-Object -ExpandProperty ProcessId"
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=5.0, check=False, **hidden_run_kwargs()
            )
            for line in (cp.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit() and int(line) != os.getpid():
                    pids.add(int(line))
        except Exception:
            pass
    elif shutil.which("pgrep"):
        try:
            cp = subprocess.run(["pgrep", "-f", "local_ai_hub.supervisor"], capture_output=True, text=True, timeout=3.0, check=False)
            for line in (cp.stdout or "").splitlines():
                if line.strip().isdigit() and int(line.strip()) != os.getpid():
                    pids.add(int(line.strip()))
        except Exception:
            pass
    return list(pids)


def kill_supervisor() -> bool:
    owner = _read_owner("supervisor")
    if owner and process_owner_state(owner, STATE, "supervisor") == "owned":
        if not terminate_owned_process(owner, STATE, "supervisor", grace_seconds=5.0):
            return False
    return _role_stopped("supervisor")




def hub_pid() -> int:
    try:
        pid = int((STATE / "hub.pid").read_text(encoding="utf-8").strip() or 0)
        owner = _read_owner("hub")
        if pid > 0 and owner and int(owner.get("pid", 0)) == pid and process_owner_state(owner, STATE, "hub") == "owned":
            return pid
    except Exception:
        pass
    return 0


def managed_service_running() -> bool:
    if supervisor_pid() > 0 or hub_pid() > 0:
        return True
    port = int(CFG.get("server", {}).get("port", 11435))
    listening_pid = find_listening_pid(port)
    owner = _read_owner("hub")
    return bool(
        listening_pid
        and owner
        and int(owner.get("pid", 0)) == int(listening_pid)
        and process_owner_state(owner, STATE, "hub") == "owned"
    )

def kill_hub() -> bool:
    owner = _read_owner("hub")
    if owner and process_owner_state(owner, STATE, "hub") == "owned":
        launcher_pid = int(owner.get("pid", 0))
        listener_pid = find_listening_pid(int(CFG.get("server", {}).get("port", 11435))) or 0
        if not listener_pid:
            try:
                listener_pid = int((STATE / "hub.pid").read_text(encoding="utf-8").strip())
            except (FileNotFoundError, OSError, ValueError):
                listener_pid = 0
        if listener_pid > 0 and listener_pid != launcher_pid:
            # On Windows the venv pythonw launcher may own a second interpreter
            # process that hosts the HTTP listener. Stop it only when both its
            # parent and its process identity prove it belongs to this hub.
            if process_parent_pid(listener_pid) != launcher_pid:
                return False
            listener_owner = process_owner_record(listener_pid, STATE, "hub")
            if (
                listener_owner is None
                or process_owner_state(listener_owner, STATE, "hub") != "owned"
                or not terminate_owned_process(
                    listener_owner, STATE, "hub", grace_seconds=5.0
                )
            ):
                return False
        if not terminate_owned_process(owner, STATE, "hub", grace_seconds=5.0):
            return False
    return _role_stopped("hub")

def stop_managed_ollama() -> bool:
    if not bool(CFG.get("headless", {}).get("stop_managed_ollama_on_stop", True)):
        return True
    try:
        return bool(OllamaRuntime(CFG).stop_managed_server())
    except Exception:
        return False


def _service_manager_stop_result(backend: str, result: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    returncode = int(result.returncode)
    timed_out = returncode == 124
    reason = f"{backend}_stop_timeout" if timed_out else f"{backend}_stop_failed" if returncode else ""
    return {
        "backend": backend,
        "returncode": returncode,
        "success": returncode == 0,
        "timed_out": timed_out,
        "reason": reason,
    }

def _windows_user_startup_without_task() -> bool:
    """Verify the exact registry fallback; scheduler errors stay fail-closed."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False
    expected = f'"{PYWIN}" "{ROOT / "tools" / "service_entry.py"}"'
    script = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "try {",
        "  $scheduler = New-Object -ComObject Schedule.Service",
        "  $scheduler.Connect()",
        "  try { $null = $scheduler.GetFolder('\\').GetTask('LocalAIHubSupervisor'); exit 1 }",
        "  catch {",
        "    $errorObject = $_.Exception; $missing = $false",
        "    while ($null -ne $errorObject) {",
        "      if ($errorObject.HResult -eq -2147024894) { $missing = $true }",
        "      $errorObject = $errorObject.InnerException",
        "    }",
        "    if (-not $missing) { exit 1 }",
        "  }",
        "  $command = Get-ItemPropertyValue -LiteralPath 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name LocalAIHubSupervisor",
        "  if ($command -ceq '" + expected.replace("'", "''") + "') { exit 0 }",
        "  exit 1",
        "} catch { exit 1 }",
    ])
    return run([powershell, "-NoProfile", "-NonInteractive", "-Command", script]).returncode == 0


def native_stop() -> dict[str, object]:
    errors: list[str] = []
    manager: dict[str, object] = {"supported": True, "success": False, "timed_out": False}
    try:
        mark_disabled(True)
    except OSError:
        errors.append("disable_marker_write_failed")
    if os.name == "nt":
        result = run(["schtasks", "/Change", "/TN", "LocalAIHubSupervisor", "/DISABLE"])
        manager.update(_service_manager_stop_result("schtasks", result))
        if result.returncode not in (0, 124, 127) and _windows_user_startup_without_task():
            # The durable disabled marker gates this registration at startup.
            # Do not delete it: resume must preserve next-logon availability.
            manager.update(backend="windows-user-startup", returncode=0, success=True, reason="")
    elif sys.platform == "darwin":
        dest = Path.home() / "Library/LaunchAgents/com.localai.hub.plist"
        if not dest.is_file():
            manager.update(backend="launchctl", supported=False, reason="managed_launch_agent_not_installed")
        else:
            result = run(["launchctl", "bootout", f"gui/{os.getuid()}", str(dest)])
            manager.update(_service_manager_stop_result("launchctl", result))
    else:
        systemctl = shutil.which("systemctl")
        dest = Path.home() / ".config/systemd/user/local-ai-hub.service"
        if not systemctl or not dest.is_file():
            manager.update(backend="systemctl", supported=False, reason="managed_user_unit_not_installed")
        else:
            result = run([systemctl, "--user", "stop", "local-ai-hub.service"])
            manager.update(_service_manager_stop_result("systemctl", result))
    if manager.get("success") is not True:
        errors.append(str(manager.get("reason") or f"{manager.get('backend', 'service_manager')}_stop_failed"))
    supervisor_stopped = kill_supervisor()
    hub_stopped = kill_hub()
    if not supervisor_stopped:
        errors.append("supervisor_stop_unverified")
    if not hub_stopped:
        errors.append("hub_stop_unverified")
    port = int(CFG.get("server", {}).get("port", 11435))
    deadline = time.monotonic() + 2.0
    listener = find_listening_pid(port)
    while listener is not None and time.monotonic() < deadline:
        time.sleep(0.1)
        listener = find_listening_pid(port)
    if listener is not None:
        errors.append("hub_port_listener_remains")
    ollama_stopped = stop_managed_ollama()
    if not ollama_stopped:
        errors.append("managed_ollama_stop_unverified")
    stopped = supervisor_stopped and hub_stopped and listener is None and ollama_stopped
    return {
        "success": stopped and not errors,
        "stopped": stopped,
        "service_manager": manager,
        "supervisor_stopped": supervisor_stopped,
        "hub_stopped": hub_stopped,
        "managed_ollama_stopped": ollama_stopped,
        "port_listener_pid": listener,
        "errors": errors,
    }


def native_start() -> None:
    mark_managed()
    mark_disabled(False)
    if supervisor_pid() > 0:
        return
    if os.name == "nt":
        cp = run(["schtasks", "/Change", "/TN", "LocalAIHubSupervisor", "/ENABLE"])
        if cp.returncode == 0:
            run_cp = run(["schtasks", "/Run", "/TN", "LocalAIHubSupervisor"])
            if run_cp.returncode == 0:
                return
        # Task Scheduler can start the supervisor even when its control command
        # reports failure. Re-check before the fallback spawn to avoid duplicates.
        if supervisor_pid() > 0:
            return
        spawn_detached(); return
    if sys.platform == "darwin":
        dest = Path.home() / "Library/LaunchAgents/com.localai.hub.plist"
        if dest.exists():
            cp = run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(dest)])
            if cp.returncode == 0: return
        spawn_detached(); return
    systemctl = shutil.which("systemctl")
    dest = Path.home() / ".config/systemd/user/local-ai-hub.service"
    if systemctl and dest.exists():
        cp = run([systemctl, "--user", "start", "local-ai-hub.service"])
        if cp.returncode == 0: return
    spawn_detached()


def set_windows_user_startup(enabled: bool) -> bool:
    """Keep logon startup available when Task Scheduler requires elevation."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if enabled:
                command = f'"{PYWIN}" "{ROOT / "tools" / "service_entry.py"}"'
                winreg.SetValueEx(key, "LocalAIHubSupervisor", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "LocalAIHubSupervisor")
                except FileNotFoundError:
                    pass
        return True
    except (ImportError, OSError):
        return False


def install_windows() -> str:
    # Run one persistent supervisor at logon. Task Scheduler restarts the supervisor
    # after a crash; it does not launch a second singleton every minute.
    task = "LocalAIHubSupervisor"
    script_path = ROOT / "tools" / "service_entry.py"
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell:
        def psq(value: object) -> str:
            return "'" + str(value).replace("'", "''") + "'"
        script = "; ".join([
            f"$a=New-ScheduledTaskAction -Execute {psq(PYWIN)} -Argument {psq(str(script_path))} -WorkingDirectory {psq(str(ROOT))}",
            "$t=New-ScheduledTaskTrigger -AtLogOn",
            "$s=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable",
            f"Register-ScheduledTask -TaskName {psq(task)} -Action $a -Trigger $t -Settings $s -Force | Out-Null",
        ])
        cp = run([powershell, "-NoProfile", "-NonInteractive", "-Command", script])
        if cp.returncode == 0:
            set_windows_user_startup(False)
            run(["schtasks", "/Run", "/TN", task])
            return "windows-logon-task"
    command = f'"{PYWIN}" "{script_path}"'
    cp = run(["schtasks", "/Create", "/TN", task, "/TR", command, "/SC", "ONLOGON", "/RL", "LIMITED", "/F"])
    if cp.returncode != 0:
        # Task registration can be denied by a policy while an older managed task
        # is already running. Do not turn that recoverable control-plane failure
        # into a second detached supervisor competing for the same hub port.
        if set_windows_user_startup(True):
            if not managed_service_running():
                spawn_detached()
            return "windows-user-startup"
        if managed_service_running():
            return "existing-service"
        spawn_detached(); return "detached-fallback"
    set_windows_user_startup(False)
    run(["schtasks", "/Run", "/TN", task])
    return "windows-logon-task"


def install_macos() -> str:
    dest = Path.home() / "Library/LaunchAgents/com.localai.hub.plist"
    dest.parent.mkdir(parents=True, exist_ok=True)
    service_env = {"PYTHONPATH": str(ROOT / "src")}
    if _ACTIVE_CONFIG_ARG:
        service_env["LOCAL_AI_CONFIG"] = _ACTIVE_CONFIG_ARG
    payload = {
        "Label": "com.localai.hub",
        "ProgramArguments": [str(PY), "-m", "local_ai_hub.supervisor"],
        "RunAtLoad": True, "KeepAlive": True, "WorkingDirectory": str(ROOT), "ProcessType": "Background",
        "EnvironmentVariables": service_env,
    }
    with dest.open("wb") as fh:
        plistlib.dump(payload, fh)
    run(["launchctl", "bootout", f"gui/{os.getuid()}", str(dest)])
    cp = run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(dest)])
    if cp.returncode != 0:
        spawn_detached(); return "detached-fallback"
    return "launchd"


def install_linux() -> str:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        spawn_detached(); return "detached-fallback"
    dest = Path.home() / ".config/systemd/user/local-ai-hub.service"
    dest.parent.mkdir(parents=True, exist_ok=True)
    def sdq(value: object) -> str:
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'
    environment_lines = [f"Environment={sdq('PYTHONPATH=' + str(ROOT / 'src'))}"]
    if _ACTIVE_CONFIG_ARG:
        environment_lines.append(f"Environment={sdq('LOCAL_AI_CONFIG=' + _ACTIVE_CONFIG_ARG)}")
    unit = "\n".join([
        "[Unit]", "Description=Local AI Hub headless supervisor", "After=network.target", "",
        "[Service]", "Type=simple", f"WorkingDirectory={sdq(ROOT)}", *environment_lines,
        f"ExecStart={sdq(PY)} -m local_ai_hub.supervisor", "Restart=always", "RestartSec=2", "TimeoutStopSec=15", "",
        "[Install]", "WantedBy=default.target", "",
    ])
    dest.write_text(unit, encoding="utf-8")
    run([systemctl, "--user", "daemon-reload"])
    cp = run([systemctl, "--user", "enable", "--now", "local-ai-hub.service"])
    if cp.returncode != 0:
        spawn_detached(); return "detached-fallback"
    return "systemd-user"


def install() -> str:
    mark_managed()
    mark_disabled(False)
    if os.name == "nt": return install_windows()
    if sys.platform == "darwin": return install_macos()
    return install_linux()


def uninstall() -> None:
    mark_disabled(True)
    kill_supervisor()
    if os.name == "nt":
        set_windows_user_startup(False)
        run(["schtasks", "/Delete", "/TN", "LocalAIHubSupervisor", "/F"])
    elif sys.platform == "darwin":
        dest = Path.home() / "Library/LaunchAgents/com.localai.hub.plist"
        run(["launchctl", "bootout", f"gui/{os.getuid()}", str(dest)])
        dest.unlink(missing_ok=True)
    else:
        systemctl = shutil.which("systemctl")
        dest = Path.home() / ".config/systemd/user/local-ai-hub.service"
        if systemctl:
            run([systemctl, "--user", "disable", "--now", "local-ai-hub.service"])
            run([systemctl, "--user", "daemon-reload"])
        dest.unlink(missing_ok=True)
    MANAGED.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/control Local AI Hub headless supervisor")
    parser.add_argument("action", choices=["install", "start", "stop", "restart", "status", "uninstall"])
    action = parser.parse_args().action
    if action == "install": print(install()); return 0
    if action == "uninstall": uninstall(); print("uninstalled"); return 0
    if action == "stop":
        result = native_stop()
        if not result.get("success"):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 1
        print("stopped")
        return 0
    if action == "start": native_start(); time.sleep(0.5); print("started"); return 0
    if action == "restart":
        result = native_stop()
        if not result.get("success"):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 1
        time.sleep(0.5)
        native_start()
        print("restarted")
        return 0
    client = HubClient(tenant="service-control", config_path=_ACTIVE_CONFIG_ARG, auto_start=False)
    status_path = STATE / "supervisor.status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"state": "stopped"}
    except (OSError, ValueError):
        status = {"state": "unknown"}
    online = bool(client._online())
    status["hub_online"] = online
    if not online:
        # A supervisor status file can outlive its child after an abrupt stop.
        # Never report that stale state as running and never auto-start from a
        # read-only status command.
        if status.get("state") in {"running", "starting"}:
            status["state"] = "unavailable"
        status["last_error"] = status.get("last_error") or "hub endpoint unavailable"
        status["ollama_online"] = False
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if online else 1


if __name__ == "__main__":
    raise SystemExit(main())
