from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import MagicMock
from local_ai_hub import deterministic_editing as deterministic_editing_module
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.command_broker import CommandBroker
from local_ai_hub.services import LocalAIServices
from local_ai_hub.token_accounting import finalize_tool_accounting


def test_split_changes(tmp_path: Path) -> None:
    changed = [
        "src/models/user.py",
        "src/core/engine.py",
        "src/api/routes.py",
        "tests/test_user.py",
        "docs/api.md",
        "config.toml",
    ]
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    for path in changed:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", path], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    for path in changed:
        (tmp_path / path).write_text("changed\n", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path.parent / (tmp_path.name + "-state"))}})
    res = engine.split_changes(str(tmp_path))
    assert res["success"] is True
    assert res["total_files"] == 6
    assert res["cluster_count"] == 6

    categories = {c["category"] for c in res["clusters"]}
    assert "implementation" in categories
    assert "test" in categories
    assert "docs" in categories


def test_split_changes_bounds_git_status(tmp_path: Path, monkeypatch) -> None:
    engine = DeterministicEngine(
        {
            "server": {"state_dir": str(tmp_path)},
            "workspace_cache": {"git_status_timeout_seconds": 0.7},
        }
    )
    timeouts = []

    def fake_run(argv, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        if "--show-toplevel" in argv:
            output = str(tmp_path.resolve()).encode() + b"\n"
        elif "--verify" in argv:
            output = b"a" * 40 + b"\n"
        elif "ls-files" in argv:
            output = b""
        elif "status" in argv:
            output = b" M source.py\0"
        elif "--patch" in argv:
            output = b"diff --git a/source.py b/source.py\n@@ -1 +1 @@\n-old\n+new\n"
        elif "--cached" in argv:
            output = b""
        else:
            output = b"1\t1\tsource.py\0"
        return subprocess.CompletedProcess(argv, 0, output, b"")

    monkeypatch.setattr(deterministic_editing_module, "run_hidden", fake_run)

    result = engine.split_changes(str(tmp_path))

    assert result["total_files"] == 1
    assert timeouts == [0.7] * 11


def test_split_changes_has_no_legacy_full_mode(tmp_path: Path, monkeypatch) -> None:
    import local_ai_hub.change_plan_projection as projection

    services = LocalAIServices(
        config={"server": {"state_dir": str(tmp_path)}},
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=MagicMock(),
    )
    services.deterministic.split_changes.return_value = {"success": True, "clusters": []}
    monkeypatch.setattr(projection, "project_change_plan", lambda result, **kwargs: {"projected": kwargs["mode"]})

    assert services.split_changes(str(tmp_path)) == {"projected": "summary"}
    assert services.split_changes(str(tmp_path), mode="full")["success"] is False


def test_split_changes_continuation_requires_a_prior_observation_revision(tmp_path: Path) -> None:
    services = LocalAIServices(
        config={"server": {"state_dir": str(tmp_path)}},
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=MagicMock(),
    )

    result = services.split_changes(str(tmp_path), mode="summary", offset=1)

    assert result["success"] is False
    assert result["restart_required"] is True
    assert "expected_revision" in result["error"]
    services.deterministic.split_changes.assert_not_called()


def test_synthesize_rules(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    # create pyproject.toml
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    res = engine.synthesize_rules(str(tmp_path), limit=10)
    assert res["success"] is True
    assert res["rule_count"] >= 4

    rule_ids = {r["rule_id"] for r in res["rules"]}
    assert "rule_bounded_execution" in rule_ids
    assert "rule_deterministic_first" in rule_ids
    assert "rule_python_ruff" in rule_ids
    assert "rule_typescript_strict" in rule_ids


def test_token_accounting_retains_tokens_without_fabricating_prices() -> None:
    acct = finalize_tool_accounting(
        tool_name="local_ai_repo",
        arguments={"action": "solve"},
        response={"result": "ok"},
        measured={
            "gross_cloud_tokens_avoided_est": 50000,
            "gross_input_tokens_avoided_est": 40000,
            "gross_output_tokens_avoided_est": 10000,
        },
    )
    assert acct["gross_cloud_tokens_avoided_est"] == 50000
    assert acct["gross_input_tokens_avoided_est"] == 40000
    assert acct["gross_output_tokens_avoided_est"] == 10000
    assert acct["net_cloud_token_delta_est"] == 50000 - acct["agent_protocol_tokens_est"]
    for field in ("net_savings_usd", "estimated_savings_usd",
                  "estimated_input_savings_usd", "estimated_output_savings_usd"):
        assert field not in acct


def test_speculative_draft_service(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"fast_code": "qwen2.5-coder:7b"},
    }
    services = LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )
    services._generate = MagicMock(return_value={
        "response": "def calculate():\n    return 42\n",
        "duration_ms": 120.0,
    })
    services.commands = MagicMock()
    services.commands.run.return_value = {"success": True, "summary": "tests passed"}
    services.affected_tests = MagicMock(
        return_value={"suggested_command": "pytest -q tests/test_calculator.py"}
    )

    res = services.speculative_draft(
        {
            "task": "write calculate function",
            "file": "calc.py",
            "root": str(tmp_path),
        },
    )

    assert res["success"] is True
    assert res["model"] == "qwen2.5-coder:7b"
    assert "def calculate" in res["draft"]
    assert res["verification"]["syntax_valid"] is True
    assert res["validated"] is False
    services.affected_tests.assert_not_called()
    services.commands.run.assert_not_called()

    verified = services.speculative_draft(
        {
            "task": "write calculate function",
            "file": "calc.py",
            "root": str(tmp_path),
            "verify_tests": True,
        },
    )

    services.affected_tests.assert_called_once_with(
        str(tmp_path), changed_paths=["calc.py"]
    )
    services.commands.run.assert_called_once()
    assert services.commands.run.call_args.args[0] == "pytest -q tests/test_calculator.py"
    assert services.commands.run.call_args.args == (
        "pytest -q tests/test_calculator.py",
        str(tmp_path),
    )
    assert verified["verification"]["tests_passed"] is True
    assert verified["verification"]["test_summary"] == "tests passed"
    assert verified["validated"] is True


