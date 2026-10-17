"""Safe ownership tracking for installed agent skill directories.

This module deliberately uses only the standard library so setup and uninstall
can use it before the Local AI Hub runtime is available.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MANIFEST_NAME = ".local-ai-hub-skill-ownership.json"
MANIFEST_VERSION = 1
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


_LOCK_TIMEOUT_SECONDS = 30.0
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


@contextmanager
def _ownership_lock(manifest: Path):
    """Serialize ownership-manifest and skill-tree mutations across threads/processes."""
    lock_path = manifest.with_name(manifest.name + ".lock")
    key = _canonical(lock_path)
    with _PATH_LOCKS_GUARD:
        thread_lock = _PATH_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock_path, flags, 0o600)
        acquired = False
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
                raise OSError(f"skill ownership lock is not a regular file: {lock_path}")
            if info.st_size == 0:
                os.write(fd, b"\\0")
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        acquired = True
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"timed out locking skill ownership manifest: {manifest}")
                        time.sleep(0.05)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"timed out locking skill ownership manifest: {manifest}")
                        time.sleep(0.05)
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _safe_tree_hash(root: Path) -> str:
    if _is_link(root) or not root.is_dir():
        raise ValueError(f"skill tree is not a safe directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if _is_link(path):
            raise ValueError(f"skill tree contains a link: {path}")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            digest.update(b"D\0" + relative.encode("utf-8") + b"\0")
        elif stat.S_ISREG(info.st_mode):
            digest.update(b"F\0" + relative.encode("utf-8") + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            raise ValueError(f"skill tree contains an unsupported file: {path}")
    return digest.hexdigest()


def _canonical(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _validate_manifest(manifest: Path) -> None:
    if manifest.name != MANIFEST_NAME:
        raise ValueError(f"unexpected skill ownership manifest path: {manifest}")
    cursor = manifest.parent
    while cursor != cursor.parent:
        if _is_link(cursor):
            raise ValueError(f"ownership manifest path contains a link: {cursor}")
        cursor = cursor.parent


def _validate_source(source: Path, skill_name: str) -> Path:
    if source.name != skill_name or source.parent.name != "skills":
        raise ValueError(f"skill source must be a direct child of an install skills directory: {source}")
    cursor = source
    while cursor != cursor.parent:
        if _is_link(cursor):
            raise ValueError(f"skill source path contains a link: {cursor}")
        cursor = cursor.parent
    return source.resolve(strict=True)


def _manifest_read(manifest: Path) -> dict[str, dict[str, str]]:
    if _is_link(manifest):
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("version") != MANIFEST_VERSION or not isinstance(payload.get("skills"), dict):
            return {}
        return {key: value for key, value in payload["skills"].items() if isinstance(value, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _manifest_write(manifest: Path, entries: dict[str, dict[str, str]]) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=manifest.name + ".", dir=manifest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"version": MANIFEST_VERSION, "skills": entries}, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_name, manifest)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _validate_target(target: Path, skills_root: Path, skill_name: str) -> Path:
    if target.name != skill_name or target.parent != skills_root:
        raise ValueError(f"skill target must be a direct child of {skills_root}: {target}")
    if _is_link(skills_root):
        raise ValueError(f"skills directory is a link: {skills_root}")
    if _is_link(target):
        raise ValueError(f"skill target is a link: {target}")
    # Resolve existing ancestors and ensure resolution did not redirect the target.
    resolved_root = skills_root.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    if resolved_target.parent != resolved_root:
        raise ValueError(f"skill target resolves outside its skills directory: {target}")
    cursor = skills_root
    while cursor != cursor.parent:
        if _is_link(cursor):
            raise ValueError(f"skill path contains a link: {cursor}")
        cursor = cursor.parent
    return resolved_root / target.name


def _install_skill_unlocked(source: Path, target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    """Install only into an absent or unchanged Hub-owned skill tree."""
    _validate_manifest(manifest)
    source = _validate_source(source, skill_name)
    if _canonical(source.parent.parent) != _canonical(manifest.parent):
        raise ValueError(f"skill source and ownership manifest have different install roots: {source}")
    source_hash = _safe_tree_hash(source)
    target = _validate_target(target, skills_root, skill_name)
    entries = _manifest_read(manifest)
    key = _canonical(target)
    previous = entries.get(key)
    if target.exists():
        try:
            current_hash = _safe_tree_hash(target)
        except ValueError:
            return f"preserved conflicting skill tree: {target}"
        if not previous or previous.get("name") != skill_name or previous.get("sha256") != current_hash:
            return f"preserved unmanaged or modified skill tree: {target}"
        if _is_link(target):
            return f"preserved conflicting skill tree: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=f".{skill_name}.lah-stage-", dir=target.parent))
    staged = stage_root / "replacement"
    backup = stage_root / "previous"
    had_target = target.exists()
    moved_old = False
    installed_new = False
    try:
        shutil.copytree(source, staged, symlinks=False)
        if _safe_tree_hash(staged) != source_hash:
            raise OSError("staged skill content differs from source")
        if had_target:
            if _safe_tree_hash(target) != current_hash or _is_link(target):
                return f"preserved changed skill tree during replacement: {target}"
            os.replace(target, backup)
            moved_old = True
            try:
                moved_hash = _safe_tree_hash(backup)
            except ValueError:
                moved_hash = None
            if _is_link(backup) or moved_hash != current_hash:
                if not target.exists():
                    os.replace(backup, target)
                    moved_old = False
                if backup.exists():
                    return f"preserved changed skill tree during replacement; recoverable at {backup}"
                return f"preserved changed skill tree during replacement: {target}"
        elif target.exists() or _is_link(target):
            return f"preserved conflicting skill tree created during install: {target}"
        os.replace(staged, target)
        installed_new = True
        entries[key] = {"name": skill_name, "sha256": source_hash}
        _manifest_write(manifest, entries)
    except (OSError, ValueError) as exc:
        rollback_error: Exception | None = None
        try:
            if installed_new and target.exists() and _safe_tree_hash(target) == source_hash:
                shutil.rmtree(target)
            if moved_old and backup.exists() and not target.exists():
                os.replace(backup, target)
        except (OSError, ValueError) as rollback_exc:
            rollback_error = rollback_exc
        if backup.exists():
            recovery = f"; previous skill recoverable at {backup}"
        else:
            recovery = "; previous skill restored" if had_target and target.exists() else "; target unchanged"
        if rollback_error:
            recovery += f"; rollback failed: {rollback_error}"
        return f"skill replacement failed for {target}: {exc}{recovery}"
    finally:
        if not backup.exists():
            shutil.rmtree(stage_root, ignore_errors=True)
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            return f"installed Hub-owned skill: {target}; previous version retained at {backup}: {exc}"
    try:
        shutil.rmtree(stage_root)
    except OSError:
        pass
    return f"installed Hub-owned skill: {target}"


def install_skill(source: Path, target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    _validate_manifest(manifest)
    with _ownership_lock(manifest):
        return _install_skill_unlocked(source, target, skills_root, manifest, skill_name)


def _remove_skill_unlocked(target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    """Remove a skill only when its recorded content hash still matches."""
    _validate_manifest(manifest)
    target = _validate_target(target, skills_root, skill_name)
    if not target.exists():
        return f"skill already absent: {target}"
    entries = _manifest_read(manifest)
    key = _canonical(target)
    previous = entries.get(key)
    if not previous or previous.get("name") != skill_name:
        return f"preserved unmanaged skill tree: {target}"
    try:
        current_hash = _safe_tree_hash(target)
    except ValueError:
        return f"preserved conflicting skill tree: {target}"
    if previous.get("sha256") != current_hash:
        return f"preserved modified Hub-owned skill tree: {target}"
    if _is_link(target):
        return f"preserved conflicting skill tree: {target}"

    quarantine = target.with_name(f".{target.name}.removing-{uuid.uuid4().hex}")
    try:
        os.replace(target, quarantine)
    except OSError as exc:
        return f"skill removal failed for {target}: {exc}"
    try:
        moved_hash = _safe_tree_hash(quarantine)
    except (OSError, ValueError):
        moved_hash = None
    if _is_link(quarantine) or moved_hash != current_hash:
        if not target.exists() and not _is_link(target):
            try:
                os.replace(quarantine, target)
            except OSError:
                return f"preserved changed skill tree; recoverable at {quarantine}"
        if quarantine.exists() or _is_link(quarantine):
            return f"preserved changed skill tree; recoverable at {quarantine}"
        return f"preserved changed skill tree during removal: {target}"

    del entries[key]
    try:
        _manifest_write(manifest, entries)
    except (OSError, ValueError) as exc:
        try:
            if not target.exists() and not _is_link(target):
                os.replace(quarantine, target)
        except OSError:
            return f"skill removal failed for {target}: {exc}; recoverable at {quarantine}"
        return f"skill removal failed for {target}: {exc}; previous skill restored"

    try:
        shutil.rmtree(quarantine)
    except OSError as exc:
        return f"removed skill ownership; previous tree retained at {quarantine}: {exc}"
    return f"removed Hub-owned skill: {target}"


def remove_skill(target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    _validate_manifest(manifest)
    with _ownership_lock(manifest):
        return _remove_skill_unlocked(target, skills_root, manifest, skill_name)
