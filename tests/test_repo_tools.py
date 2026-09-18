from __future__ import annotations

import subprocess
from pathlib import Path

from local_ai_hub.config import load_config
from local_ai_hub.repo_tools import RepositoryTools


def _cfg(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    return load_config(str(path))


def test_generated_tool_metadata_never_enters_inventory(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("def main(): return 1\n", encoding="utf-8")
    for hidden in (".serena", ".codegraphcontext", ".local-ai-hub"):
        d = repo / hidden
        d.mkdir()
        (d / "generated.py").write_text("SHOULD_NOT_INDEX = True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    files = RepositoryTools(_cfg(tmp_path)).iter_files(str(repo))
    rel = {p.relative_to(repo).as_posix() for p in files}
    assert "src/main.py" in rel
    assert all(not p.startswith((".serena/", ".codegraphcontext/", ".local-ai-hub/")) for p in rel)


def test_unity_generated_directories_never_enter_inventory(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "Assets").mkdir(parents=True)
    (repo / "Assets" / "game.cs").write_text("class Game {}\n", encoding="utf-8")
    for generated in ("Library", "Temp", "Logs", "UserSettings"):
        d = repo / generated
        d.mkdir()
        (d / "generated.cs").write_text("class Generated {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    files = RepositoryTools(_cfg(tmp_path)).iter_files(str(repo))
    rel = {p.relative_to(repo).as_posix() for p in files}

    assert "Assets/game.cs" in rel
    assert all(not p.startswith(("Library/", "Temp/", "Logs/", "UserSettings/")) for p in rel)


def test_path_escape_is_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = _cfg(tmp_path)
    result = RepositoryTools(cfg).file_slice(str(repo), "../secret.txt", 1, 10)
    assert result["success"] is False


def test_repo_map_can_use_preindexed_paths_without_inventory(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    source = repo / "src" / "main.py"
    source.write_text("class Main:\n    pass\n", encoding="utf-8")
    tools = RepositoryTools(_cfg(tmp_path))

    monkeypatch.setattr(tools, "_git_files", lambda *_args: (_ for _ in ()).throw(AssertionError("inventory")))
    result = tools.repo_map(str(repo), paths=["src/main.py"])

    assert result["success"] is True
    assert result["files"] == 1
    assert result["symbols_sample"][0]["name"] == "Main"


def test_git_diff_on_non_git_root_is_a_terminal_client_result(tmp_path: Path):
    root = tmp_path / "plain-files"
    root.mkdir()

    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(root))

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["error"] == "git diff requires a Git repository"


def test_repository_tools_returns_revision_and_changed_paths_for_guard(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "main.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "initial"],
        check=True,
    )
    tracked.write_text("VALUE = 2\n", encoding="utf-8")

    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(repo))

    assert result["revision"]
    assert result["changed_paths"] == ["main.py"]


def test_search_returns_bounded_retryable_result_after_accelerator_timeouts(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    tools = RepositoryTools(_cfg(tmp_path))
    tools._rg = "rg"

    calls = {"n": 0}
    def fake_run(*args, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(args[0], 0.1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(tools, "iter_files", lambda *_args: (_ for _ in ()).throw(AssertionError("unbounded scan")))

    result = tools.search(str(repo), "needle")

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["error"] == "bounded search accelerators timed out or failed"
    assert calls["n"] == 2
