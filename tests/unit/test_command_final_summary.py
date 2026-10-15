"""Deferred output fixtures; these tests never invoke pytest subprocesses."""

import pytest

from local_ai_hub.command_summary import pytest_output_summary
from local_ai_hub.response_budget import budget_response


def test_long_skip_details_do_not_replace_reported_counts():
    output = "SKIPPED tests/long_path.py: missing optional dependency\n" * 2000
    output += "================ 59 passed, 3 skipped in 4.25s ================\n"
    summary = pytest_output_summary(output, "")
    assert summary == {
        "framework": "pytest", "source": "captured_final_summary",
        "counts": {"passed": 59, "skipped": 3}, "elapsed_seconds": 4.25,
    }
    bounded = budget_response({"success": True, "stdout": output, "test_summary": summary},
                              max_tokens=400, protected_keys=("test_summary",))
    assert bounded["test_summary"] == summary
    assert "output_artifact_id" not in bounded


@pytest.mark.parametrize("output", ["tests.py .... [100%]", "59 passed", "3 failed in ??s", "test says 8 passed in 0.1s"])
def test_progress_or_incomplete_output_never_invents_summary(output):
    assert pytest_output_summary(output, "") is None


def test_failed_count_and_ansi_summary_are_preserved():
    result = pytest_output_summary("\x1b[31m2 failed, 1 error, 3 warnings in 0.30s\x1b[0m\n", "")
    assert result["counts"] == {"failed": 2, "errors": 1, "warnings": 3}


def test_latest_framework_summary_wins():
    result = pytest_output_summary("1 passed in 0.10s\n2 passed in 0.20s\n", "")
    assert result["counts"] == {"passed": 2}
