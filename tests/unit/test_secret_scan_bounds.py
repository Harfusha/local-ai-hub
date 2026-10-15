from pathlib import Path
import subprocess
from types import SimpleNamespace

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
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside-secret-scan.txt"
    outside.write_text("nothing to scan", encoding="utf-8")
    try:
        result = DeterministicEngine().secret_scan(str(root), "../outside-secret-scan.txt")
    finally:
        outside.unlink(missing_ok=True)

    assert result["scan_complete"] is False
    assert result["clean"] is False
    assert result["coverage"]["errors"] == ["requested_path_unreadable_or_outside_root"]


def _history_output(secret: bytes = b"", *, parents: bytes = b"") -> bytes:
    commit = b"a" * 40
    output = b"\x00LAH_SECRET_SCAN_COMMIT:" + commit + b" PARENTS:" + parents + b"\x00\n"
    if secret:
        output += (
            b"diff --git a/config.env b/config.env\n--- a/config.env\n+++ b/config.env\n"
            b"@@ -7 +7,0 @@\n-" + secret + b"\n"
        )
    return output


def _mock_history(monkeypatch, stdout: bytes, **attrs):
    from local_ai_hub import deterministic

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        result = SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")
        for key, value in attrs.items():
            setattr(result, key, value)
        return result

    monkeypatch.setattr(deterministic, "run_hidden", fake_run)
    return calls


def test_git_history_scans_deleted_secret_line_with_commit_and_hunk_metadata(tmp_path: Path, monkeypatch) -> None:
    calls = _mock_history(monkeypatch, _history_output(b"sk-proj-123456789012345678901234"))
    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True, commit_depth=3)

    finding = result["findings"][0]
    assert finding["source"] == "git_history"
    assert finding["git_change"] == "removed"
    assert finding["git_commit"] == "a" * 40
    assert finding["file"] == "config.env"
    assert finding["line"] == 7
    assert result["scanned_git_history"] is True
    assert result["coverage"]["git_history"]["commits_scanned"] == 1
    assert result["clean"] is False
    argv, kwargs = calls[0]
    assert "--literal-pathspecs" in argv
    assert "--no-ext-diff" in argv and "--no-textconv" in argv
    assert "HEAD" in argv
    assert kwargs["capture_output"] is True and kwargs["text"] is False
    assert "shell" not in kwargs
    assert kwargs["timeout"] <= 5.0


def test_git_history_pathspec_is_literal_and_validated(tmp_path: Path, monkeypatch) -> None:
    calls = _mock_history(monkeypatch, _history_output())
    result = DeterministicEngine().secret_scan(
        str(tmp_path), "config[old].env", scan_git_history=True, commit_depth=2
    )

    argv, _kwargs = calls[0]
    assert argv[-1] == "config[old].env"
    assert "--literal-pathspecs" in argv
    assert result["coverage"]["git_history"]["requested_commit_depth"] == 2


def test_git_history_quoted_non_ascii_path_is_decoded_without_guessing(tmp_path: Path, monkeypatch) -> None:
    commit = b"d" * 40
    output = (
        b"\x00LAH_SECRET_SCAN_COMMIT:" + commit + b" PARENTS:\x00\n"
        b'diff --git "a/caf\\303\\251.env" "b/caf\\303\\251.env"\n'
        b'--- "a/caf\\303\\251.env"\n+++ "b/caf\\303\\251.env"\n'
        b"@@ -2 +2 @@\n-sk-proj-123456789012345678901234\n"
    )
    _mock_history(monkeypatch, output)

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert result["findings"][0]["file"] == "café.env"
    assert result["findings"][0]["line"] == 2
    assert result["scanned_git_history"] is True


def test_git_history_rejects_output_over_shared_capture_budget(tmp_path: Path, monkeypatch) -> None:
    _mock_history(monkeypatch, b"x" * (16 * 1024 * 1024 + 1))

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert result["findings"] == []
    assert result["scan_complete"] is False
    assert result["git_history_status"] == "output_capture_incomplete"


def test_git_history_timeout_output_is_not_treated_as_verified_capture(tmp_path: Path, monkeypatch) -> None:
    from local_ai_hub import deterministic

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("git", 0.1, output=_history_output(b"sk-proj-123456789012345678901234"))

    monkeypatch.setattr(deterministic, "run_hidden", timeout)

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert result["findings"] == []
    assert result["scan_complete"] is False
    assert result["scanned_git_history"] is False
    assert result["git_history_status"] == "process_failed_or_cleanup_unverified"
    assert all("sk-proj" not in error for error in result["coverage"]["errors"])


