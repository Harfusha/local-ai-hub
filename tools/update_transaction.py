"""Staged, rollback-capable replacement of the managed install payload."""

from __future__ import annotations

import hashlib
import fnmatch
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _tree_digest(root: Path, ignored: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    paths = (
        path for path in root.rglob("*")
        if not any(fnmatch.fnmatch(part, pattern) for part in path.relative_to(root).parts for pattern in ignored)
    )
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if _is_link(path):
            raise ValueError(f"update payload contains a link: {path}")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            digest.update(b"D\0" + relative + b"\0")
        elif stat.S_ISREG(info.st_mode):
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            raise ValueError(f"update payload contains an unsupported file: {path}")
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    if _is_link(path) or not path.is_file():
        raise ValueError(f"update payload is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stop_existing_runtime(
    install_dir: Path,
    python: Path,
    service_script: Path,
    runner: Callable[..., Any],
) -> tuple[bool, str]:
    """Require an observed successful stop whenever managed runtime files exist."""
    runtime_present = any(
        path.exists() or _is_link(path)
        for path in (install_dir / "src", install_dir / "tools", install_dir / ".venv")
    )
    if not runtime_present:
        return True, "no existing managed runtime"
    if _is_link(python) or _is_link(service_script) or not python.is_file() or not service_script.is_file():
        return False, "existing runtime cannot be stopped with its managed Python and service script"
    try:
        result = runner([str(python), str(service_script), "stop"], check=False, timeout=20)
    except Exception as exc:
        return False, f"managed runtime stop failed: {exc}"
    returncode = getattr(result, "returncode", None)
    if returncode != 0:
        return False, f"managed runtime stop was not confirmed (exit={returncode!r})"
    return True, "managed runtime stop confirmed"


def replace_install_payload(
    source_root: Path,
    install_dir: Path,
    config_source: Path,
    file_names: tuple[str, ...],
    *,
    ignored: tuple[str, ...] = ("__pycache__", "*.pyc", ".pytest_cache"),
    before_commit: Callable[[], tuple[bool, str]] | None = None,
) -> tuple[bool, str]:
    """Stage and verify all payload, then swap with rollback on any failure."""
    if _is_link(install_dir):
        return False, f"install directory is a link; update refused: {install_dir}"
    entries: list[tuple[Path, Path, bool]] = []
    for name in ("src", "skills", "tools"):
        source, target = source_root / name, install_dir / name
        if source.resolve() != target.resolve():
            entries.append((source, target, True))
    for name in file_names:
        source, target = source_root / name, install_dir / name
        if source.is_file() and source.resolve() != target.resolve():
            entries.append((source, target, False))
    if config_source.is_file():
        target = install_dir / "config.toml"
        if config_source.resolve() != target.resolve():
            entries.append((config_source, target, False))

    for source, target, is_tree in entries:
        if target.parent != install_dir or target.name in {".venv", "state", "models", ".local-ai-hub-skill-ownership.json"}:
            return False, f"unsafe update target rejected: {target}"
        if _is_link(target):
            return False, f"update target is a link; update refused: {target}"
        if not source.exists() or _is_link(source):
            return False, f"update source is missing or a link: {source}"
        if is_tree and not source.is_dir():
            return False, f"update source is not a directory: {source}"
        if not is_tree and not source.is_file():
            return False, f"update source is not a file: {source}"
    try:
        source_digests = {
            source: _tree_digest(source, ignored) if is_tree else _file_digest(source)
            for source, _target, is_tree in entries
        }
    except (OSError, ValueError) as exc:
        return False, f"update source verification failed before staging: {exc}"

    stage_root: Path | None = None
    try:
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        stage_root = Path(tempfile.mkdtemp(prefix=f".{install_dir.name}.update-stage-", dir=install_dir.parent))
        payload_root, backup_root = stage_root / "payload", stage_root / "backup"
        payload_root.mkdir()
        backup_root.mkdir()
    except OSError as exc:
        if stage_root is not None:
            shutil.rmtree(stage_root, ignore_errors=True)
        return False, f"could not create update staging area; install unchanged: {exc}"
    if stage_root is None:
        return False, "could not create update staging area; install unchanged"
    moved_old: list[tuple[Path, Path]] = []
    moved_new: list[tuple[Path, Path, str, bool]] = []
    install_dir_created = False
    commit_complete = False
    stop_detail = ""
    try:
        for source, target, is_tree in entries:
            staged = payload_root / target.name
            if is_tree:
                shutil.copytree(source, staged, ignore=shutil.ignore_patterns(*ignored), symlinks=False)
                if source_digests[source] != _tree_digest(staged, ignored):
                    raise OSError(f"staged directory verification failed: {source}")
            else:
                shutil.copy2(source, staged)
                if source_digests[source] != _file_digest(staged):
                    raise OSError(f"staged file verification failed: {source}")

        if before_commit is not None:
            stopped, stop_detail = before_commit()
            if not stopped:
                return False, f"update blocked before live install swap or service start: {stop_detail}"
        install_dir_created = not install_dir.exists()
        install_dir.mkdir(parents=True, exist_ok=True)
        if _is_link(install_dir):
            raise OSError(f"install directory became a link during update: {install_dir}")
        for source, target, is_tree in entries:
            staged, backup = payload_root / target.name, backup_root / target.name
            if _is_link(target):
                raise OSError(f"update target became a link during swap: {target}")
            if target.exists():
                os.replace(target, backup)
                moved_old.append((backup, target))
            os.replace(staged, target)
            moved_new.append((target, staged, source_digests[source], is_tree))
        commit_complete = True
    except Exception as exc:
        rollback_errors: list[str] = []
        for target, staged, expected_digest, is_tree in reversed(moved_new):
            try:
                if target.exists() or _is_link(target):
                    if _is_link(target):
                        raise OSError(f"replacement target became a link during rollback: {target}")
                    actual_digest = _tree_digest(target, ignored) if is_tree else _file_digest(target)
                    if actual_digest != expected_digest:
                        raise OSError(f"replacement target changed during rollback: {target}")
                    os.replace(target, staged)
            except (OSError, ValueError) as rollback_exc:
                rollback_errors.append(f"could not move replacement {target}: {rollback_exc}")
        for backup, target in reversed(moved_old):
            try:
                if backup.exists() and not target.exists() and not _is_link(target):
                    os.replace(backup, target)
            except OSError as rollback_exc:
                rollback_errors.append(f"could not restore {target}: {rollback_exc}")
        recoverable = any(backup.exists() for backup, _target in moved_old)
        if not recoverable:
            if install_dir_created:
                try:
                    install_dir.rmdir()
                except OSError:
                    pass
            detail = "; rollback completed" if not rollback_errors else "; " + "; ".join(rollback_errors)
        else:
            detail = f"; recoverable backups retained at {backup_root}"
            if rollback_errors:
                detail += "; " + "; ".join(rollback_errors)
        return False, f"update payload transaction failed: {exc}{detail}"
    finally:
        if not commit_complete and not any(backup.exists() for backup, _target in moved_old):
            shutil.rmtree(stage_root, ignore_errors=True)

    try:
        shutil.rmtree(stage_root)
    except OSError as exc:
        return True, f"update payload installed; staging and prior backups retained at {stage_root}: {exc}"
    message = "update payload installed and staged verification passed"
    if stop_detail and stop_detail != "no existing managed runtime":
        message += f"; {stop_detail}"
    return True, message
