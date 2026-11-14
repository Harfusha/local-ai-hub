"""Normalize safe repository paths returned by optional search backends."""

from pathlib import Path
from typing import cast


def collect_external_candidate_paths(root: str, payload: object) -> list[str]:
    """Extract safe, existing repository-relative paths from backend payloads."""
    root_path = Path(root).resolve(strict=False)
    path_keys = {"path", "relative_path", "file_path", "filename", "module_path", "source_path"}
    found: list[str] = []
    visited = 0

    def add_path(raw_path: str | Path) -> None:
        candidate_text = str(raw_path).strip()
        candidate = Path(candidate_text).expanduser()
        if not candidate.is_absolute():
            candidate = root_path / Path(candidate_text.replace("\\", "/"))
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root_path)
            if resolved.is_file():
                relative = resolved.relative_to(root_path).as_posix()
                if relative not in found:
                    found.append(relative)
        except (OSError, ValueError):
            pass

    def visit(value: object) -> None:
        nonlocal visited
        if visited >= 500:
            return
        visited += 1
        if isinstance(value, dict):
            for key, item in cast(dict[object, object], value).items():
                if str(key).lower() in path_keys and isinstance(item, (str, Path)):
                    add_path(item)
                else:
                    if (
                        isinstance(key, str)
                        and ("/" in key or "\\" in key)
                        and isinstance(item, (dict, list, tuple))
                    ):
                        add_path(key)
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in cast(list[object] | tuple[object, ...], value):
                visit(item)

    visit(payload)
    return found
