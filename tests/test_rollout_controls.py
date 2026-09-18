from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.features import FeatureSet
from local_ai_hub import mcp_server
from local_ai_hub.services import LocalAIServices


ROOT = Path(__file__).resolve().parents[1]


def test_defaults_enable_adoption_features() -> None:
    source_defaults = ROOT / "src" / "local_ai_hub" / "defaults.toml"
    defaults = tomllib.loads(source_defaults.read_text(encoding="utf-8"))

    assert source_defaults.read_text(encoding="utf-8").replace("\r\n", "\n") == (ROOT / "defaults.toml").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert defaults["features"]["enriched_search"] is True
    assert defaults["features"]["batch_replacement"] is True
    assert defaults["features"]["diagnostic_artifacts"] is True
    assert defaults["features"]["local_diagnostic_dispatch"] is True


def test_feature_opt_ins_fail_closed_for_malformed_values() -> None:
    features = FeatureSet({"features": {
        "enriched_search": "true",
        "batch_replacement": 1,
        "diagnostic_artifacts": "yes",
        "local_diagnostic_dispatch": object(),
    }})

    assert features.enriched_search is False
    assert features.batch_replacement is False
    assert features.diagnostic_artifacts is False
    assert features.local_diagnostic_dispatch is False


def test_disabled_batch_replacement_does_not_call_engine() -> None:
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"batch_replacement": False}}
    services.deterministic = MagicMock()

    result = services.batch_replace("C:/repo", [{"path": "a.py", "old": "x", "new": "y"}])

    assert result == {
        "success": False,
        "unsupported": True,
        "feature": "batch_replacement",
        "error": "batch replacement is disabled (features.batch_replacement=false)",
    }
    services.deterministic.batch_replace.assert_not_called()


def test_disabled_mcp_rollout_features_do_not_call_server(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "FEATURES", FeatureSet({"features": {"repo": True}}))
    post = MagicMock()
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    batch = mcp_server.local_ai_repo(
        action="batch_replace", root=str(ROOT), edits=[{"path": "a.py", "old": "x", "new": "y"}],
    )
    search = mcp_server.local_ai_repo(action="search", root=str(ROOT), query="needle", include_code=True)

    assert batch["feature"] == "batch_replacement"
    assert search["feature"] == "enriched_search"
    post.assert_not_called()


def test_disabled_batch_schema_projection_tolerates_missing_optional_mcp_sdk() -> None:
    def repo_tool(action: str, dry_run: bool = False, edits: list[dict] | None = None) -> None:
        return None

    mcp_server._hide_disabled_batch_schema(mcp_server._MissingMCP("test"), repo_tool)

    assert "dry_run" not in __import__("inspect").signature(repo_tool).parameters
    assert "edits" not in __import__("inspect").signature(repo_tool).parameters


def test_disabled_diagnostic_artifacts_do_not_persist_command_output(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    broker = CommandBroker(
        {"features": {"diagnostic_artifacts": False}, "server": {"state_dir": str(tmp_path)}},
        artifacts,
    )

    result = broker._compact({"success": False, "stdout": "", "stderr": "unclassified failure"}, "tenant", "pytest -q")

    assert "artifact_id" not in result
    assert result["diagnostic_artifacts"] == {
        "available": False,
        "unsupported": True,
        "feature": "diagnostic_artifacts",
        "error": "diagnostic artifacts are disabled (features.diagnostic_artifacts=false)",
    }
    assert result["output_truncated"] is False


def test_malformed_local_diagnostic_flag_does_not_dispatch_model() -> None:
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"tasks": True, "local_diagnostic_dispatch": "true"}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "failure_summary": {"path": "", "line": 0, "message": "unclassified failure"},
        "artifact_id": "art_failure_log",
        "preview": "unclassified command failure",
    }

    assert services._synthesize_repair_patch("pytest -q", "C:/repo", failure) is None
    assert failure["local_diagnostic_dispatch"] == {
        "available": False,
        "unsupported": True,
        "feature": "local_diagnostic_dispatch",
        "error": "local diagnostic dispatch is disabled (features.local_diagnostic_dispatch=false)",
    }
    services.proxy_request.assert_not_called()


def test_verified_remediation_bypasses_disabled_local_diagnostic_gate() -> None:
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"tasks": False, "local_diagnostic_dispatch": False}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "remediation": {"verified_fix": {"src/widget.py": "fixed\n"}},
    }

    assert services._synthesize_repair_patch("pytest -q", "C:/repo", failure) == {
        "src/widget.py": "fixed\n",
    }
    assert "local_diagnostic_dispatch" not in failure
    services.proxy_request.assert_not_called()


def test_enabled_local_diagnostic_dispatch_persists_only_bounded_preview(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    broker = CommandBroker(
        {
            "features": {"local_diagnostic_dispatch": True, "diagnostic_artifacts": False},
            "server": {"state_dir": str(tmp_path)},
        },
        artifacts,
    )
    failure = broker._compact(
        {"success": False, "stdout": "RAW_COMMAND_OUTPUT_MUST_NOT_BE_STORED", "stderr": "unclassified failure"},
        "tenant",
        "pytest -q",
    )
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"tasks": True, "local_diagnostic_dispatch": True}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock(return_value={"response": '{"diagnosis": "missing setup"}'})

    assert failure["artifact_id"].startswith("art_")
    assert artifacts.get(failure["artifact_id"])["text"] == "unclassified failure"
    assert services._synthesize_repair_patch("pytest -q", "C:/repo", failure) is None
    assert failure["local_diagnostic"] == "missing setup"
    services.proxy_request.assert_called_once()
