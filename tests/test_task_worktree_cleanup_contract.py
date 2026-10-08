from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint, TaskStore
from local_ai_hub.process_utils import create_git_worktree, remove_git_worktree


def _repo(root: Path) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "a.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "init"],
        check=True,
    )
    return root.resolve()


def _task(tmp_path: Path, repo: Path) -> tuple[TaskStore, object]:
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    task = tasks.create(
        GoalContract(goal="owned worktree cleanup", acceptance_criteria=["feature"]),
        ScopeContext(repository_id=str(repo)),
        actor="owner-a",
        auto_worktree=True,
    )
    return tasks, task


def _discard_worktree(repo: Path, metadata: dict[str, object]) -> None:
    worktree = Path(str(metadata["worktree_path"]))
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        check=False,
    )
    branch = str(metadata.get("branch", ""))
    if branch:
        subprocess.run(["git", "-C", str(repo), "branch", "-D", branch], capture_output=True, check=False)
    shutil.rmtree(worktree, ignore_errors=True)


def test_worktree_cleanup_refuses_dirty_checkout_without_deleting_edits(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    created = create_git_worktree(repo, branch_name="owned-task", worktree_path=tmp_path / "owned")
    worktree = Path(created["worktree_path"])
    (worktree / "a.txt").write_text("user edits\n", encoding="utf-8")

    result = remove_git_worktree(
        repo, worktree, branch_name="owned-task", worktree_id=created.get("worktree_id")
    )

    assert result["success"] is False
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "user edits\n"
    _discard_worktree(repo, {**created, "branch": "owned-task"})


def test_worktree_cleanup_requires_registered_worktree_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    created = create_git_worktree(
        repo,
        branch_name="owned-task",
        worktree_path=tmp_path / "owned",
        task_id="task-owned",
        owner="owner-a",
    )
    worktree = Path(created["worktree_path"])

    result = remove_git_worktree(repo, worktree, branch_name="owned-task")

    assert result["success"] is False
    assert worktree.is_dir()
    _discard_worktree(repo, created)


def test_worktree_cleanup_rejects_checkout_owned_by_another_repository(tmp_path: Path) -> None:
    repo_a = _repo(tmp_path / "repo-a")
    repo_b = _repo(tmp_path / "repo-b")
    created = create_git_worktree(repo_b, branch_name="repo-b-task", worktree_path=tmp_path / "repo-b-checkout")
    worktree = Path(created["worktree_path"])

    result = remove_git_worktree(
        repo_a, worktree, branch_name="repo-b-task", worktree_id=created["worktree_id"]
    )

    assert result["success"] is False
    assert worktree.is_dir()
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "baseline\n"
    _discard_worktree(repo_b, {**created, "branch": "repo-b-task"})


def test_worktree_cleanup_rejects_branch_changed_since_creation(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    created = create_git_worktree(repo, branch_name="owned-task", worktree_path=tmp_path / "owned")
    worktree = Path(created["worktree_path"])
    subprocess.run(["git", "-C", str(worktree), "switch", "-c", "replacement-task"], check=True)

    result = remove_git_worktree(
        repo, worktree, branch_name="owned-task", worktree_id=created["worktree_id"]
    )

    assert result["success"] is False
    assert worktree.is_dir()
    _discard_worktree(repo, {**created, "branch": "replacement-task"})
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "owned-task"], capture_output=True, check=False)


def test_task_cleanup_requires_owner_and_preserves_dirty_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    tasks, task = _task(tmp_path, repo)
    metadata = task.checkpoint.state_data["worktree"]
    worktree = Path(metadata["worktree_path"])
    try:
        assert metadata["task_id"] == task.task_id
        assert metadata["owner"] == "owner-a"
        foreign = tasks.cleanup_worktree(task.task_id, actor="owner-b")
        assert foreign["success"] is False
        assert worktree.is_dir()

        (worktree / "a.txt").write_text("preserve me\n", encoding="utf-8")
        dirty = tasks.cleanup_worktree(task.task_id, actor="owner-a")
        assert dirty["success"] is False
        assert (worktree / "a.txt").read_text(encoding="utf-8") == "preserve me\n"
    finally:
        _discard_worktree(repo, metadata)


