"""Guarded removal of Hub-owned runtime and state for full reinstall."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Callable

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _has_link_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    return any(_is_link(component) for component in (absolute, *absolute.parents))


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(os.path.abspath(os.fspath(right)))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        Path(os.path.abspath(os.fspath(path))).relative_to(Path(os.path.abspath(os.fspath(parent))))
        return True
    except ValueError:
        return False


def reinstall_targets(install_dir: Path, state_dir: Path, source_root: Path, home: Path) -> list[Path]:
    install = Path(os.path.abspath(os.fspath(install_dir)))
    state = Path(os.path.abspath(os.fspath(state_dir)))
    source = Path(source_root).resolve(strict=False)
    home_dir = Path(os.path.abspath(os.fspath(home)))
    if _same_path(install, source) or _same_path(install, home_dir):
        raise ValueError(f"unsafe full reinstall path refused: {install}")
    if _same_path(state, install):
        raise ValueError(f"state directory cannot be the install directory: {state}")
    if _same_path(state, source) or _same_path(state, home_dir):
        raise ValueError(f"unsafe state deletion path refused: {state}")
    if _is_within(state, source) or _is_within(source, state):
        raise ValueError(f"state deletion path overlaps the source checkout: {state}")
    if not _is_within(state, install) and not _is_within(state, home_dir):
        raise ValueError(f"state deletion path must be inside install or user home: {state}")
    if _has_link_component(install) or _has_link_component(state):
        raise ValueError("full reinstall refused: install or state path contains a symlink or junction")
    if _is_within(source, install) or _is_within(install, source):
        raise ValueError("full reinstall refused: source checkout overlaps install directory")
    if _is_within(install, state) and not _same_path(install, state):
        raise ValueError(f"unsafe state deletion path would remove install directory: {state}")
    targets = [install / ".venv", install / "tool-envs", install / "state", install / "models", state]
    unique: list[Path] = []
    for target in targets:
        if not any(_same_path(target, prior) for prior in unique):
            unique.append(target)
    for target in unique:
        if not _is_within(target, install) and not _same_path(target, state):
            raise ValueError(f"unsafe full reinstall target refused: {target}")
        if _has_link_component(target):
            raise ValueError(f"full reinstall target contains a symlink or junction: {target}")
    return unique


def perform_full_reinstall(
    install_dir: Path,
    state_dir: Path,
    source_root: Path,
    *,
    home: Path,
    stop_runtime: Callable[[], tuple[bool, str]],
    interactive: bool,
    confirmation: str | None,
) -> list[Path]:
    targets = reinstall_targets(install_dir, state_dir, source_root, home)
    state = Path(os.path.abspath(os.fspath(state_dir)))
    print("\nÚplná reinstalace smaže data Hubu v těchto cestách:")
    for target in targets:
        print(f"  {target}")
    required_confirmation = f"DELETE {state}"
    if interactive:
        typed = input(f"Pro smazání napiš přesně `{required_confirmation}`: ").strip()
    else:
        typed = confirmation or ""
    if typed != required_confirmation:
        raise ValueError("full reinstall cancelled: exact data-path confirmation did not match")
    stopped, detail = stop_runtime()
    if not stopped:
        raise RuntimeError(f"full reinstall refused because the managed Hub did not stop: {detail}")
    for target in targets:
        if not target.exists():
            continue
        if _has_link_component(target):
            raise ValueError(f"full reinstall target became a symlink or junction: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    return targets