def test_speculative_draft_failures_never_run_or_claim_validation(tmp_path: Path) -> None:
    cases = (
        ({"success": False, "error": "provider unavailable"}, False, False),
        ({"response": "def answer(:\n    return 42\n"}, True, False),
    )
    for index, (generation, expected_success, expected_syntax_valid) in enumerate(cases):
        case_root = tmp_path / str(index)
        services = LocalAIServices(
            config={"server": {"state_dir": str(case_root)}, "models": {"fast_code": "fast"}},
            runtime=MagicMock(),
            scheduler=MagicMock(),
            embeddings=MagicMock(),
            artifacts=MagicMock(),
            telemetry=MagicMock(),
            repo_tools=MagicMock(),
            deterministic=None,
        )
        services._generate = MagicMock(return_value=generation)
        services.commands = MagicMock()
        services.affected_tests = MagicMock(
            return_value={"suggested_command": "pytest -q"}
        )

        result = services.speculative_draft(
            {
                "task": "write answer function",
                "file": "answer.py",
                "root": str(case_root),
                "verify_tests": True,
            },
        )

        assert result["success"] is expected_success
        assert result["verification"]["syntax_valid"] is expected_syntax_valid
        assert result["validated"] is False
        services.affected_tests.assert_not_called()
        services.commands.run.assert_not_called()


def test_speculative_draft_broker_rejects_unpermitted_validation(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "models": {"fast_code": "qwen2.5-coder:7b"},
        "commands": {"enabled": True, "policy_blocking": True, "allow_validation": False},
    }
    services = LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )
    broker = CommandBroker(config)
    services.commands = broker
    services._generate = MagicMock(return_value={
        "response": "def calculate():\n    return 42\n",
        "duration_ms": 20.0,
    })
    services.affected_tests = MagicMock(
        return_value={"suggested_command": "pytest --version"}
    )
    classification = broker.classify("pytest --version")
    assert classification["class"] == "validation"
    assert classification["allowed"] is False

    result = services.speculative_draft(
        {
            "task": "write calculate function",
            "file": "calc.py",
            "root": str(tmp_path),
            "verify_tests": True,
        },
    )

    assert result["verification"]["tests_passed"] is False
    assert result["validated"] is False
    assert broker.blocked == 1


def test_speculative_draft_cascade_execution(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {
            "fast_code": "qwen2.5-coder:7b",
            "draft_code": "qwen2.5-coder:0.5b",
        },
    }
    services = LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )
    calls = []

    def fake_generate(model, prompt, system, max_tokens, temp, **kwargs):
        calls.append((model, prompt))
        if model == "qwen2.5-coder:0.5b":
            return {"response": "def draft_calc():\n    return 10\n", "duration_ms": 15.0}
        return {"response": "def calculate():\n    return 42\n", "duration_ms": 50.0}

    services._generate = fake_generate

    result = services.speculative_draft(
        {
            "task": "write calculate function",
            "file": "calc.py",
            "root": str(tmp_path),
        },
    )

    assert result["success"] is True
    assert result["model"] == "qwen2.5-coder:7b"
    assert result["draft"] == "def calculate():\n    return 42"
    assert result["cascade"] == ["qwen2.5-coder:0.5b", "qwen2.5-coder:7b"]
    assert result["draft_model"] == "qwen2.5-coder:0.5b"
    assert result["target_model"] == "qwen2.5-coder:7b"
    assert len(calls) == 2
    assert calls[0][0] == "qwen2.5-coder:0.5b"
    assert calls[1][0] == "qwen2.5-coder:7b"
    assert "CANDIDATE DRAFT CODE" in calls[1][1]

