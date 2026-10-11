from pathlib import Path

import pytest

from tools.release_check import _iter_release_hygiene_violations


def _python_caches(root: Path) -> None:
    cache = root / "src" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.cpython-313.pyc").write_bytes(b"cache")
    (root / "legacy.pyc").write_bytes(b"cache")
    (root / "legacy.pyo").write_bytes(b"cache")


def test_working_tree_ignores_python_caches_but_rejects_durable_payload(tmp_path):
    _python_caches(tmp_path)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "agent_state.sqlite3").write_bytes(b"durable")

    violations = list(_iter_release_hygiene_violations(tmp_path))

    assert violations == ["runtime/build payload: agent_state.sqlite3"]


def test_strict_release_tree_ignores_python_cache_payloads(tmp_path):
    _python_caches(tmp_path)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "agent_state.sqlite3").write_bytes(b"durable")

    violations = list(_iter_release_hygiene_violations(tmp_path, strict_tree=True))

    assert violations == ["runtime/build payload: agent_state.sqlite3"]


@pytest.mark.parametrize("options", [{"post_test": True}, {"allow_installed": True}])
def test_strict_release_tree_cannot_allow_workspace_payloads(tmp_path, options):
    with pytest.raises(ValueError, match="strict_tree cannot allow"):
        list(_iter_release_hygiene_violations(tmp_path, strict_tree=True, **options))
