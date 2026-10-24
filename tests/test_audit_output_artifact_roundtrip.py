from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.compact import compact_result
from local_ai_hub.projection import AgentProjector


def _broker(*, artifacts: ArtifactStore, diagnostic_artifacts: bool) -> CommandBroker:
    broker = object.__new__(CommandBroker)
    broker.config = {
        "features": {
            "diagnostic_artifacts": diagnostic_artifacts,
            "local_diagnostic_dispatch": False,
        }
    }
    broker.inline_chars = 96
    broker.artifacts = artifacts
    broker._deterministic_summary = lambda _result: "command summary"
    broker._extract_diagnostics = lambda _result: []
    broker._first_failure_summary = lambda _result: {"path": "", "message": "failure"}
    broker._failure_preview = lambda _summary: "bounded diagnostic preview"
    return broker


@pytest.mark.parametrize("state_dir_as_string", [False, True])
def test_full_output_artifact_roundtrips_through_compaction_and_paged_reads(
    tmp_path: Path, state_dir_as_string: bool
) -> None:
    state_dir = tmp_path / ("artifact-state-string" if state_dir_as_string else "artifact-state-path")
    store = ArtifactStore(str(state_dir) if state_dir_as_string else state_dir)
    stdout = "stdout-head-unique\n" + ("o" * 900) + "\nstdout-tail-exact\n"
    stderr = "stderr-head-unique\n" + ("e" * 850) + "\nstderr-tail-exact\n"
    full_output = f"$ audit-output\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"

    compacted = _broker(artifacts=store, diagnostic_artifacts=True)._compact(
        {"success": True, "stdout": stdout, "stderr": stderr}, "audit-output"
    )

    assert compacted["output_artifact_id"] == compacted["artifact_id"]
    projected = AgentProjector({}).project(
        compact_result(compacted, max_text_chars=300), agent="generic", task_kind="command"
    )
    assert projected["output_artifact_id"] == compacted["output_artifact_id"]
    assert len(projected['stdout']) < len(stdout)
    assert projected['output_truncated'] is True

    pages: list[str] = []
    offset = 0
    for _ in range(len(full_output) + 1):
        page = store.get(compacted["output_artifact_id"], offset=offset, max_chars=47)
        assert page["success"] is True
        assert page["offset"] == offset
        pages.append(page["text"])
        next_offset = page["next_offset"]
        if next_offset is None:
            break
        assert next_offset > offset
        offset = next_offset
    else:
        pytest.fail('artifact pagination did not terminate within its character bound')

    assert "".join(pages) == full_output
    assert "stdout-tail-exact" in "".join(pages)
    assert "stderr-tail-exact" in "".join(pages)


@pytest.mark.parametrize(
    ("diagnostic_artifacts", "result_fields", "expected_reason"),
    [
        (False, {}, "diagnostic_artifacts_disabled"),
        (True, {"discarded_output_chars": 7}, "capture_incomplete"),
    ],
)
def test_unavailable_or_partial_capture_never_publishes_complete_output_pointer(
    tmp_path: Path,
    diagnostic_artifacts: bool,
    result_fields: dict[str, int],
    expected_reason: str,
) -> None:
    store = ArtifactStore(tmp_path / "artifact-state")
    result = _broker(artifacts=store, diagnostic_artifacts=diagnostic_artifacts)._compact(
        {"success": True, "stdout": "captured stdout " * 20, "stderr": "captured stderr " * 12, **result_fields},
        "audit-output",
    )

    assert "output_artifact_id" not in result
    assert result["output_recovery"] == {"available": False, "reason": expected_reason}
    projected = AgentProjector({}).project(
        compact_result(result, max_text_chars=300), agent="generic", task_kind="command"
    )
    assert "output_artifact_id" not in projected

