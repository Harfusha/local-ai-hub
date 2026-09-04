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


def test_path_escape_is_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = _cfg(tmp_path)
    result = RepositoryTools(cfg).file_slice(str(repo), "../secret.txt", 1, 10)
    assert result["success"] is False


def test_git_diff_on_non_git_root_is_a_terminal_client_result(tmp_path: Path):
    root = tmp_path / "plain-files"
    root.mkdir()

    result = RepositoryTools(_cfg(tmp_path)).git_diff(str(root))

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["error"] == "git diff requires a Git repository"
