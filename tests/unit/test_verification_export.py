from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_verification import VerificationStore, VerificationReceipt


def test_export_verification_receipts_markdown(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite")
    verif = VerificationStore(state_store)

    r1 = VerificationReceipt.create(
        task_id="task_100",
        criterion="tests_unit_passed",
        passed=True,
        evidence_id="art_12345",
        command_id="cmd_12345",
        repository_revision="abcdef0123456789",
    )
    r2 = VerificationReceipt.create(
        task_id="task_100",
        criterion="lint_clean",
        passed=True,
        evidence_id="art_67890",
        command_id="cmd_67890",
        repository_revision="abcdef0123456789",
    )
    verif.record(r1)
    verif.record(r2)

    exported = verif.export_receipts("task_100", format="markdown")
    assert exported["success"] is True
    assert exported["count"] == 2
    assert exported["task_id"] == "task_100"
    assert exported["format"] == "markdown"
    assert "| tests_unit_passed | PASSED |" in exported["output"]
    assert "| lint_clean | PASSED |" in exported["output"]
    assert "`abcdef012345`" in exported["output"]
    assert "`art_12345`" in exported["output"]


def test_export_verification_receipts_git_trailers(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite")
    verif = VerificationStore(state_store)

    r = VerificationReceipt.create(
        task_id="task_200",
        criterion="performance_regression_gate",
        passed=True,
        evidence_id="art_perf_99",
        command_id="cmd_perf_99",
        repository_revision="1234567890ab",
    )
    verif.record(r)

    exported = verif.export_receipts("task_200", format="trailers")
    assert exported["success"] is True
    assert exported["count"] == 1
    assert exported["output"].startswith(f"Verified-by: performance_regression_gate ({r.receipt_id})")


def test_export_verification_receipts_standalone_and_json(tmp_path: Path):
    from local_ai_hub.agent_verification import export_verification_receipts

    state_store = AgentStateStore(tmp_path / "state.sqlite")
    verif = VerificationStore(state_store)

    r = VerificationReceipt.create(
        task_id="task_300",
        criterion="test_gate",
        passed=True,
        evidence_id="art_gate_1",
        command_id="cmd_gate_1",
        repository_revision="9876543210ab",
    )
    verif.record(r)

    exported = export_verification_receipts(verif, "task_300", format="json")
    assert exported["success"] is True
    assert exported["count"] == 1
    assert exported["format"] == "json"
    assert "task_300" in exported["output"]
    assert "test_gate" in exported["output"]

    # Test missing task_id
    err = verif.export_receipts("")
    assert err["success"] is False
    assert err["error"] == "task_id required"

    # Test unsupported format
    err2 = verif.export_receipts("task_300", format="xml")
    assert err2["success"] is False
    assert "unsupported format" in err2["error"]


def test_local_ai_coord_verify_export_mcp(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    class FakeClient:
        def __init__(self):
            self.calls = []

        def post(self, path, payload, **kwargs):
            self.calls.append((path, payload, kwargs))
            return {
                "success": True,
                "task_id": payload.get("task_id"),
                "format": payload.get("format"),
                "count": 1,
                "output": "sample output",
            }

    fake_client = FakeClient()
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", fake_client)

    res = mcp_server.local_ai_coord(
        action="verify_export",
        task_id="task_400",
        format="markdown",
        root=str(tmp_path),
    )
    assert res["success"] is True
    assert len(fake_client.calls) == 1
    path, payload, kwargs = fake_client.calls[0]
    assert path == "/api/agent-state/verification"
    assert payload["action"] == "export"
    assert payload["task_id"] == "task_400"
    assert payload["format"] == "markdown"

