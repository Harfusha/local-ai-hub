"""Write the deterministic setup result for later inspection."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_setup_report(install_dir: Path, report: dict[str, Any]) -> Path:
    return write_install_report(Path(install_dir) / "setup-report.json", report)


def write_install_report(target: Path, report: dict[str, Any]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise OSError(f"setup report path is a symlink: {target}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.stem}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
