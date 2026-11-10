from pathlib import Path

from local_ai_hub.repo_tools import is_root_archive_path


def test_root_archive_path_classification_is_cached_and_stable() -> None:
    cases = {
        "src/local_ai_hub/app.py": False,
        "docs/integration/archive/old.py": True,
        ".validation/run/test_generated.py": True,
        "artifacts/generated_report.py": True,
        "docs/guide.md": False,
    }

    is_root_archive_path.cache_clear()
    for path, expected in cases.items():
        assert is_root_archive_path(path) is expected
    misses_after_first_pass = is_root_archive_path.cache_info().misses

    for path, expected in cases.items():
        assert is_root_archive_path(path) is expected

    cache = is_root_archive_path.cache_info()
    assert cache.misses == misses_after_first_pass
    assert cache.hits == len(cases)
    assert is_root_archive_path(Path("docs/integration/archive/old.py")) is True
