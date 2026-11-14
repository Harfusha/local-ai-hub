from __future__ import annotations

import ntpath
import os
import stat
from pathlib import Path


def _parse_git_apply_numstat(output: bytes) -> list[str]:
    """Decode `git apply --numstat -z`, including rename/copy path pairs."""
    fields = output.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        columns = field.split(b"\t", 2)
        if len(columns) != 3:
            raise ValueError("Git returned malformed patch path metadata")
        if columns[2]:
            paths.append(os.fsdecode(columns[2]))
            continue
        if index + 1 >= len(fields) or not fields[index] or not fields[index + 1]:
            raise ValueError("Git returned incomplete rename path metadata")
        paths.extend((os.fsdecode(fields[index]), os.fsdecode(fields[index + 1])))
        index += 2
    return list(dict.fromkeys(paths))


def _patch_relative_parts(raw: str) -> tuple[str, ...]:
    if not raw or "\x00" in raw or "\\" in raw or len(raw) > 4096:
        raise ValueError("patch contains an invalid path")
    drive, _ = ntpath.splitdrive(raw)
    parts = raw.split("/")
    if drive or ntpath.isabs(raw) or raw.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"patch path must stay within the repository: {raw[:160]}")
    if any(part.casefold() == ".git" for part in parts):
        raise ValueError("patch cannot modify Git metadata")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)), "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}
    for part in parts:
        basename = part.split(".", 1)[0].rstrip(" .").upper()
        if ":" in part or part.endswith((".", " ")) or basename in reserved:
            raise ValueError(f"patch contains a platform-specific path: {raw[:160]}")
    return tuple(parts)


def _patch_target_path(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    for part in parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"patch path has a symlink or non-directory parent: {current.relative_to(root)}")
    target = root.joinpath(*parts)
    try:
        target.resolve(strict=False).relative_to(root)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"patch path escapes repository: {target}") from exc
    return target
