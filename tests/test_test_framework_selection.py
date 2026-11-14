import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.test_framework_selection import detect_test_framework, select_test_framework


@pytest.mark.parametrize(
    ("framework", "command"),
    [
        ("pytest", "python -m pytest"),
        ("dotnet", "dotnet test"),
        ("npm", "npm test"),
        ("cargo", "cargo test"),
        ("go", "go test ./..."),
        ("pest", "vendor/bin/pest"),
        ("phpunit", "vendor/bin/phpunit"),
        ("unknown", ""),
    ],
)
def test_framework_selection_preserves_supported_run_commands(framework, command):
    assert select_test_framework([framework]) == (framework, command)


def test_framework_selection_preserves_candidate_priority():
    assert select_test_framework(["pytest", "dotnet"]) == ("pytest", "python -m pytest")


def test_framework_selection_ignores_unknown_candidates():
    assert select_test_framework(["unknown", "cargo"]) == ("cargo", "cargo test")


def test_detection_keeps_python_priority_without_reading_php_manifest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "composer.json").write_text("invalid json", encoding="utf-8")

    assert DeterministicEngine._detect_test_framework(tmp_path) == (
        "pytest",
        "python -m pytest",
        False,
        [],
    )


def test_detection_keeps_dotnet_ahead_of_npm(tmp_path):
    (tmp_path / "project.csproj").write_text("<Project />", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    assert DeterministicEngine._detect_test_framework(tmp_path) == (
        "dotnet",
        "dotnet test",
        False,
        [],
    )


def test_detection_keeps_pest_ahead_of_phpunit(tmp_path):
    (tmp_path / "composer.json").write_text(
        '{"require":{"pestphp/pest":"*","phpunit/phpunit":"*"}}',
        encoding="utf-8",
    )

    assert DeterministicEngine._detect_test_framework(tmp_path) == (
        "pest",
        "vendor/bin/pest",
        False,
        [],
    )


def test_extracted_detection_reports_unreadable_composer_manifest(tmp_path):
    (tmp_path / "composer.json").write_text("invalid json", encoding="utf-8")

    assert detect_test_framework(tmp_path) == (
        "unknown",
        "",
        True,
        ["composer_manifest_unreadable"],
    )
