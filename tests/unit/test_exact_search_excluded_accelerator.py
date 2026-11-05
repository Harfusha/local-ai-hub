import os
from types import SimpleNamespace

import pytest

from local_ai_hub import repo_tools
from local_ai_hub.project_config import ProjectSettings
from local_ai_hub.repo_tools import RepositoryTools


def test_ripgrep_skips_literal_excluded_tree_without_losing_results(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "locked.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("needle\n", encoding="utf-8")
    settings = ProjectSettings(exclude_paths=("state/**",))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="ok.py\n", stderr="")

    monkeypatch.setattr(repo_tools.subprocess, "run", run)
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    tools._rg = "rg"

    result = tools.search(str(tmp_path), "needle", exact_count=True, project_settings=settings)

    assert ("!state/**" in calls[0]) is (os.name == "nt")
    assert result["success"] is True
    assert result["total_matches"] == 1
    assert [hit["path"] for hit in result["results"]] == ["ok.py"]


def test_ripgrep_skips_simple_excluded_config_files(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text("needle secret\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("needle\n", encoding="utf-8")
    settings = ProjectSettings(exclude_paths=("config.toml", "config.toml.bak*"))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="config.toml\nok.py\n", stderr="")

    monkeypatch.setattr(repo_tools.subprocess, "run", run)
    tools = RepositoryTools({"rag": {"extensions": [".py", ".toml"]}})
    tools._rg = "rg"

    result = tools.search(str(tmp_path), "needle", exact_count=True, project_settings=settings)

    assert ("!config.toml" in calls[0]) is (os.name == "nt")
    assert ("!config.toml.bak*" in calls[0]) is (os.name == "nt")
    assert result["success"] is True
    assert result["total_matches"] == 1
    assert [hit["path"] for hit in result["results"]] == ["ok.py"]


def test_excluded_tree_acceleration_matches_complete_fallback(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ignored.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "first.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "second.py").write_text("needle needle\n", encoding="utf-8")
    settings = ProjectSettings(exclude_paths=("state/**",))
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    tools._rg = "rg"
    monkeypatch.setattr(repo_tools.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
        returncode=0, stdout="first.py\nsecond.py\n", stderr=""))
    accelerated = tools.search(str(tmp_path), "needle", limit=10, exact_count=True, project_settings=settings)
    monkeypatch.setattr(repo_tools.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
        returncode=2, stdout="", stderr=""))
    fallback = tools.search(str(tmp_path), "needle", limit=10, exact_count=True, project_settings=settings)

    assert accelerated["success"] is fallback["success"] is True
    assert accelerated["total_matches"] == fallback["total_matches"]
    assert accelerated["results"] == fallback["results"]


@pytest.mark.skipif(os.name == "nt", reason="distinct case paths require a case-sensitive filesystem")
def test_posix_project_excludes_do_not_hide_other_case(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "STATE").mkdir()
    (tmp_path / "state" / "ignored.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "STATE" / "included.py").write_text("needle\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    if not tools._rg:
        pytest.skip("ripgrep unavailable")

    result = tools.search(str(tmp_path), "needle", exact_count=True,
                          project_settings=ProjectSettings(exclude_paths=("state/**",)))

    assert result["success"] is True
    assert [hit["path"] for hit in result["results"]] == ["STATE/included.py"]
