import pytest

from local_ai_hub.operation_contracts import validate_operation_output
from local_ai_hub.projection import AgentProjector


@pytest.mark.parametrize("action", ["get", "slice"])
def test_artifact_projection_preserves_evidence_identity(action: str) -> None:
    result = {
        "success": True,
        "evidence_id": "ev-123",
        "root": "C:/project",
        "path": "src/example.py",
        "file_sha256": "a" * 64,
        "start_line": 1,
        "end_line": 2,
        "text": "one\ntwo",
        "stale": False,
    }

    projected = AgentProjector().project(result, agent="codex", task_kind="artifact")

    assert projected["file_sha256"] == result["file_sha256"]
    assert validate_operation_output("local_ai_artifact", action, projected) is None


def test_general_projection_still_strips_file_identity_metadata() -> None:
    projected = AgentProjector().project(
        {"success": True, "file_sha256": "a" * 64, "content_hash": "b" * 64},
        agent="codex",
        task_kind="general",
    )

    assert "file_sha256" not in projected
    assert "content_hash" not in projected
