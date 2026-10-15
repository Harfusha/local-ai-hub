from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import MagicMock
from local_ai_hub import deterministic as deterministic_module
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.commands import CommandBroker
from local_ai_hub.services import LocalAIServices
from local_ai_hub.token_accounting import finalize_tool_accounting


def test_split_changes(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    changed = [
        "src/models/user.py",
        "src/core/engine.py",
        "src/api/routes.py",
        "tests/test_user.py",
        "docs/api.md",
        "config.toml",
    ]
    res = engine.split_changes(str(tmp_path), changed_files=changed)
    assert res["success"] is True
    assert res["total_files"] == 6
    assert res["cluster_count"] >= 4

    categories = {c["category"] for c in res["clusters"]}
    assert "models_or_schemas" in categories
    assert "core" in categories
    assert "api_or_services" in categories
    assert "tests" in categories
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
        return subprocess.CompletedProcess(argv, 0, " M source.py\n", "")

    monkeypatch.setattr(deterministic_module.subprocess, "run", fake_run)

    result = engine.split_changes(str(tmp_path))

    assert result["total_files"] == 1
    assert timeouts == [0.7]


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
        tenant="test",
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
            "root": "",
            "cwd": str(tmp_path),
            "verify_tests": True,
        },
        tenant="test-tenant",
    )

    services.affected_tests.assert_called_once_with(
        str(tmp_path), changed_paths=["calc.py"]
    )
    services.commands.run.assert_called_once()
    assert services.commands.run.call_args.args[0] == "pytest -q tests/test_calculator.py"
    assert services.commands.run.call_args.args[2] == "test-tenant"
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
            tenant="test",
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
        tenant="test",
    )

    assert result["verification"]["tests_passed"] is False
    assert result["validated"] is False
    assert broker.blocked == 1
