from pathlib import Path

import pytest

from tools import repeat_t02_pytest


def test_repeat_count_is_bounded() -> None:
    assert repeat_t02_pytest._validate_repeat_count(1) == 1
    assert repeat_t02_pytest._validate_repeat_count(25) == 25
    assert repeat_t02_pytest._validate_repeat_count(50) == 50
    for value in (0, 51, True):
        with pytest.raises(ValueError, match="between 1 and 50"):
            repeat_t02_pytest._validate_repeat_count(value)


def test_output_directory_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(ValueError, match="outside the repository"):
        repeat_t02_pytest._resolve_external_output(repository / "receipts", repository)


def test_attempt_command_pins_pytest_and_allowed_selector(tmp_path: Path) -> None:
    selector = repeat_t02_pytest._TARGET_SELECTOR
    scratch = tmp_path / "attempt-001"
    command = repeat_t02_pytest._command_for_attempt("python", selector, scratch)

    assert command == [
        "python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--tb=short", "--basetemp", str(scratch), selector,
    ]
    with pytest.raises(ValueError, match="unsupported T02 selector"):
        repeat_t02_pytest._command_for_attempt("python", "tests/test_anything.py", scratch)
