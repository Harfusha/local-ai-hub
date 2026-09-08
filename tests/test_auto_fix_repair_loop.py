from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_events import AgentStateStore


@pytest.fixture
def temp_dir(tmp_path: Path):
    return tmp_path


class _RepoState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "test-fingerprint"}


def make_broker(temp_dir: Path) -> CommandBroker:
    state_dir = temp_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    artifacts = ArtifactStore(state_dir / "artifacts")
    config = {
        "commands": {
            "allowed": True,
            "allow_unknown": True,
            "allow_validation": True,
            "timeout_seconds": 10,
            "inline_chars": 4000,
            "cache_ttl_seconds": 60,
        },
        "server": {"state_dir": str(state_dir)},
    }
    broker = CommandBroker(config, artifacts, _RepoState())
    agent_state = AgentStateStore(state_dir / "agent_state.sqlite3")
    v_store = VerificationStore(agent_state)
    broker.set_verification_store(v_store)
    return broker


def test_repair_loop_already_passing(temp_dir: Path):
    broker = make_broker(temp_dir)
    res = broker.repair_loop(f"{sys.executable} -c \"print('ok')\"", temp_dir, "tenant-1")
    assert res["success"] is True
    assert res["repaired"] is False
    assert res["attempts"] == 0


def test_repair_loop_successful_fix(temp_dir: Path):
    broker = make_broker(temp_dir)
    test_file = temp_dir / "test_target.py"
    test_file.write_text(
        "import unittest\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 2)\n",
        encoding="utf-8",
    )

    cmd = f"{sys.executable} -B -m unittest test_target"

    def generator(cmd_str: str, cwd_path: str, fail_res: dict[str, Any]) -> dict[str, str]:
        return {
            "test_target.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 1)\n"
        }

    res = broker.repair_loop(cmd, temp_dir, "tenant-1", fix_generator=generator, task_id="task-heal-1")
    assert res["success"] is True
    assert res["repaired"] is True
    assert res["attempts"] == 1
    assert "test_target.py" in res["patches_applied"]
    assert res.get("verification_receipt") is not None
    assert res["verification_receipt"]["passed"] is True
    assert res["verification_receipt"]["task_id"] == "task-heal-1"
    assert "self.assertEqual(1, 1)" in test_file.read_text(encoding="utf-8")


def test_repair_loop_rollback_on_failure(temp_dir: Path):
    broker = make_broker(temp_dir)
    test_file = temp_dir / "test_broken.py"
    initial_content = (
        "import unittest\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 2)\n"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    cmd = f"{sys.executable} -m unittest test_broken"

    attempts_made = 0

    def bad_generator(cmd_str: str, cwd_path: str, fail_res: dict[str, Any]) -> dict[str, str]:
        nonlocal attempts_made
        attempts_made += 1
        return {
            "test_broken.py": f"import unittest\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, {attempts_made + 2})\n"
        }

    res = broker.repair_loop(cmd, temp_dir, "tenant-1", max_attempts=2, fix_generator=bad_generator)
    assert res["success"] is False
    assert res["repaired"] is False
    assert res["attempts"] == 2
    assert test_file.read_text(encoding="utf-8") == initial_content


def test_command_run_auto_fix_flag(temp_dir: Path):
    broker = make_broker(temp_dir)
    test_file = temp_dir / "test_app.py"
    test_file.write_text(
        "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(10, 20)\n",
        encoding="utf-8",
    )

    cmd = f"{sys.executable} -B -m unittest test_app"

    def generator(cmd_str: str, cwd_path: str, fail_res: dict[str, Any]) -> dict[str, str]:
        return {
            "test_app.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(20, 20)\n"
        }

    res = broker.run(cmd, temp_dir, "tenant-1", auto_fix=True, fix_generator=generator)
    assert res["success"] is True
    assert res.get("repaired") is True
    assert "self.assertEqual(20, 20)" in test_file.read_text(encoding="utf-8")


def test_classify_quoted_semicolons(temp_dir: Path):
    broker = make_broker(temp_dir)
    # Quoted semicolon must be allowed
    res1 = broker.classify('python -c "import sys; print(1)"')
    assert res1["allowed"] is True
    assert res1["class"] == "read"

    res_val = broker.classify('python -c "assert 1 == 1; print(\'ok\')"')
    assert res_val["allowed"] is True
    assert res_val["class"] == "validation"

    # Unquoted semicolon must be blocked
    res2 = broker.classify('python test.py ; rm -rf /')
    assert res2["allowed"] is False
    assert res2["class"] == "unknown"
    assert "shell operators are not accepted" in res2["reason"]

    # Unquoted && must be blocked
    res3 = broker.classify('pytest && rm -rf /')
    assert res3["allowed"] is False
    assert res3["class"] == "unknown"


def test_classify_python_c_dangerous_patterns(temp_dir: Path):
    """Security: python -c inline code with dangerous calls must be classified
    as 'unknown' and blocked when allow_unknown=False (the secure default).
    This prevents bypass via validation keywords like 'test' or 'check' as comments."""
    # Use restricted broker with allow_unknown=False (the secure production default)
    state_dir = temp_dir / "state2"
    state_dir.mkdir(parents=True, exist_ok=True)
    restricted_config = {
        "commands": {
            "allowed": True,
            "allow_unknown": False,   # key: deny unknown classifications
            "allow_validation": True,
            "allow_read": True,
            "timeout_seconds": 10,
            "inline_chars": 4000,
            "cache_ttl_seconds": 60,
        },
        "server": {"state_dir": str(state_dir)},
    }
    artifacts2 = ArtifactStore(state_dir / "artifacts")
    broker = CommandBroker(restricted_config, artifacts2, _RepoState())

    # Bypass attempt: os.system with 'test' keyword as comment — must be blocked
    cmd1 = "python -c \"import os; os.system('rm -rf /'); # test\""
    res = broker.classify(cmd1)
    assert res["class"] == "unknown", f"os.system() should be unknown: {res}"
    assert res["allowed"] is False, f"os.system() must be denied with allow_unknown=False: {res}"

    # exec() disguised as validation
    cmd2 = 'python -c "exec(\'print(42)\')  # validate"'
    res2 = broker.classify(cmd2)
    assert res2["class"] == "unknown", f"exec() should be unknown: {res2}"
    assert res2["allowed"] is False, f"exec() must be denied: {res2}"

    # subprocess with 'check' keyword
    cmd3 = 'python -c "import subprocess; subprocess.run([\'id\']); # check"'
    res3 = broker.classify(cmd3)
    assert res3["class"] == "unknown"
    assert res3["allowed"] is False

    # eval() with 'assert' keyword
    cmd4 = 'python -c "eval(\'1+1\')  # assert"'
    res4 = broker.classify(cmd4)
    assert res4["class"] == "unknown"
    assert res4["allowed"] is False

    # Safe: legitimate use without dangerous patterns — must be allowed
    res5 = broker.classify("python -c \"import sys; print(sys.version)\"")
    assert res5["class"] == "read", f"safe inline should be read: {res5}"
    assert res5["allowed"] is True

    res6 = broker.classify("python -c \"assert True, 'sanity check'\"")
    assert res6["class"] == "validation"
    assert res6["allowed"] is True

