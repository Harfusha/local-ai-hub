from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from local_ai_hub.agent_dispatcher import get_agent_executable, execute_agent_task


def test_get_agent_executable_known():
    with patch("shutil.which", return_value="C:\\bin\\codex.exe"):
        exe = get_agent_executable("codex")
        assert exe == "C:\\bin\\codex.exe"


def test_get_agent_executable_unknown():
    with patch("shutil.which", return_value=None):
        exe = get_agent_executable("nonexistent_agent_xyz")
        assert exe is None


def test_execute_agent_task_not_found():
    with patch("local_ai_hub.agent_dispatcher.get_agent_executable", return_value=None):
        res = execute_agent_task("fake_agent", "do something", Path.cwd())
        assert res["success"] is False
        assert "not found" in res["error"]


def test_execute_agent_task_mock_success():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Task completed successfully"
    mock_proc.stderr = ""

    with patch("local_ai_hub.agent_dispatcher.get_agent_executable", return_value="C:\\bin\\codex.exe"):
        with patch("subprocess.run", return_value=mock_proc):
            res = execute_agent_task("codex", "run tests", Path.cwd())
            assert res["success"] is True
            assert res["returncode"] == 0
            assert "completed" in res["stdout"]
