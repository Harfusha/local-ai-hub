from __future__ import annotations

import subprocess
from pathlib import Path

from local_ai_hub.project_config import resolve_project_config


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=True,
    )
    return result.stdout.strip()


def test_linked_worktree_inherits_common_config_and_keeps_local_override(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    primary.mkdir()
    _git(primary, "init", "--quiet")
    _git(primary, "config", "user.email", "test@example.invalid")
    _git(primary, "config", "user.name", "Test")
    (primary / ".local-ai.toml").write_text(
        'exclude_paths = ["tracked/**"]\n'
        '[path_overrides]\n'
        '"src/**" = "exclude"\n'
        '"generated/**" = "include"\n',
        encoding="utf-8",
    )
    (primary / "README.md").write_text("test\n", encoding="utf-8")
    _git(primary, "add", ".local-ai.toml", "README.md")
    _git(primary, "commit", "--quiet", "-m", "fixture")
    _git(primary, "worktree", "add", "--quiet", "--detach", str(linked), "HEAD")

    common = Path(_git(primary, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (primary / common).resolve()
    info_config = common / "info" / "local-ai.toml"
    info_config.parent.mkdir(parents=True, exist_ok=True)
    info_config.write_text(
        'shared_namespace = "shared"\n'
        '[path_overrides]\n'
        '"src/main.py" = "include"\n'
        '"generated/**" = "exclude"\n',
        encoding="utf-8",
    )
    (linked / ".local-ai.worktree.toml").write_text(
        'exclude_paths = ["local/**"]\n'
        'shared_namespace = "worktree"\n'
        '[path_overrides]\n'
        '"src/main.py" = "exclude"\n'
        '"local/**" = "include"\n',
        encoding="utf-8",
    )

    primary_result = resolve_project_config(primary)
    linked_result = resolve_project_config(linked)

    assert primary_result.settings.shared_namespace == "shared"
    assert linked_result.settings.shared_namespace == "worktree"
    assert primary_result.settings.exclude_paths == ("tracked/**",)
    assert linked_result.settings.exclude_paths == ("local/**",)
    assert primary_result.settings.path_overrides == {
        "src/**": "exclude",
        "generated/**": "exclude",
        "src/main.py": "include",
    }
    assert linked_result.settings.path_overrides == {
        "src/**": "exclude",
        "generated/**": "exclude",
        "src/main.py": "exclude",
        "local/**": "include",
    }
    assert "git_common" in linked_result.active_sources
    assert "worktree" in linked_result.active_sources


def test_missing_git_uses_project_settings_only(tmp_path: Path, monkeypatch) -> None:
    import local_ai_hub.project_config as project_config

    common = tmp_path / "fake.git"
    (common / "info").mkdir(parents=True)
    (common / "info" / "local-ai.toml").write_text(
        'shared_namespace = "must-not-load"\n', encoding="utf-8"
    )
    (tmp_path / ".local-ai.toml").write_text(
        'project_type = "python"\n', encoding="utf-8"
    )
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)

    result = resolve_project_config(tmp_path)

    assert result.settings.project_type == "python"
    assert result.settings.shared_namespace is None
    assert result.active_sources == ("defaults", "project")
