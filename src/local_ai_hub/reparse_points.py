from __future__ import annotations

import os
from pathlib import Path
import stat


def _is_directory_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            return True
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if getattr(metadata, "st_file_attributes", 0) & reparse_point:
            return True
        is_junction = getattr(path, "is_junction", None)
        return callable(is_junction) and is_junction()
    except OSError:
        return True


def _is_symlink_or_reparse_point(path: Path) -> bool:
    info = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    is_junction = getattr(os.path, "isjunction", None)
    return (
        stat.S_ISLNK(info.st_mode)
        or bool(attributes & reparse_flag)
        or (callable(is_junction) and is_junction(path))
    )
