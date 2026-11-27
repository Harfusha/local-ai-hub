from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_ai_hub.opencode_workspace import (
    UnsafeWorkspacePathError,
    WorkspaceTransferError,
    apply_workspace_changes,
    create_workspace_snapshot,
)


def test_snapshot_applies_only_conflict_free_changes(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "keep.txt").write_text("same", encoding="utf-8")
    (project / "edit.txt").write_text("before", encoding="utf-8")
    (project / "remove.txt").write_text("remove", encoding="utf-8")

    snapshot = create_workspace_snapshot(project, stage)
    (stage / "edit.txt").write_text("after", encoding="utf-8")
    (stage / "remove.txt").unlink()
    (stage / "nested").mkdir()
    (stage / "nested" / "new.txt").write_text("new", encoding="utf-8")

    result = apply_workspace_changes(snapshot)

    assert result.applied == ("edit.txt", "nested/new.txt", "remove.txt")
    assert result.conflicts == ()
    assert (project / "edit.txt").read_text(encoding="utf-8") == "after"
    assert not (project / "remove.txt").exists()
    assert (project / "nested" / "new.txt").read_text(encoding="utf-8") == "new"
    assert (project / "keep.txt").read_text(encoding="utf-8") == "same"


def test_snapshot_conflicts_leave_other_staged_changes_unapplied(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "conflict.txt").write_text("base", encoding="utf-8")

    snapshot = create_workspace_snapshot(project, stage)
    (stage / "conflict.txt").write_text("agent", encoding="utf-8")
    (stage / "new.txt").write_text("new", encoding="utf-8")
    (project / "conflict.txt").write_text("user", encoding="utf-8")

    result = apply_workspace_changes(snapshot)

    assert result.applied == ()
    assert result.conflicts == ("conflict.txt",)
    assert (project / "conflict.txt").read_text(encoding="utf-8") == "user"
    assert not (project / "new.txt").exists()


def test_snapshot_conflicts_when_source_file_was_deleted_after_capture(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "edit.txt").write_text("base", encoding="utf-8")

    snapshot = create_workspace_snapshot(project, stage)
    (stage / "edit.txt").write_text("agent", encoding="utf-8")
    (project / "edit.txt").unlink()

    result = apply_workspace_changes(snapshot)

    assert result.applied == ()
    assert result.conflicts == ("edit.txt",)
    assert not (project / "edit.txt").exists()


