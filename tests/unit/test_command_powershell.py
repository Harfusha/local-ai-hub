import pytest

from local_ai_hub.command_powershell import classify_powershell_command


@pytest.mark.parametrize(
    ("command", "config", "extra_allowed", "expected_class", "expected_allowed"),
    [
        ("Invoke-WebRequest https://example.invalid", {}, set(), "dangerous", False),
        ("Set-Content file.txt value", {"allow_mutating": True}, set(), "mutating", True),
        ("Invoke-Pester -Path tests", {}, set(), "validation", True),
        ("Get-ChildItem src", {}, set(), "read", True),
        ("Write-Output hello", {}, set(), "unknown", False),
        ("Invoke-CustomTask", {"allow_validation": False}, {"customtask"}, "validation", False),
    ],
)
def test_powershell_classifier_preserves_fail_closed_policy(
    command, config, extra_allowed, expected_class, expected_allowed
):
    result = classify_powershell_command(command, config, extra_allowed)

    assert result["class"] == expected_class
    assert result["allowed"] is expected_allowed
