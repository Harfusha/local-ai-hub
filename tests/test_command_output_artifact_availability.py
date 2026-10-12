from __future__ import annotations

from local_ai_hub.commands import CommandBroker
from local_ai_hub.compact import compact_result
from local_ai_hub.projection import AgentProjector

import pytest


class _Artifacts:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def put(self, content: str, tenant: str, kind: str) -> str:
        self.items.append((content, tenant, kind))
        return f"artifact-{len(self.items)}"


def _broker(*, diagnostic_artifacts: bool, artifacts: _Artifacts) -> CommandBroker:
    broker = object.__new__(CommandBroker)
    broker.config = {
        "features": {
            "diagnostic_artifacts": diagnostic_artifacts,
            "local_diagnostic_dispatch": False,
        }
    }
    broker.inline_chars = 8
    broker.artifacts = artifacts
    broker._deterministic_summary = lambda _result: "command summary"
    broker._extract_diagnostics = lambda _result: []
    broker._first_failure_summary = lambda _result: {"path": "", "message": "failure"}
    broker._failure_preview = lambda _summary: "bounded diagnostic preview"
    return broker


def test_command_without_full_log_artifact_does_not_publish_output_artifact_id() -> None:
    artifacts = _Artifacts()
    broker = _broker(diagnostic_artifacts=False, artifacts=artifacts)

    result = broker._compact(
        {"success": True, "stdout": "x" * 40, "stderr": ""}, "tenant", "run"
    )

    assert "output_artifact_id" not in result
    assert "artifact_id" not in result
    assert result["output_truncated"] is True
    assert not artifacts.items


def test_command_with_full_log_artifact_publishes_output_artifact_id() -> None:
    artifacts = _Artifacts()
    broker = _broker(diagnostic_artifacts=True, artifacts=artifacts)

    result = broker._compact(
        {"success": True, "stdout": "x" * 40, "stderr": "y" * 40}, "tenant", "run"
    )

    assert result["artifact_id"] == result["output_artifact_id"] == "artifact-1"
    assert artifacts.items == [("$ run\n\nSTDOUT:\n" + "x" * 40 + "\n\nSTDERR:\n" + "y" * 40, "tenant", "command")]


def test_diagnostic_preview_artifact_does_not_claim_full_output() -> None:
    artifacts = _Artifacts()
    broker = _broker(diagnostic_artifacts=True, artifacts=artifacts)
    broker.inline_chars = 80

    result = broker._compact(
        {"success": False, "stdout": "short output", "stderr": ""}, "tenant", "run"
    )

    assert result["artifact_id"] == "artifact-1"
    assert "output_artifact_id" not in result
    assert artifacts.items == [("bounded diagnostic preview", "tenant", "command_diagnostic")]


@pytest.mark.parametrize("uncertain_flag", ["output_capture_unconfirmed", "cleanup_unconfirmed"])
def test_unconfirmed_capture_never_claims_complete_output_artifact(uncertain_flag: str) -> None:
    artifacts = _Artifacts()
    broker = _broker(diagnostic_artifacts=True, artifacts=artifacts)
    result = broker._compact(
        {"success": False, "stdout": "x" * 40, "stderr": "", uncertain_flag: True},
        "tenant", "run",
    )
    assert result["artifact_id"]
    assert "output_artifact_id" not in result
    assert result[uncertain_flag] is True


def test_partial_capture_artifact_does_not_claim_full_output() -> None:
    artifacts = _Artifacts()
    broker = _broker(diagnostic_artifacts=True, artifacts=artifacts)

    result = broker._compact(
        {"success": True, "stdout": "x" * 40, "stderr": "", "discarded_output_chars": 6},
        "tenant",
        "run",
    )

    assert result["artifact_id"] == "artifact-1"
    assert "output_artifact_id" not in result
    assert result["discarded_output_chars"] > 6
    assert result["output_truncated"] is True


def test_inline_compaction_preserves_capture_truncation() -> None:
    broker = _broker(diagnostic_artifacts=False, artifacts=_Artifacts())

    result = broker._compact(
        {
            "success": True,
            "stdout": "short",
            "stderr": "",
            "discarded_output_chars": 6,
            "output_truncated": True,
        },
        "tenant",
        "run",
    )

    assert result["output_truncated"] is True


def test_compaction_and_projection_only_offer_artifact_for_full_log() -> None:
    stdout = "out\n" * 200
    stderr = "err\n" * 200
    compacted = compact_result(
        {"stdout": stdout, "stderr": stderr}, max_text_chars=300
    )
    projected = AgentProjector({}).project(
        {"stdout": stdout, "stderr": stderr, "artifact_id": "diagnostic-preview"},
        agent="generic",
        task_kind="command",
    )

    assert "use artifact" not in compacted["stdout"]
    assert "use artifact" not in compacted["stderr"]
    assert "use artifact" not in projected["stdout"]
    assert "use artifact" not in projected["stderr"]
    assert compacted["output_truncated"] is True
    assert projected["output_truncated"] is True

    with_artifact = compact_result(
        {
            "stdout": stdout,
            "stderr": stderr,
            "artifact_id": "full-log",
            "output_artifact_id": "full-log",
        },
        max_text_chars=300,
    )
    assert "use artifact" in with_artifact["stdout"]
    assert "use artifact" in with_artifact["stderr"]

    command_projection = AgentProjector({}).project(
        {"summary": "summary\n" * 200}, agent="generic", task_kind="command"
    )
    assert "more available via artifact" not in command_projection["summary"]

    non_command_projection = AgentProjector({}).project(
        {"summary": "summary\n" * 200}, agent="generic", task_kind="search"
    )
    assert "more available via artifact" in non_command_projection["summary"]

    command_with_artifact = AgentProjector({}).project(
        {"summary": "summary\n" * 200, "output_artifact_id": "full-log"},
        agent="generic",
        task_kind="command",
    )
    assert "more available via artifact" in command_with_artifact["summary"]

    whitespace_projection = AgentProjector({}).project(
        {"stdout": "\n" * 1000, "stderr": "\n" * 1000},
        agent="generic",
        task_kind="command",
    )
    assert not whitespace_projection.get("output_truncated", False)
