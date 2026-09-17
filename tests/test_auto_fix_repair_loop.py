from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.services import LocalAIServices


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
        "features": {"diagnostic_artifacts": True},
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
    assert attempts_made == 1
    assert test_file.read_text(encoding="utf-8") == initial_content


def test_repair_loop_does_not_dispatch_local_diagnosis_for_arbitrary_interpreter(temp_dir: Path):
    broker = make_broker(temp_dir)
    script = temp_dir / "failing_command.py"
    script.write_text("raise SystemExit('unclassified failure')\n", encoding="utf-8")
    services = object.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock(return_value={"response": '{"candidate.py": "value = 1\\n"}'})

    result = broker.repair_loop(
        f"{sys.executable} -B {script.name}",
        temp_dir,
        "tenant-1",
        max_attempts=3,
        fix_generator=services._synthesize_repair_patch,
    )

    assert result["success"] is False
    assert result["attempts"] == 3
    services.proxy_request.assert_not_called()


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


def test_long_pytest_failure_has_artifact_and_first_failure_preview(temp_dir: Path):
    broker = make_broker(temp_dir)
    script = temp_dir / "synthetic_pytest_failure.py"
    script.write_text(
        "import sys\n"
        "for _ in range(900):\n"
        "    print('pytest progress ' + ('x' * 20))\n"
        "print('tests/test_widget.py:42: AssertionError: expected ready', file=sys.stderr)\n"
        "print('FAILED tests/test_widget.py::test_ready - AssertionError: expected ready', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )

    result = broker.run(f"{sys.executable} {script.name}", temp_dir, "tenant-1", force=True)

    assert result["success"] is False
    assert result["failure_summary"] == {
        "path": "tests/test_widget.py",
        "line": 42,
        "message": "AssertionError: expected ready",
    }
    assert result["artifact_id"].startswith("art_")
    assert "tests/test_widget.py:42: AssertionError: expected ready" in result["preview"]
    assert result["output_truncated"] is True
    stdout_artifact = broker.artifacts.get(result["artifact_id"], section="stdout")
    stderr_artifact = broker.artifacts.get(result["artifact_id"], section="stderr")
    assert stdout_artifact["success"] is True
    assert stderr_artifact["success"] is True
    assert "pytest progress" in stdout_artifact["text"]
    assert "FAILED tests/test_widget.py::test_ready" in stderr_artifact["text"]


def test_failure_summary_ignores_remediation_diagnostic(temp_dir: Path):
    broker = make_broker(temp_dir)
    result = broker._compact({
        "success": False,
        "stdout": "",
        "stderr": "tests/a.py:3: AssertionError: command failure",
        "remediation": {"root_cause": "tests/remediation.py:99: stale guidance"},
    }, "tenant-1", "pytest -q")

    assert result["failure_summary"] == {
        "path": "tests/a.py",
        "line": 3,
        "message": "AssertionError: command failure",
    }


def test_short_low_confidence_failure_gets_bounded_diagnostic_artifact(temp_dir: Path):
    broker = make_broker(temp_dir)
    result = broker._compact({
        "success": False,
        "stdout": "RAW_SHORT_LOG_MUST_NOT_BE_IN_DIAGNOSTIC_ARTIFACT",
        "stderr": "unclassified failure",
    }, "tenant-1", "pytest -q")

    assert result["artifact_id"].startswith("art_")
    diagnostic = broker.artifacts.get(result["artifact_id"])
    assert diagnostic["success"] is True
    assert "unclassified failure" in diagnostic["text"]
    assert "RAW_SHORT_LOG_MUST_NOT_BE_IN_DIAGNOSTIC_ARTIFACT" not in diagnostic["text"]


def test_failure_summary_prefers_error_diagnostic_over_stdout_warning(temp_dir: Path):
    broker = make_broker(temp_dir)
    result = broker._compact({
        "success": False,
        "stdout": "tests/warning.py:1: warning: deprecated fixture",
        "stderr": "tests/a.py:3: AssertionError: command failure",
    }, "tenant-1", "pytest -q")

    assert result["failure_summary"] == {
        "path": "tests/a.py",
        "line": 3,
        "message": "AssertionError: command failure",
    }


def test_failure_summary_keeps_first_failed_pytest_path(temp_dir: Path):
    broker = make_broker(temp_dir)
    result = broker._compact({
        "success": False,
        "stdout": "FAILED tests/widget.py::test_ready",
        "stderr": "AssertionError: a later generic failure",
    }, "tenant-1", "pytest -q")

    assert result["failure_summary"] == {
        "path": "tests/widget.py",
        "line": 0,
        "message": "test_ready",
    }


def test_long_low_confidence_failure_stores_only_full_artifact(temp_dir: Path):
    broker = make_broker(temp_dir)
    calls: list[tuple[str, str, str]] = []
    original_put = broker.artifacts.put

    def record_put(text: str, tenant: str, kind: str) -> str:
        calls.append((text, tenant, kind))
        return original_put(text, tenant, kind)

    broker.artifacts.put = record_put
    result = broker._compact({
        "success": False,
        "stdout": "x" * (broker.inline_chars + 1),
        "stderr": "unclassified failure",
    }, "tenant-1", "pytest -q")

    assert result["artifact_id"].startswith("art_")
    assert [kind for _, _, kind in calls] == ["command"]


def test_classify_quoted_semicolons(temp_dir: Path):
    broker = make_broker(temp_dir)
    # Quoted semicolon must be allowed
    res1 = broker.classify('python -c "import sys; print(1)"')
    assert res1["allowed"] is True
    assert res1["class"] == "read"

    res_val = broker.classify('python -c "assert 1 == 1; print(\'ok\')"')
    assert res_val["allowed"] is True
    assert res_val["class"] == "validation"

    # Safe compound commands must be allowed
    res_safe = broker.classify('git status ; git diff')
    assert res_safe["allowed"] is True
    assert res_safe["class"] == "read"

    res_safe_and = broker.classify('git status && git diff')
    assert res_safe_and["allowed"] is True

    # Dangerous compound command must be blocked
    res2 = broker.classify('python test.py ; rm -rf /')
    assert res2["allowed"] is False
    assert res2["class"] == "dangerous"

    # Dangerous unquoted && must be blocked
    res3 = broker.classify('pytest && rm -rf /')
    assert res3["allowed"] is False
    assert res3["class"] == "dangerous"


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

    # Word-boundary check: 'latest' contains 'test' but should NOT be classified as validation
    res7 = broker.classify("python -c \"latest = 123; print(latest)\"")
    assert res7["class"] == "read", f"word containing 'test' substring should be read: {res7}"

    # Dangerous functions blocked by AST/pattern
    res8 = broker.classify("python -c \"import os; os.remove('some_file')\"")
    assert res8["class"] == "unknown"
    assert res8["allowed"] is False


def test_broadened_command_classification(tmp_path: Path):
    broker = CommandBroker({
        "commands": {
            "enabled": True,
            "allow_read": True,
            "allow_validation": True,
            "allow_build": True,
            "allow_mutating": False,
            "allow_unknown": False,
            "extra_allowed_tools": ["custom_tool", "my-cli"],
        },
        "server": {"state_dir": str(tmp_path)},
    })

    # Git commands
    assert broker.classify("git log -p -n 5")["allowed"] is True
    assert broker.classify("git log -p -n 5")["class"] == "read"
    assert broker.classify("git --no-pager log")["allowed"] is True
    assert broker.classify("git --no-pager log")["class"] == "read"
    assert broker.classify("git -C some/dir status")["allowed"] is True
    assert broker.classify("git blame src/main.py")["allowed"] is True
    assert broker.classify("git stash list")["allowed"] is True
    assert broker.classify("git config --get user.name")["allowed"] is True
    assert broker.classify("git push origin main")["allowed"] is False
    assert broker.classify("git reset --hard")["allowed"] is False
    assert broker.classify("git -c core.pager=rm status")["allowed"] is False

    # Read-only tools
    for tool_cmd in ("fd pattern", "cat file.txt", "wc -l file.txt", "jq . data.json", "diff a.txt b.txt", "head -n 10 file.txt", "tail -n 20 file.txt", "sort file.txt"):
        res = broker.classify(tool_cmd)
        assert res["allowed"] is True, f"Failed for {tool_cmd}: {res}"
        assert res["class"] == "read"

    # Python commands
    assert broker.classify("python -m pip list")["allowed"] is True
    assert broker.classify("python -m pip list")["class"] == "read"
    assert broker.classify("python -m coverage report")["allowed"] is True
    assert broker.classify("python -m coverage report")["class"] == "validation"
    assert broker.classify("python -m json.tool data.json")["allowed"] is True
    assert broker.classify("python -m json.tool data.json")["class"] == "read"
    assert broker.classify("python tools/benchmark.py")["allowed"] is True
    assert broker.classify("python tools/benchmark.py")["class"] == "validation"
    assert broker.classify("python tools/show_summary.py")["allowed"] is True
    assert broker.classify("python -m pip install requests")["allowed"] is False

    # Linters and formatters
    assert broker.classify("flake8 src tests")["allowed"] is True
    assert broker.classify("pylint src")["allowed"] is True
    assert broker.classify("black --check .")["allowed"] is True
    assert broker.classify("black --check .")["class"] == "validation"
    assert broker.classify("black .")["allowed"] is False  # without --check: mutating

    # Whitelisted custom tools
    assert broker.classify("custom_tool --foo bar")["allowed"] is True
    assert broker.classify("my-cli inspect")["allowed"] is True


def test_benevolent_command_classification(tmp_path: Path):
    broker = CommandBroker({
        "commands": {
            "enabled": True,
            "allow_read": True,
            "allow_validation": True,
            "allow_build": True,
            "allow_mutating": False,
            "allow_unknown": False,
        },
        "server": {"state_dir": str(tmp_path)},
    })

    # Git plumbing and worktree inspection
    for cmd in (
        "git worktree list --porcelain",
        "git stash show",
        "git stash list",
        "git for-each-ref --format='%(refname)'",
        "git cat-file -p HEAD:README.md",
        "git rev-list --count HEAD",
        "git diff-tree -r --name-only HEAD",
        "git hash-object README.md",
    ):
        res = broker.classify(cmd)
        assert res["allowed"] is True, f"Blocked: {cmd} -> {res}"
        assert res["class"] == "read"

    # Dotnet inspection and build/test
    for cmd in ("dotnet --info", "dotnet --version", "dotnet --list-sdks"):
        res = broker.classify(cmd)
        assert res["allowed"] is True, f"Blocked: {cmd} -> {res}"
        assert res["class"] == "read"

    assert broker.classify("dotnet test")["allowed"] is True
    assert broker.classify("dotnet test")["class"] == "validation"
    assert broker.classify("dotnet build")["allowed"] is True
    assert broker.classify("dotnet build")["class"] == "build"

    # Windows inspection tools
    for cmd in ("tasklist", "whoami", "hostname", "systeminfo", "ipconfig", "netstat -ano"):
        res = broker.classify(cmd)
        assert res["allowed"] is True, f"Blocked: {cmd} -> {res}"
        assert res["class"] == "read"

    # Compound commands and pipelines
    compound_safe = broker.classify("git diff --stat; git status")
    assert compound_safe["allowed"] is True
    assert compound_safe["class"] == "read"

    pipe_safe = broker.classify("git ls-files | Select-String 'test'")
    assert pipe_safe["allowed"] is True
    assert pipe_safe["class"] == "read"

    pipe_rg = broker.classify("git ls-files | rg test")
    assert pipe_rg["allowed"] is True

    pipe_findstr = broker.classify("tasklist | findstr Unity")
    assert pipe_findstr["allowed"] is True

    # PowerShell commands and scripts
    ps_res = broker.classify("$ErrorActionPreference='Stop'; Get-Process")
    assert ps_res["allowed"] is True
    assert ps_res["class"] == "read"

    ps_unity = broker.classify("pwsh -File tools/run/Invoke-WoodboundUnity.ps1 -runTests")
    assert ps_unity["allowed"] is True
    assert ps_unity["class"] == "validation"

    # Loopback HTTP in python -c allowed
    py_http = broker.classify('python -c "import urllib.request; print(urllib.request.urlopen(\'http://127.0.0.1:11435/health\').read())"')
    assert py_http["allowed"] is True

    # Dangerous commands still blocked
    assert broker.classify("rm -rf /")["allowed"] is False
    assert broker.classify("git push origin main")["allowed"] is False
    assert broker.classify("git reset --hard")["allowed"] is False
    assert broker.classify("git diff; rm -rf /")["allowed"] is False
    assert broker.classify("Remove-Item -Recurse C:\\")["allowed"] is False


def test_benevolent_command_execution(temp_dir: Path):
    broker = make_broker(temp_dir)

    # 1. Read-only git worktree list execution
    res_wt = broker.run("git worktree list", cwd=str(Path.cwd()))
    assert res_wt["success"] is True
    assert res_wt["exit_code"] == 0

    # 2. Compound command execution
    res_compound = broker.run("git status --short; git branch --show-current", cwd=str(Path.cwd()))
    assert res_compound["success"] is True
    assert res_compound["exit_code"] == 0
    assert len(res_compound["stdout"]) > 0

    # 3. Pipeline execution
    if os.name == "nt":
        res_pipe = broker.run("git ls-files | Select-String 'commands.py'", cwd=str(Path.cwd()))
    else:
        res_pipe = broker.run("git ls-files | grep 'commands.py'", cwd=str(Path.cwd()))
    assert res_pipe["success"] is True
    assert res_pipe["exit_code"] == 0
    assert "commands.py" in res_pipe["stdout"]


