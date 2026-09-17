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
from local_ai_hub.client import HubClient
from local_ai_hub.config import load_config
from local_ai_hub.process_utils import find_listening_pid, hidden_run_kwargs, pid_alive, terminate_tree
from local_ai_hub.ollama import OllamaRuntime

ROOT_CONFIG = ROOT / "config.toml"
CFG = load_config(str(ROOT_CONFIG) if ROOT_CONFIG.is_file() else None)
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

def mark_disabled(disabled: bool) -> None:
    if disabled:
        DISABLED.write_text(f"disabled {time.time()}\n", encoding="utf-8")
    else:
        DISABLED.unlink(missing_ok=True)


def mark_managed() -> None:
    MANAGED.write_text(f"managed {time.time()}\n", encoding="utf-8")


def spawn_detached() -> None:
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
        return int((STATE / "supervisor.pid").read_text(encoding="utf-8").strip() or 0)
    except Exception:
        return 0


def kill_supervisor() -> None:
    pid = supervisor_pid()
    if pid <= 0:
        return
    try:
        terminate_tree(pid, grace_seconds=5.0)
    except Exception:
        pass




def hub_pid() -> int:
    try:
        return int((STATE / "hub.pid").read_text(encoding="utf-8").strip() or 0)
    except Exception:
        return 0


def managed_service_running() -> bool:
    if pid_alive(supervisor_pid()):
        return True
    port = int(CFG.get("server", {}).get("port", 11435))
    return bool(find_listening_pid(port))


def normalize_status(data: dict[str, object], *, supervisor_alive: bool, hub_alive: bool) -> dict[str, object]:
    """Replace active states left behind by a hard supervisor crash."""
    state = str(data.get("state", "stopped"))
    if state in {"running", "starting", "degraded", "cooldown"} and not supervisor_alive and not hub_alive:
        normalized = dict(data)
        normalized.update({
            "state": "stopped",
            "pid": 0,
            "hub_pid": 0,
            "last_error": "supervisor process not running",
        })
        return normalized
    return data

def kill_hub() -> None:
    pid = hub_pid()
    if pid > 0:
        try: terminate_tree(pid, grace_seconds=5.0)
        except Exception: pass
    port = int(CFG.get("server", {}).get("port", 11435))
    listening_pid = find_listening_pid(port)
    if listening_pid and listening_pid != os.getpid():
        try: terminate_tree(listening_pid, grace_seconds=5.0)
        except Exception: pass

def stop_managed_ollama() -> None:
    if not bool(CFG.get("headless", {}).get("stop_managed_ollama_on_stop", True)):
        return
    try: OllamaRuntime(CFG).stop_managed_server()
    except Exception: pass

def native_stop() -> None:
    mark_disabled(True)
    if os.name == "nt":
        run(["schtasks", "/Change", "/TN", "LocalAIHubSupervisor", "/DISABLE"])
    elif sys.platform == "darwin":
        dest = Path.home() / "Library/LaunchAgents/com.localai.hub.plist"
        run(["launchctl", "bootout", f"gui/{os.getuid()}", str(dest)])
    else:
        systemctl = shutil.which("systemctl")
        dest = Path.home() / ".config/systemd/user/local-ai-hub.service"
        if systemctl and dest.exists():
            run([systemctl, "--user", "stop", "local-ai-hub.service"])
    # Kill both layers explicitly. This also cleans up installations recovered from
    # an old/orphaned supervisor state instead of leaving a headless process behind.
    kill_supervisor()
    kill_hub()
    stop_managed_ollama()


def native_start() -> None:
    mark_managed()
    mark_disabled(False)
    if os.name == "nt":
        cp = run(["schtasks", "/Change", "/TN", "LocalAIHubSupervisor", "/ENABLE"])
        if cp.returncode == 0:
            run_cp = run(["schtasks", "/Run", "/TN", "LocalAIHubSupervisor"])
            if run_cp.returncode == 0:
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
    if action == "stop": native_stop(); print("stopped"); return 0
    if action == "start": native_start(); time.sleep(0.5); print("started"); return 0
    if action == "restart": native_stop(); time.sleep(0.5); native_start(); print("restarted"); return 0
    client = HubClient(tenant="service-control", config_path=_ACTIVE_CONFIG_ARG)
    status_path = STATE / "supervisor.status.json"
    try:
        data = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"state": "stopped"}
    except (OSError, ValueError):
        data = {"state": "stopped", "last_error": "invalid supervisor status"}
    online = client._online()
    normalized = normalize_status(
        data,
        supervisor_alive=pid_alive(supervisor_pid()),
        hub_alive=online or managed_service_running(),
    )
    print(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
    return 0 if online else 1


if __name__ == "__main__":
    raise SystemExit(main())
