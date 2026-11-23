from __future__ import annotations

from pathlib import Path

from .deterministic_constants import (
    _MAX_SCHEMA_SCAN_DIRS,
    _MAX_SCHEMA_SCAN_ENTRIES,
    _MAX_SCHEMA_SCAN_FILES,
)
from .schema_file_scanning import scan_schema_files


def _bounded_schema_files(
    root: Path,
    *,
    suffix: str,
    deadline: float,
    migrations_only: bool = False,
) -> list[Path]:
    return scan_schema_files(
        root,
        suffix=suffix,
        deadline=deadline,
        migrations_only=migrations_only,
        max_dirs=_MAX_SCHEMA_SCAN_DIRS,
        max_entries=_MAX_SCHEMA_SCAN_ENTRIES,
        max_files=_MAX_SCHEMA_SCAN_FILES,
    )
