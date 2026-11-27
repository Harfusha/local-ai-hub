"""Explicit opt-in source context for the next server-inventoried obligation."""
from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .project_config import path_is_allowed, resolve_project_config
from .repo_tools import RepositoryTools
from .source_slice import read_source_slice

# Deliberately exclude configuration, environment, credential and data files.
SOURCE_SUFFIXES = frozenset({".py", ".php", ".rs", ".go", ".js", ".jsx", ".ts", ".tsx",
                             ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb"})


def obligation_source_context(
    config: Mapping[str, Any], execution: Mapping[str, Any], *,
    requested_root: str, trusted_root: str,
) -> dict[str, Any] | None:
    """Read a small exact source preview, not evidence or completion authority."""
    inventory = config.get("inventory", {})
    next_unit = execution.get("next_obligation")
    if (inventory.get("scope") != "repository"
            or execution.get("scope_check", {}).get("complete") is not True
            or not isinstance(next_unit, dict)
            or next_unit.get("evidence_type") != "source_review"
            or not trusted_root or not requested_root):
        return None
    resource = next_unit.get("resource")
    if (type(resource) is not str or resource not in inventory.get("resources", [])
            or Path(resource).suffix.lower() not in SOURCE_SUFFIXES):
        return None
    try:
        base = Path(trusted_root).resolve(strict=True)
        if Path(requested_root).resolve(strict=True) != base:
            return None
        candidate = base / resource
        safe = RepositoryTools._resolve_inventory_path_safe_with_stat(base, candidate, resolved_base=base)
        if safe is None or not stat.S_ISREG(safe[2].st_mode):
            return None
        policy = resolve_project_config(base)
        if policy.error_codes or not path_is_allowed(
            base, candidate, policy.settings, phase="search", size_bytes=safe[2].st_size,
        ):
            return None
        result = read_source_slice(str(base), resource, line_start=1, line_end=40, max_chars=1600)
        after = RepositoryTools._resolve_inventory_path_safe_with_stat(base, candidate, resolved_base=base)
        if (after is None or any(getattr(after[2], field) != getattr(safe[2], field)
                                for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
                or result.get("success") is not True or result.get("relative_path") != resource):
            return None
        return result
    except (OSError, ValueError, RuntimeError):
        return None
