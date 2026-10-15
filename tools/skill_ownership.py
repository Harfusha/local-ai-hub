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
from pathlib import Path

MANIFEST_NAME = ".local-ai-hub-skill-ownership.json"
MANIFEST_VERSION = 1
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


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


def install_skill(source: Path, target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
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
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)
    entries[key] = {"name": skill_name, "sha256": source_hash}
    _manifest_write(manifest, entries)
    return f"installed Hub-owned skill: {target}"


def remove_skill(target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
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
    shutil.rmtree(target)
    del entries[key]
    _manifest_write(manifest, entries)
    return f"removed Hub-owned skill: {target}"
