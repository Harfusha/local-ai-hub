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
    outside.write_bytes(b"outside baseline\n")
    junction = root / "linked"
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside_dir)],
            check=True, capture_output=True, text=True,
        )
    else:
        junction.symlink_to(outside_dir, target_is_directory=True)
    journal = [_JournalEntry("linked/a.txt", True, b"original\n")]
    with pytest.raises(ValueError, match="symlink|reparse|escape"):
        WorkOrchestrator._rollback(root, journal)
    with pytest.raises(ValueError, match="symlink|reparse|escape"):
        object.__new__(WorkOrchestrator)._snapshot(root, ["linked/a.txt"])
    assert outside.read_bytes() == b"outside baseline\n"
