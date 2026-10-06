from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from local_ai_hub.work_orchestrator import WorkOrchestrator, _JournalEntry


def test_rollback_refuses_junction_target(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside = outside_dir / "a.txt"
    outside.write_text("outside baseline\n", encoding="utf-8")
    junction = root / "linked"
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside_dir)],
            check=True, capture_output=True, text=True,
        )
    else:
        junction.symlink_to(outside_dir, target_is_directory=True)
