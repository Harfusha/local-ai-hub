"""Apply a previously verified release checkout to an existing installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).absolute().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / "src")]

from local_ai_hub.client import HubClient  # noqa: E402
from local_ai_hub.config import load_config  # noqa: E402
from local_ai_hub.state_lifecycle import read_state_version  # noqa: E402
from tools.auto_update import installed_version, managed_target  # noqa: E402
from tools.prepare_release import version_parts  # noqa: E402
from tools.setup import run, venv_python, verify_source_revision  # noqa: E402
from tools.setup_report import write_install_report  # noqa: E402
from tools.state_migrations import inspect_state_migration_path, restore_state_backup, run_state_migrations  # noqa: E402
from tools.update_transaction import (  # noqa: E402
    PAYLOAD_FILES, _has_link_component, has_unexpected_python_link, installation_update_lock, replace_install_payload,
    stop_existing_runtime, update_recovery_path,
)


def configured_state(install: Path) -> Path:
    config = load_config(install / "config.toml", probe_hardware=False)
    target = Path(os.path.expandvars(os.path.expanduser(config["setup"]["install_dir"]))).absolute()
    state = Path(os.path.expandvars(os.path.expanduser(config["server"]["state_dir"]))).absolute()
    if target != install or _has_link_component(state):
        raise ValueError("installed configuration does not identify an unlinked state directory for this installation")
    return state


def prepare_dependencies(python: Path, requirements: Path, wheel: Path, wheelhouse: Path) -> None:
    run([str(python), "-I", "-m", "pip", "--isolated", "download", "--only-binary=:all:",
         "--no-input", "--disable-pip-version-check", "--dest", str(wheelhouse),
         "-r", str(requirements), str(wheel)], timeout=600)


def install_runtime(python: Path, requirements: Path, wheel: Path, wheelhouse: Path, version: str) -> None:
    run([str(python), "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-input",
         "--disable-pip-version-check", "--find-links", str(wheelhouse), "-r", str(requirements), str(wheel)], timeout=300)
    run([str(python), "-I", "-m", "pip", "check"], timeout=90)
    actual = run([str(python), "-I", "-B", "-m", "local_ai_hub", "--version"], capture=True, timeout=30).stdout.strip()
    if actual != f"Local AI Hub {version}":
        raise ValueError(f"installed runtime version mismatch: expected {version}, got {actual!r}")


def start_service(install: Path, python: Path, version: str) -> None:
    config = install / "config.toml"
    run([str(python), str(install / "tools/service.py"), "start"], timeout=75,
        env={**os.environ, "LOCAL_AI_CONFIG": str(config)})
    client = HubClient(config_path=str(config), auto_start=False)
    ready = client.get("/ready", timeout=5, requires_heavy_work=False)
    if ready.get("ready") is not True or ready.get("version") != version:
        raise RuntimeError(f"service did not report readiness at version {version}: {ready}")


def install_candidate(source: Path, install: Path, state: Path, wheel: Path, version: str, previous: str) -> dict:
    with installation_update_lock(install):
        if installed_version(install) != previous or version_parts(version) <= version_parts(previous):
            raise ValueError("installation changed while preparing the update or candidate is not newer")
        if configured_state(install) != state:
            raise ValueError("configured state target changed while preparing the update")
        payload = [install / name for name in (*PAYLOAD_FILES, "src", "skills", "tools", ".venv", "config.toml")]
        recovery = update_recovery_path(install)
        if install.is_relative_to(state) or any(
            state.is_relative_to(path) or path.is_relative_to(state) for path in (*payload, recovery)
        ):
            raise ValueError("configured state overlaps the install payload or recovery directory")
        plan = inspect_state_migration_path(state)
        if plan["status"] == "initialize":
            raise ValueError("automatic updates require an existing versioned state directory")

        with tempfile.TemporaryDirectory(prefix="local-ai-hub-wheels-") as temporary:
            wheelhouse = Path(temporary)
            python = venv_python(install / ".venv")
            if has_unexpected_python_link(install, python):
                raise ValueError("installed runtime contains a linked Python path")
            prepare_dependencies(python, source / "requirements-core.txt", wheel, wheelhouse)
            return _activate(source, install, state, wheel, wheelhouse, version, previous, int(plan["version"]), recovery)


def _activate(source: Path, install: Path, state: Path, wheel: Path, wheelhouse: Path,
              version: str, previous: str, previous_state_version: int, recovery: Path) -> dict:
    venv = install / ".venv"
    previous_venv = recovery / ".venv"
    python = venv_python(venv)
    service = install / "tools/service.py"
    disabled = state / "service.disabled"
    was_disabled = disabled.exists()
    resume_service = (state / "service.managed").is_file() and not was_disabled
    service_touched = False
    payload_unchanged_or_restored = True
    start_attempted = False
    rollback_blocked = False
    migration: dict = {}
    failed_state: Path | None = None
    recovery.mkdir()
    (recovery / "update.json").write_text(json.dumps({
        "install": str(install), "state": str(state), "previous_state_version": previous_state_version,
        "previous_version": previous, "candidate_version": version,
    }, indent=2) + "\n", encoding="utf-8")

    def stop() -> tuple[bool, str]:
        nonlocal service_touched
        service_touched = True
        return stop_existing_runtime(install, python, service, run)

    def stop_before_swap() -> tuple[bool, str]:
        nonlocal payload_unchanged_or_restored
        stopped, detail = stop()
        payload_unchanged_or_restored = not stopped
        return stopped, detail

    def activate() -> tuple[bool, str]:
        nonlocal migration, start_attempted
        if configured_state(install) != state:
            raise ValueError("release defaults change the configured state path")
        os.replace(venv, previous_venv)
        shutil.copytree(previous_venv, venv, symlinks=True)
        install_runtime(python, install / "requirements-core.txt", wheel, wheelhouse, version)
        migration = run_state_migrations(state, backup_current=True)
        if resume_service:
            start_attempted = True
            start_service(install, python, version)
        elif not was_disabled:
            disabled.unlink(missing_ok=True)
        return True, "runtime and state verified"

    def restore() -> tuple[bool, str]:
        nonlocal rollback_blocked, failed_state
        rollback_blocked = True
        if start_attempted:
            stopped, detail = stop()
            if not stopped:
                return False, detail
        backups = migration.get("backups", [])
        if backups and (start_attempted or migration.get("status") == "migrated"):
            failed_state = restore_state_backup(state, Path(backups[0]))
        if read_state_version(state) != previous_state_version:
            return False, "previous state version could not be verified"
        if previous_venv.exists():
            if venv.exists():
                os.replace(venv, recovery / "failed-venv")
            os.replace(previous_venv, venv)
        rollback_blocked = False
        return True, "runtime and state restored"

    def confirm_payload_restored() -> None:
        nonlocal payload_unchanged_or_restored
        payload_unchanged_or_restored = True

    success, detail = replace_install_payload(
        source, install, install / "config.toml", PAYLOAD_FILES,
        before_commit=stop_before_swap, after_swap=activate, before_rollback=restore,
        after_rollback=confirm_payload_restored,
    )
    result = {"success": success, "message": detail, "backups": migration.get("backups", [])}
    if failed_state is not None:
        result["failed_candidate_state"] = str(failed_state)
    if not success and service_touched and not rollback_blocked:
        try:
            if not payload_unchanged_or_restored or installed_version(install) != previous:
                raise RuntimeError("payload rollback could not be confirmed")
            if read_state_version(state) != previous_state_version:
                raise RuntimeError("prior state version could not be confirmed")
            if resume_service:
                start_service(install, python, previous)
            elif not was_disabled:
                disabled.unlink(missing_ok=True)
            result["previous_install_restored"] = True
        except Exception as exc:
            result["restore_error"] = str(exc)
            rollback_blocked = True
    if rollback_blocked:
        result["recovery_directory"] = str(recovery)
    else:
        try:
            shutil.rmtree(recovery)
        except OSError as exc:
            result.update(recovery_directory=str(recovery), cleanup_error=str(exc))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install", type=Path)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("wheel_digest")
    parser.add_argument("revision")
    parser.add_argument("version")
    parser.add_argument("previous_version")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        install = args.install.absolute()
        managed_target(install)
        verify_source_revision(args.revision, source_root=SOURCE)
        if installed_version(SOURCE) != args.version or _has_link_component(args.wheel):
            raise ValueError("source version or wheel path is inconsistent with the verified release")
        with args.wheel.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != args.wheel_digest:
                raise ValueError("release wheel digest changed before installation")
        result = install_candidate(SOURCE, install, configured_state(install), args.wheel, args.version, args.previous_version)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result = {"success": False, "error": str(exc)}
    write_install_report(args.report, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
