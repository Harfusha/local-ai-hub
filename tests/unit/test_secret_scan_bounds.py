from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine


def test_test_path_credentials_remain_untriaged_at_original_severity(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "test_credentials.py"
    fixture.parent.mkdir()
    fixture.write_text('token = "sk-proj-123456789012345678901234"\n', encoding="utf-8")

    result = DeterministicEngine().secret_scan(str(tmp_path))

    finding = result["findings"][0]
    assert finding["is_test"] is True
    assert finding["severity"] == "CRITICAL"
    assert finding["triage_status"] == "untriaged"
    assert "123456789012345678901234" not in finding["redacted_snippet"]


def test_placeholder_substring_does_not_downgrade_finding(tmp_path: Path) -> None:
    source = tmp_path / "config.py"
    source.write_text('api_key = "sk-EXAMPLEabcdefghijklmnop"\n', encoding="utf-8")

    result = DeterministicEngine().secret_scan(str(tmp_path))

    finding = result["findings"][0]
    assert finding["severity"] == "CRITICAL"
    assert finding["is_placeholder"] is False
    assert finding["triage_status"] == "untriaged"


def test_requested_path_escape_makes_scan_incomplete(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret-scan.txt"
    outside.write_text("nothing to scan", encoding="utf-8")
    try:
        result = DeterministicEngine().secret_scan(str(tmp_path), "../outside-secret-scan.txt")
    finally:
        outside.unlink(missing_ok=True)

    assert result["scan_complete"] is False
    assert result["clean"] is False
    assert result["coverage"]["errors"] == ["requested_path_unreadable_or_outside_root"]


def test_requested_git_history_is_explicitly_not_scanned(tmp_path: Path) -> None:
    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert result["scanned_git_history"] is False
    assert result["git_history_status"] == "unsupported_bounded_process_capture"
    assert result["scan_complete"] is False
    assert result["clean"] is False
