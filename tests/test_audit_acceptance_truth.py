"""Static audit claims are never sufficient to approve a release."""
from __future__ import annotations

import json

from tools import generate_audit_acceptance as audit


def test_no_receipts_never_produces_a_ready_release(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "get_git_head", lambda: "a" * 40)
    result = audit.generate_acceptance(tmp_path / "audit.json")
    assert result["summary"]["verified_count"] == 0
    assert result["summary"]["unverified_count"] > 0
    assert result["summary"]["regressions_count"] is None
    assert result["release_gate"]["approved"] is False
    assert result["summary"]["overall_status"] == "BLOCKED"
    assert not any(x.get("verification_status") == "CI_GREEN" for x in result["items"])


def test_receipts_reject_stale_sha_and_failed_or_wrong_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "get_git_head", lambda: "a" * 40)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    item = next(x for x in audit.AUDIT_ITEMS if x["status"] == "SOURCE_VERIFIED")
    receipt = {
        "item_id": item["id"], "source_sha": "b" * 40,
        "command": item["verification_command"], "exit_code": 0,
        "timestamp_utc": "2026-11-15T12:00:00Z",
    }
    path = receipts / (item["id"] + ".json")
    path.write_text(json.dumps(receipt), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in report["items"] if x["id"] == item["id"])["verification_status"] == "UNVERIFIED"
    receipt["source_sha"] = "a" * 40
    receipt["exit_code"] = 1
    path.write_text(json.dumps(receipt), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in report["items"] if x["id"] == item["id"])["verification_status"] == "UNVERIFIED"
    receipt["exit_code"] = 0
    receipt["command"] = "echo fake pass"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in report["items"] if x["id"] == item["id"])["verification_status"] == "UNVERIFIED"


def test_current_local_receipt_does_not_imply_ci_or_live_acceptance(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "get_git_head", lambda: "a" * 40)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    item = next(x for x in audit.AUDIT_ITEMS if x["status"] == "SOURCE_VERIFIED")
    (receipts / (item["id"] + ".json")).write_text(json.dumps({
        "item_id": item["id"], "source_sha": "a" * 40,
        "command": item["verification_command"], "exit_code": 0,
        "timestamp_utc": "2026-11-15T12:00:00Z",
    }), encoding="utf-8")
    result = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in result["items"] if x["id"] == item["id"])["verification_status"] == "LOCAL_TESTED"
    assert result["release_gate"]["approved"] is False
    assert result["summary"]["verified_count"] == 0
    assert result["summary"]["regressions_count"] is None


def test_receipts_reject_mock_skipped_and_assertionless_records(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "get_git_head", lambda: "a" * 40)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    item = next(x for x in audit.AUDIT_ITEMS if x["status"] == "SOURCE_VERIFIED")
    receipt_file = receipts / f"{item['id']}.json"

    # 1. Mock receipt rejected
    receipt_file.write_text(json.dumps({
        "item_id": item["id"], "source_sha": "a" * 40,
        "command": item["verification_command"], "exit_code": 0,
        "timestamp_utc": "2026-11-24T12:00:00Z", "mock": True,
    }), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in report["items"] if x["id"] == item["id"])["verification_status"] == "UNVERIFIED"

    # 2. Skipped receipt rejected
    receipt_file.write_text(json.dumps({
        "item_id": item["id"], "source_sha": "a" * 40,
        "command": item["verification_command"], "exit_code": 0,
        "timestamp_utc": "2026-11-24T12:00:00Z", "skipped": True,
    }), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in report["items"] if x["id"] == item["id"])["verification_status"] == "UNVERIFIED"

    # 3. Assertionless receipt rejected (passed_assertions == 0)
    receipt_file.write_text(json.dumps({
        "item_id": item["id"], "source_sha": "a" * 40,
        "command": item["verification_command"], "exit_code": 0,
        "timestamp_utc": "2026-11-24T12:00:00Z", "passed_assertions": 0,
    }), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    assert next(x for x in report["items"] if x["id"] == item["id"])["verification_status"] == "UNVERIFIED"


def test_receipts_support_finding_id_alias_and_flag_stale_commit_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "get_git_head", lambda: "c" * 40)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    item = next(x for x in audit.AUDIT_ITEMS if x["status"] == "SOURCE_VERIFIED")
    receipt_file = receipts / f"{item['id']}.json"

    receipt_file.write_text(json.dumps({
        "finding_id": item["id"],
        "commit_sha": "d" * 40,  # drifted from head "c" * 40
        "verification_command": item["verification_command"],
        "exit_code": 0,
        "timestamp_utc": "2026-11-24T12:00:00Z",
    }), encoding="utf-8")
    report = audit.generate_acceptance(tmp_path / "report.json", receipts_dir=receipts)
    res_item = next(x for x in report["items"] if x["id"] == item["id"])
    assert res_item["verification_status"] == "UNVERIFIED"
    assert res_item["stale"] is True
    assert "commit drift" in res_item["stale_reason"]

