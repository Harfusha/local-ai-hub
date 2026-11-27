"""Check for releases and hand off desktop-confirmed updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .process_utils import hidden_run_kwargs


_VERSION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_CHECK_TTL = 30 * 60
_REPORT = "auto-update-report.json"


def _check_release(command: list[str]) -> dict:
    result = subprocess.run(
        [*command, "--json"], check=False, capture_output=True, text=True,
        encoding="utf-8", timeout=70, **hidden_run_kwargs(),
    )
    payload = json.loads(result.stdout)
    if result.returncode or not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError(payload.get("error", "Release check failed.") if isinstance(payload, dict) else "Invalid release check result.")
    return payload


def _launch(root: Path, command: list[str], job: str) -> None:
    env = os.environ.copy()
    if os.name == "nt":
        env.update(
            LOCAL_AI_UPDATE_TASK=job, LOCAL_AI_UPDATE_EXECUTABLE=command[0],
            LOCAL_AI_UPDATE_ARGUMENTS=subprocess.list2cmdline(command[1:]),
            LOCAL_AI_UPDATE_DIRECTORY=str(root),
        )
        script = """
$ErrorActionPreference = 'Stop'
$name = $env:LOCAL_AI_UPDATE_TASK
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and $existing.State -in @('Running', 'Queued')) { throw 'An update task is already active.' }
$action = New-ScheduledTaskAction -Execute $env:LOCAL_AI_UPDATE_EXECUTABLE -Argument $env:LOCAL_AI_UPDATE_ARGUMENTS -WorkingDirectory $env:LOCAL_AI_UPDATE_DIRECTORY
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $name
"""
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    elif sys.platform == "darwin":
        argv = ["launchctl", "submit", "-l", f"{job}-{time.time_ns()}", "--", *command]
    else:
        argv = ["systemd-run", "--user", "--collect", f"--unit={job}", "--", *command]
    result = subprocess.run(
        argv, cwd=root, env=env, check=False, capture_output=True,
        encoding="utf-8", errors="replace", text=True, timeout=20, **hidden_run_kwargs(),
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-1000:] or "The user service manager rejected the update.")


class DesktopUpdates:
    def __init__(self, config_path: str | None) -> None:
        prefix = Path(sys.prefix).absolute()
        self.root = prefix.parent
        script = self.root / "tools" / "auto_update.py"
        python = Path(sys._base_executable).absolute()
        if os.name == "nt" and python.name.lower() == "pythonw.exe":
            python = python.with_name("python.exe")
        self._command = [str(python), "-I", "-B", str(script)]
        try:
            self._eligible = (
                prefix.name == ".venv"
                and not any((directory / ".git").exists() for directory in (self.root, *self.root.parents))
                and Path(config_path or "").absolute() == self.root / "config.toml"
                and script.resolve(strict=True) == script
                and script.is_file()
                and python.is_file()
                and not python.is_relative_to(self.root)
            )
        except (OSError, RuntimeError):
            self._eligible = False
        self._lock = threading.Lock()
        self._check: dict = {"status": "not_checked"}
        self._checked = 0.0
        self._queued_at = 0.0
        self._thread: threading.Thread | None = None

    def _report(self) -> dict:
        path = self.root / _REPORT
        try:
            if path.resolve(strict=True) != path or not path.is_file():
                return {}
            with path.open(encoding="utf-8") as stream:
                result = json.loads(stream.read(65537))
            return result if isinstance(result, dict) else {}
        except (OSError, ValueError, RuntimeError):
            return {}

    @staticmethod
    def _report_time(report: dict) -> float:
        try:
            return datetime.fromisoformat(report.get("checked_at", "")).timestamp()
        except (TypeError, ValueError, OSError, OverflowError):
            return 0.0

    def _busy(self, report: dict) -> bool:
        stamp = self._report_time(report)
        now = time.time()
        if self._queued_at > stamp and now - self._queued_at < 3600:
            return True
        return report.get("status") == "installing" and now - stamp < 3600

    def _run_check(self) -> None:
        try:
            result = _check_release(self._command)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result = {"status": "check_failed", "error": str(exc)[:1000]}
        with self._lock:
            self._check = result

    def status(self, *, check: bool = True, refresh: bool = False) -> dict:
        if not self._eligible:
            return {"success": True, "eligible": False, "check": {"status": "unavailable"}}
        with self._lock:
            report = self._report()
            busy = self._busy(report)
            elapsed = time.monotonic() - self._checked
            if check and not busy and (self._thread is None or not self._thread.is_alive()) and (
                not self._checked or elapsed >= (15 if refresh else _CHECK_TTL)
            ):
                self._check = {"status": "checking"}
                self._checked = time.monotonic()
                self._thread = threading.Thread(target=self._run_check, name="desktop-release-check", daemon=True)
                self._thread.start()
            return {"success": True, "eligible": True, "check": dict(self._check), "report": report, "busy": busy}

    def install(self, version: str, revision: str) -> dict:
        if not self._eligible:
            raise ValueError("Dashboard updates require a managed installation.")
        with self._lock:
            if self._busy(self._report()):
                raise ValueError("An update is already running or queued.")
            if (
                not isinstance(version, str) or not _VERSION.fullmatch(version)
                or not isinstance(revision, str) or not _REVISION.fullmatch(revision)
                or self._check.get("status") != "update_available"
                or self._check.get("target_version") != version or self._check.get("revision") != revision
                or time.monotonic() - self._checked >= _CHECK_TTL
            ):
                raise ValueError("Check for updates and review the current candidate before installing.")
            command = [*self._command, "--apply", "--expect-version", version, "--expect-revision", revision]
            job = "local-ai-hub-update-" + hashlib.sha256(os.fsencode(self.root)).hexdigest()[:16]
            self._queued_at = time.time()
            try:
                _launch(self.root, command, job)
            except subprocess.TimeoutExpired:
                return {"success": True, "status": "launch_unknown"}
            except (OSError, RuntimeError):
                self._queued_at = 0.0
                raise
            self._check = {"status": "not_checked"}
            self._checked = 0.0
            return {"success": True, "status": "queued"}
