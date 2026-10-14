import sys
from pathlib import Path
import pytest

from local_ai_hub.commands import CommandBroker


def test_pytest_failure_output_parses_into_failed_tests():
    sample_pytest_output = """
=================================== FAILURES ===================================
________________________ test_database_connection_timeout ________________________
tests/unit/test_db.py:42: in test_database_connection_timeout
    assert conn.is_connected() is True
E   AssertionError: connection timed out
=========================== short test summary info ===========================
FAILED tests/unit/test_db.py::test_database_connection_timeout - AssertionError: connection timed out
FAILED tests/unit/test_auth.py::test_invalid_token - PermissionError: token expired
1 failed in 0.50s
"""
    result = {
        "success": False,
        "exit_code": 1,
        "stdout": sample_pytest_output,
        "stderr": "",
    }
    failed = CommandBroker._extract_failed_tests(result)
    assert len(failed) == 2
    assert failed[0]["name"] == "test_database_connection_timeout"
    assert failed[0]["file"] == "tests/unit/test_db.py"
    assert failed[0]["line"] == 42
    assert "connection timed out" in failed[0]["error_message"]

    assert failed[1]["name"] == "test_invalid_token"
    assert failed[1]["file"] == "tests/unit/test_auth.py"
    assert "token expired" in failed[1]["error_message"]


def test_cargo_failure_output_parses_into_failed_tests():
    sample_cargo_output = """
running 2 tests
test test_ok ... ok
test tests::test_parse_failure ... FAILED

failures:

---- tests::test_parse_failure stdout ----
thread 'tests::test_parse_failure' panicked at 'assertion failed: false', src/parser.rs:88:5
"""
    result = {
        "success": False,
        "exit_code": 101,
        "stdout": sample_cargo_output,
        "stderr": "",
    }
    failed = CommandBroker._extract_failed_tests(result)
    assert len(failed) == 1
    assert failed[0]["name"] == "tests::test_parse_failure"
    assert failed[0]["file"] == "src/parser.rs"
    assert failed[0]["line"] == 88
    assert "assertion failed: false" in failed[0]["error_message"]


def test_run_command_includes_failed_tests(tmp_path: Path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    fake_pytest = f'"{sys.executable}" -c "print(\'FAILED tests/test_app.py::test_feature - AssertionError: fail\'); import sys; sys.exit(1)"'
    res = broker.run(fake_pytest, str(tmp_path))
    assert res["success"] is False
    assert "failed_tests" in res
    assert len(res["failed_tests"]) == 1
    assert res["failed_tests"][0]["name"] == "test_feature"
    assert res["failed_tests"][0]["file"] == "tests/test_app.py"