def test_snapshot_conflicts_when_new_file_collides_with_source_directory(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    snapshot = create_workspace_snapshot(project, stage)
    (stage / "collision").write_text("agent", encoding="utf-8")
    (project / "collision").mkdir()

    result = apply_workspace_changes(snapshot)

    assert result.applied == ()
    assert result.conflicts == ("collision",)
    assert (project / "collision").is_dir()


def test_snapshot_enforces_file_limit_before_copying(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "one.txt").write_text("one", encoding="utf-8")
    (project / "two.txt").write_text("two", encoding="utf-8")

    with pytest.raises(UnsafeWorkspacePathError, match="size limit"):
        create_workspace_snapshot(project, stage, max_files=1)

    assert list(stage.iterdir()) == []


def test_snapshot_rejects_replaced_stage_root(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "file.txt").write_text("base", encoding="utf-8")
    snapshot = create_workspace_snapshot(project, stage)

    stage.rename(tmp_path / "old-stage")
    stage.mkdir()
    (stage / "file.txt").write_text("agent", encoding="utf-8")

    with pytest.raises(UnsafeWorkspacePathError, match="identity changed"):
        apply_workspace_changes(snapshot)


def test_snapshot_never_copies_git_metadata_back(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    (project / ".git").mkdir(parents=True)
    stage.mkdir()
    (project / ".git" / "config").write_text("base", encoding="utf-8")

    snapshot = create_workspace_snapshot(project, stage)
    (stage / ".git" / "config").write_text("agent", encoding="utf-8")

    result = apply_workspace_changes(snapshot)

    assert result.applied == ()
    assert result.conflicts == ()
    assert (project / ".git" / "config").read_text(encoding="utf-8") == "base"


def test_snapshot_rolls_back_prior_file_when_a_later_replace_fails(tmp_path: Path, monkeypatch):
    import local_ai_hub.opencode_workspace as workspace

    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "a.txt").write_text("base-a", encoding="utf-8")
    (project / "b.txt").write_text("base-b", encoding="utf-8")
    snapshot = create_workspace_snapshot(project, stage)
    (stage / "a.txt").write_text("agent-a", encoding="utf-8")
    (stage / "b.txt").write_text("agent-b", encoding="utf-8")

    replace = workspace.os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second-file failure")
        replace(source, destination)

    monkeypatch.setattr(workspace.os, "replace", fail_second_replace)
    with pytest.raises(WorkspaceTransferError, match="rolled back"):
        apply_workspace_changes(snapshot)

    assert (project / "a.txt").read_text(encoding="utf-8") == "base-a"
    assert (project / "b.txt").read_text(encoding="utf-8") == "base-b"
    assert sorted(path.name for path in project.iterdir()) == ["a.txt", "b.txt"]


def test_snapshot_retains_recovery_backup_if_rollback_fails(tmp_path: Path, monkeypatch):
    import local_ai_hub.opencode_workspace as workspace

    project = tmp_path / "project"
    stage = tmp_path / "stage"
    project.mkdir()
    stage.mkdir()
    (project / "a.txt").write_text("base-a", encoding="utf-8")
    (project / "b.txt").write_text("base-b", encoding="utf-8")
    snapshot = create_workspace_snapshot(project, stage)
    (stage / "a.txt").write_text("agent-a", encoding="utf-8")
    (stage / "b.txt").write_text("agent-b", encoding="utf-8")

    replace = workspace.os.replace
    calls = 0

    def fail_commit_and_rollback(source, destination):
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError("injected commit/rollback failure")
        replace(source, destination)

    monkeypatch.setattr(workspace.os, "replace", fail_commit_and_rollback)
    with pytest.raises(WorkspaceTransferError, match="rollback could not be confirmed") as error:
        apply_workspace_changes(snapshot)

    recovery = [Path(path) for path in error.value.recovery_paths]
    try:
        assert recovery
        assert all(path.exists() for path in recovery)
        assert any(path.read_text(encoding="utf-8") == "base-a" for path in recovery)
    finally:
        for path in recovery:
            path.unlink(missing_ok=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-share semantics only")
def test_workspace_tree_lock_prevents_nested_directory_replacement(tmp_path: Path):
    import local_ai_hub.opencode_workspace as workspace

    project = tmp_path / "project"
    nested = project / "nested"
    project.mkdir()
    nested.mkdir()
    replacement = project / "replacement"

    with workspace._lock_workspace_tree(project):
        with pytest.raises(OSError):
            nested.rename(replacement)

    assert nested.is_dir()
    assert not replacement.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_snapshot_rejects_source_symlinks_without_reading_external_content(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    external = tmp_path / "outside.txt"
    project.mkdir()
    stage.mkdir()
    external.write_text("outside", encoding="utf-8")
    try:
        (project / "escape.txt").symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(UnsafeWorkspacePathError, match="reparse|symbolic link"):
        create_workspace_snapshot(project, stage)

    assert list(stage.iterdir()) == []


def test_snapshot_rejects_staged_symlinks_before_copyback(tmp_path: Path):
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    external = tmp_path / "outside.txt"
    project.mkdir()
    stage.mkdir()
    (project / "safe.txt").write_text("base", encoding="utf-8")
    external.write_text("outside", encoding="utf-8")
    snapshot = create_workspace_snapshot(project, stage)
    (stage / "safe.txt").write_text("changed", encoding="utf-8")
    try:
        (stage / "escape.txt").symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(UnsafeWorkspacePathError, match="reparse|symbolic link"):
        apply_workspace_changes(snapshot)

    assert (project / "safe.txt").read_text(encoding="utf-8") == "base"
    assert (project / "outside.txt").exists() is False
