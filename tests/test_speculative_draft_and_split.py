from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import MagicMock
from local_ai_hub import deterministic as deterministic_module
from local_ai_hub.deterministic import DeterministicEngine
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


def test_token_accounting_financial_savings() -> None:
    # Test financial USD accounting calculation
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
    assert "net_savings_usd" in acct
    assert "estimated_savings_usd" in acct
    assert acct["estimated_savings_usd"] > 0
    assert acct["estimated_input_savings_usd"] == round((40000 / 1_000_000.0) * 3.0, 4)
    assert acct["estimated_output_savings_usd"] == round((10000 / 1_000_000.0) * 15.0, 4)


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
