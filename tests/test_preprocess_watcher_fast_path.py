from __future__ import annotations

from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock
import sqlite3
import time
import pytest

from local_ai_hub.preprocess import ProjectPreprocessor


def test_preprocess_watcher_fast_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    app_file = root / "app.py"
    app_file.write_text("def hello(): return 'world'\n", encoding="utf-8")

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"enabled": True},
    }

    mock_deterministic = MagicMock()
    mock_deterministic.update_file.return_value = {"success": True}

    mock_rag = MagicMock()
    mock_rag.workspace_id.return_value = "test_workspace"

    mock_repo_tools = MagicMock()
    mock_repo_tools.ignore_dirs = {".git", "node_modules", "venv"}
    mock_repo_tools.special_filenames = set()
    mock_repo_tools.extensions = {".py", ".ts", ".js"}

    prep = ProjectPreprocessor(
        config=config,
        services=MagicMock(),
        rag=mock_rag,
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=mock_repo_tools,
        deterministic=mock_deterministic,
    )

    try:
        # Register project cleanly via prep.register
        prep.register(str(root))
        with closing(prep._connect()) as con:
            con.execute(
                "UPDATE projects SET status='complete', phase='complete' WHERE root=?",
                (str(root.resolve()),),
            )
            con.commit()

        # Update file via fast-path
        t0 = time.monotonic()
        res = prep.fast_update_file(str(root), "app.py", content="def hello(): return 'universe'\n")
        duration_ms = (time.monotonic() - t0) * 1000

        assert res["success"] is True
        assert res["path"] == "app.py"
        assert res["deterministic_updated"] is True
        # Verify sub-50ms execution
        assert duration_ms < 50.0

        # Verify file_refs has the new content hash
        with closing(prep._connect()) as con:
            row = con.execute("SELECT content_hash, needs_hash FROM file_refs WHERE root=? AND path='app.py'", (str(root.resolve()),)).fetchone()
            assert row is not None
            assert row[1] == 0
            assert row[0] == res["content_hash"]

            # Verify project status did NOT get demoted to 'inventory'
            proj = con.execute("SELECT phase FROM projects WHERE root=?", (str(root.resolve()),)).fetchone()
            assert proj[0] == "complete"

        # Verify notify_path_changed with fast_path=True also works
        notified = prep.notify_path_changed(str(app_file), fast_path=True)
        assert notified is True

    finally:
        prep.close()