def test_git_history_unverified_process_cleanup_fails_closed(tmp_path: Path, monkeypatch) -> None:
    from local_ai_hub import deterministic
    from local_ai_hub.process_utils import ProcessCleanupUnverifiedError

    def failed_cleanup(*_args, **_kwargs):
        raise ProcessCleanupUnverifiedError(
            ["git"], process=SimpleNamespace(), tree_termination_confirmed=False,
            output=_history_output(b"sk-proj-123456789012345678901234"),
        )

    monkeypatch.setattr(deterministic, "run_hidden", failed_cleanup)

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert result["findings"] == []
    assert result["scan_complete"] is False
    assert result["clean"] is False
    assert all("sk-proj" not in error for error in result["coverage"]["errors"])


def test_git_history_rejects_invalid_depth_without_running_git(tmp_path: Path, monkeypatch) -> None:
    calls = _mock_history(monkeypatch, _history_output())

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True, commit_depth=101)

    assert calls == []
    assert result["git_history_status"] == "invalid_commit_depth"
    assert result["scan_complete"] is False
    assert result["clean"] is False


def test_git_history_truncated_capture_is_not_parsed_as_complete(tmp_path: Path, monkeypatch) -> None:
    calls = _mock_history(
        monkeypatch, _history_output(b"sk-proj-123456789012345678901234"), stdout_truncated=True,
    )

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert calls
    assert result["findings"] == []
    assert result["scanned_git_history"] is False
    assert result["git_history_status"] == "output_capture_incomplete"
    assert result["clean"] is False


def test_git_history_merge_commit_omission_is_incomplete(tmp_path: Path, monkeypatch) -> None:
    result_output = _history_output(
        b"sk-proj-123456789012345678901234", parents=b"b" * 40 + b" " + b"c" * 40,
    )
    _mock_history(monkeypatch, result_output)

    result = DeterministicEngine().secret_scan(str(tmp_path), scan_git_history=True)

    assert result["scanned_git_history"] is True
    assert result["scan_complete"] is False
    assert "git_history_merge_commit_omitted" in result["coverage"]["errors"]
    assert result["findings"][0]["git_change"] == "removed"


def test_env_file_is_scanned(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('OPENAI_API_KEY="sk-proj-123456789012345678901234"\n', encoding="utf-8")

    result = DeterministicEngine().secret_scan(str(tmp_path))

    assert any(item["file"] == ".env" for item in result["findings"])


def test_file_read_stops_at_hard_byte_limit(tmp_path: Path, monkeypatch) -> None:
    from local_ai_hub import deterministic

    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * 64)
    monkeypatch.setattr(deterministic, "_SECRET_SCAN_MAX_FILE_BYTES", 16)

    result = DeterministicEngine().secret_scan(str(tmp_path))

    assert result["coverage"]["bytes_read"] <= 16
    assert "file_bytes" in result["coverage"]["limits_hit"]
    assert result["scan_complete"] is False


def test_long_line_does_not_shift_following_secret_line_number(tmp_path: Path) -> None:
    source = tmp_path / "config.py"
    source.write_bytes(b"x" * 65_537 + b"\napi_key = \"sk-EXAMPLEabcdefghijklmnop\"\n")

    result = DeterministicEngine().secret_scan(str(tmp_path))

    finding = next(item for item in result["findings"] if item["rule"] == "openai_api_key")
    assert finding["line"] == 2
    assert finding["redacted_snippet"] == "credential-like value omitted"
    assert result["scan_complete"] is False


def test_comment_and_low_entropy_credentials_remain_visible(tmp_path: Path) -> None:
    source = tmp_path / "config.py"
    source.write_text(
        '# token = "sk-proj-123456789012345678901234"\n'
        '# api_key = "aaaaaaaaaaaaaaaa"\n',
        encoding="utf-8",
    )

    result = DeterministicEngine().secret_scan(str(tmp_path))

    assert {item["rule"] for item in result["findings"]} == {
        "openai_api_key", "generic_secret_assignment"
    }
    assert all(item["triage_status"] == "untriaged" for item in result["findings"])