def test_task_cleanup_removes_owned_clean_worktree_and_records_trace(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    tasks, task = _task(tmp_path, repo)
    metadata = task.checkpoint.state_data["worktree"]
    worktree = Path(metadata["worktree_path"])

    result = tasks.cleanup_worktree(task.task_id, actor="owner-a")

    assert result["success"] is True
    assert result["had_worktree"] is True
    assert not worktree.exists()
    cleaned = tasks.get(task.task_id)
    assert cleaned is not None
    assert cleaned.checkpoint.state_data["worktree"]["cleanup_success"] is True
    assert cleaned.checkpoint.state_data["worktree"]["cleaned_at"] > 0
    repeated = tasks.cleanup_worktree(task.task_id, actor="owner-a")
    assert repeated["success"] is True
    assert repeated["already_cleaned"] is True


@pytest.mark.parametrize(
    "field",
    ["task_id", "owner", "repo_root", "branch", "worktree_id", "created_at", "expires_at", "ttl_seconds"],
)
def test_task_cleanup_rejects_tampered_ownership_metadata(tmp_path: Path, field: str) -> None:
    repo = _repo(tmp_path / "repo")
    tasks, task = _task(tmp_path, repo)
    original = dict(task.checkpoint.state_data["worktree"])
    worktree = Path(original["worktree_path"])
    tampered = dict(original)
    changed: dict[str, object] = {
        "task_id": "foreign-task",
        "owner": "owner-b",
        "repo_root": str(tmp_path / "foreign-repo"),
        "branch": "foreign-branch",
        "worktree_id": "worktree_foreign000000",
        "created_at": float(original["created_at"]) + 60,
        "expires_at": float(original["expires_at"]) + 60,
        "ttl_seconds": float(original["ttl_seconds"]) + 60,
    }
    tampered[field] = changed[field]
    if field == "repo_root":
        with pytest.raises(ValueError, match="worktree repo_root is server-managed"):
            tasks.checkpoint(
                task.task_id,
                TaskCheckpoint(state_data={**task.checkpoint.state_data, "worktree": tampered}),
                actor="owner-a",
                idempotency_key=f"tamper-{field}",
            )
        assert tasks.get(task.task_id).checkpoint.state_data["worktree"] == original
        assert worktree.is_dir()
        assert tasks.cleanup_worktree(task.task_id, actor="owner-a")["success"] is True
        return
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={**task.checkpoint.state_data, "worktree": tampered}),
        actor="owner-a",
        idempotency_key=f"tamper-{field}",
    )

    try:
        result = tasks.cleanup_worktree(task.task_id, actor="owner-a")
        assert result["success"] is False
        assert worktree.is_dir()
    finally:
        latest = tasks.get(task.task_id)
        if worktree.is_dir() and latest is not None:
            tasks.checkpoint(
                task.task_id,
                TaskCheckpoint(state_data={**latest.checkpoint.state_data, "worktree": original}),
                actor="owner-a",
                idempotency_key=f"restore-{field}",
            )
            tasks.cleanup_worktree(task.task_id, actor="owner-a")


@pytest.mark.parametrize("actor", ["http-default", "system", "admin", "*", ""])
def test_task_cleanup_rejects_reserved_or_missing_actor(tmp_path: Path, actor: str) -> None:
    repo = _repo(tmp_path / "repo")
    tasks, task = _task(tmp_path, repo)
    metadata = task.checkpoint.state_data["worktree"]
    worktree = Path(metadata["worktree_path"])
    try:
        result = tasks.cleanup_worktree(task.task_id, actor=actor)
        assert result["success"] is False
        assert worktree.is_dir()
    finally:
        _discard_worktree(repo, metadata)


def test_task_cleanup_rejects_foreign_worktree_and_same_repo_retarget(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    foreign_repo = _repo(tmp_path / "foreign-repo")
    foreign = create_git_worktree(foreign_repo, branch_name="foreign-task", worktree_path=tmp_path / "foreign-checkout")
    tasks, task = _task(tmp_path, repo)
    original = dict(task.checkpoint.state_data["worktree"])
    own_worktree = Path(original["worktree_path"])
    tampered = {**original, "worktree_path": foreign["worktree_path"]}
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={**task.checkpoint.state_data, "worktree": tampered}),
        actor="owner-a",
        idempotency_key="foreign-path",
    )
    try:
        result = tasks.cleanup_worktree(task.task_id, actor="owner-a")
        assert result["success"] is False
        assert own_worktree.is_dir()
        assert Path(foreign["worktree_path"]).is_dir()
    finally:
        latest = tasks.get(task.task_id)
        if latest is not None:
            tasks.checkpoint(
                task.task_id,
                TaskCheckpoint(state_data={**latest.checkpoint.state_data, "worktree": original}),
                actor="owner-a",
                idempotency_key="restore-foreign-path",
            )
        _discard_worktree(repo, original)
        _discard_worktree(foreign_repo, foreign)


def test_task_cleanup_rejects_same_repository_foreign_worktree_retarget(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    foreign = create_git_worktree(repo, branch_name="foreign-task", worktree_path=tmp_path / "foreign-checkout")
    tasks, task = _task(tmp_path, repo)
    original = dict(task.checkpoint.state_data["worktree"])
    own_worktree = Path(original["worktree_path"])
    retargeted = {
        **original,
        "worktree_path": foreign["worktree_path"],
        "branch": foreign["branch"],
        "worktree_id": foreign.get("worktree_id"),
    }
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={**task.checkpoint.state_data, "worktree": retargeted}),
        actor="owner-a",
        idempotency_key="same-repo-retarget",
    )
    try:
        result = tasks.cleanup_worktree(task.task_id, actor="owner-a")
        assert result["success"] is False
        assert own_worktree.is_dir()
        assert Path(foreign["worktree_path"]).is_dir()
    finally:
        latest = tasks.get(task.task_id)
        if latest is not None:
            tasks.checkpoint(
                task.task_id,
                TaskCheckpoint(state_data={**latest.checkpoint.state_data, "worktree": original}),
                actor="owner-a",
                idempotency_key="restore-same-repo-retarget",
            )
        _discard_worktree(repo, original)
        _discard_worktree(repo, foreign)
