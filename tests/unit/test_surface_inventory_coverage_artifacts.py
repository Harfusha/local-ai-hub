from __future__ import annotations

import json
from pathlib import Path

from tools import surface_inventory


def _fake_inventory(monkeypatch) -> dict:
    finding = {
        "surface": "MCP tool",
        "name": "sample",
        "owner": "src/sample.py",
        "handler": "handle_sample",
        "evidence_status": "conditional",
        "condition": "feature gate: sample_enabled",
        "contract": {"request": {"field": "value"}, "status_codes": [200]},
        "fixtures": ["tests/unit/test_sample.py::test_contract"],
        "evidence": ["src/sample.py:10"],
        "acceptance": "Generated schema declares sample operation.",
        "behavioral_test_ids": ["tests/unit/test_sample.py::test_contract"],
    }
    monkeypatch.setattr(surface_inventory, "collect_inventory", lambda _root: {"drift": []})
    monkeypatch.setattr(surface_inventory, "_findings", lambda _inventory: [finding])
    return finding


def test_write_and_check_cover_human_index_and_structured_rows(tmp_path: Path, monkeypatch, capsys) -> None:
    finding = _fake_inventory(monkeypatch)
    (tmp_path / "docs").mkdir()

    assert surface_inventory.main([
        "--root", str(tmp_path), "--write-doc", "--task-id", "F19-test",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    markdown = tmp_path / "docs" / "API_COVERAGE.md"
    artifact = tmp_path / "docs" / "API_COVERAGE.json"
    parsed = json.loads(artifact.read_text(encoding="utf-8"))
    expected_row = surface_inventory.coverage_rows([finding], "F19-test")[0]
    assert output["written_artifact"] == "docs/API_COVERAGE.json"
    assert "Contract gaps" not in markdown.read_text(encoding="utf-8")
    assert parsed["task_id"] == "F19-test"
    assert parsed["coverage_rows"][0] == expected_row
    for key, value in finding["contract"].items():
        assert parsed["coverage_rows"][0]["contract"][key] == value
    assert parsed["coverage_rows"][0]["fixtures"] == finding["fixtures"]
    assert parsed["coverage_rows"][0]["condition"] == finding["condition"]
    assert parsed["coverage_rows"][0]["task_id"] == "F19-test"
    assert "contract_gaps" in parsed["coverage_rows"][0]
    assert "not runtime" in parsed["description"]

    assert surface_inventory.main(["--root", str(tmp_path), "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["coverage_matches"] is True
    assert checked["artifact_matches"] is True
    assert checked["coverage_rows"] == 1


def test_check_reports_structured_artifact_drift_without_writing(tmp_path: Path, monkeypatch, capsys) -> None:
    _fake_inventory(monkeypatch)
    (tmp_path / "docs").mkdir()
    assert surface_inventory.main(["--root", str(tmp_path), "--write-doc"]) == 0
    capsys.readouterr()
    artifact = tmp_path / "docs" / "API_COVERAGE.json"
    artifact.write_text("{}\n", encoding="utf-8")
    before = artifact.read_bytes()

    assert surface_inventory.main(["--root", str(tmp_path), "--check"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["coverage_matches"] is True
    assert output["artifact_matches"] is False
    assert any("docs/API_COVERAGE.json" in item for item in output["drift"])
    assert artifact.read_bytes() == before


def test_check_rejects_pending_historical_snapshot(tmp_path: Path, monkeypatch, capsys) -> None:
    _fake_inventory(monkeypatch)
    docs = tmp_path / "docs"
    docs.mkdir()
    markdown = docs / "API_COVERAGE.md"
    artifact = docs / "API_COVERAGE.json"
    markdown.write_text("# API surface coverage\n\nRefresh pending.\n", encoding="utf-8")
    artifact.write_text(json.dumps({
        "schema_version": 1,
        "snapshot_status": "refresh_pending",
        "task_id": None,
        "coverage_rows": None,
    }) + "\n", encoding="utf-8")
    before = (markdown.read_bytes(), artifact.read_bytes())

    assert surface_inventory.main(["--root", str(tmp_path), "--check"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["coverage_matches"] is False
    assert output["artifact_matches"] is False
    assert (markdown.read_bytes(), artifact.read_bytes()) == before
