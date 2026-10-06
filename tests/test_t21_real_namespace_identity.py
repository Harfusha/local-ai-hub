from __future__ import annotations

import subprocess
from pathlib import Path

from local_ai_hub.process_utils import run_hidden
from local_ai_hub.project_config import resolve_project_context


def _git(root: Path, *arguments: str) -> None:
    run_hidden(
        ["git", *arguments],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=True,
    )


def test_real_git_worktree_namespace_is_inherited_but_unrelated_repo_is_not(tmp_path):
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    unrelated = tmp_path / "unrelated"
    primary.mkdir()
    unrelated.mkdir()
    _git(primary, "init", "--quiet")
    _git(unrelated, "init", "--quiet")
    (primary / ".local-ai.toml").write_text(
        'shared_namespace = "team"\n', encoding="utf-8"
    )
    (unrelated / ".local-ai.toml").write_text(
        'shared_namespace = "team"\n', encoding="utf-8"
    )
    _git(primary, "add", ".local-ai.toml")
    _git(
        primary,
        "-c", "user.name=Fixture",
        "-c", "user.email=fixture@example.invalid",
        "commit", "--quiet", "-m", "identity fixture",
    )
    _git(primary, "worktree", "add", "--quiet", "--detach", str(linked), "HEAD")

    state = tmp_path / "state"
    primary_context = resolve_project_context(primary, state)
    linked_context = resolve_project_context(linked, state)
    unrelated_context = resolve_project_context(unrelated, state)

    assert not primary_context.resolution.error_codes
    assert not linked_context.resolution.error_codes
    assert primary_context.coordination_id is not None
    assert linked_context.coordination_id == primary_context.coordination_id
    assert unrelated_context.coordination_id != primary_context.coordination_id
    assert linked_context.root == linked.resolve()
    assert primary_context.root == primary.resolve()

    (linked / ".local-ai.worktree.toml").write_text(
        'shared_namespace = "separate"\n', encoding="utf-8"
    )
    overridden = resolve_project_context(linked, state)
    assert overridden.settings.shared_namespace == "separate"
    assert overridden.coordination_id != primary_context.coordination_id
    assert overridden.root == linked_context.root
