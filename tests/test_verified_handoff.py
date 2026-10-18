from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from local_ai_hub.work_orchestrator import WorkOrchestrator
from local_ai_hub.process_utils import create_git_worktree, remove_git_worktree
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, InvalidTransitionError, TaskCheckpoint, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.project_config import resolve_project_context


class _Artifacts:
    def __init__(self):
        self.items = {}

    def put(self, text, *, kind):
        key = f"artifact-{len(self.items) + 1}"
        self.items[key] = {"text": text, "kind": kind}
        return key

    def get(self, artifact_id, max_chars=6000, section=""):
        artifact = self.items.get(artifact_id)
        if artifact is None:
            return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
        text = artifact["text"][:max_chars]
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": artifact["kind"],
            "text": text,
            "next_offset": len(text) if len(text) < len(artifact["text"]) else None,
        }


class _Leases:
    def claim_batch(self, *, owner, root, paths, ttl_seconds=900, purpose="", coordination_id=None):
        return {"success": True, "lease_id": "lease-test", "paths": paths}

    def release(self, *, owner, lease_id=""):
        return {"success": True}


class _Services:
    def __init__(self, validation_command="git diff --check", command_id="", repository_revision=""):
        self.delegate_calls = 0
        self.commands_run = []
        self.validation_command = validation_command
        self.command_id = command_id
        self.repository_revision = repository_revision

    def repo_profile(self, root):
        return {"success": True, "validation_commands": [self.validation_command]}

    def repo_map(self, root, max_symbols=80):
        return {"success": True, "files": ["a.txt"]}

    def test_matrix(self, root):
        return {"success": True, "commands": [self.validation_command]}

    def deterministic_query(self, root, query, limit=24):
        return {"success": True, "facts": []}

    def code_query(self, root, query, limit=20):
        return {"success": True, "symbols": []}

    def fast_context(self, root, query, max_tokens):
        return {"success": True, "evidence": []}

    def repo_diff(self, root, base="HEAD", staged=False, max_tokens=5000):
        diff = subprocess.run(["git", "-C", root, "diff"], capture_output=True, text=True, check=True).stdout
        return {"success": True, "diff": diff, "changed_files": ["a.txt"] if diff else []}

    def delegate_repo(self, args):
        self.delegate_calls += 1
        if self.delegate_calls == 1:
            plan = {
                "summary": "edit then validate",
                "needs_agent": False,
                "steps": [
                    {"id": "edit", "kind": "edit", "task": "replace old with new", "depends_on": [], "acceptance": ["tests pass"]},
                    {"id": "validate", "kind": "validate", "task": "run validation", "depends_on": ["edit"], "acceptance": ["tests pass"]},
                ],
                "validation_commands": [self.validation_command],
            }
            return {"success": True, "text": json.dumps(plan)}
        return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}

    def second_opinion(self, args):
        return {"success": True, "text": json.dumps({
            "passed": True,
            "summary": "model says tests pass",
            "criteria": [{"criterion": "tests pass", "passed": True}],
            "risks": [],
        })}

    def command(self, args):
        if args.get("action") == "discover":
            return {"success": True, "validation_commands": [self.validation_command]}
        self.commands_run.append(args.get("command"))
        return {
            "success": True, "exit_code": 0, "error": "",
            "execution_id": self.command_id,
            "repository_revision": self.repository_revision if self.command_id else "",
        }


def _repo(root: Path) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "init"], check=True)
    return root


def _repository_scope(repo: Path, state_dir: Path) -> ScopeContext:
    return ScopeContext(
        repository_id=resolve_project_context(str(repo), state_dir).coordination_id
    )


def _wait(orch: WorkOrchestrator, work_id: str):
    deadline = time.time() + 8
    while time.time() < deadline:
        result = orch.get(work_id, profile="debug")
        if result.get("status") in {"complete", "failed", "cancelled", "needs_agent", "partial"}:
            return result
        time.sleep(0.05)
    raise AssertionError(orch.get(work_id, profile="debug"))


def _run_handoff(tmp_path, validation_command="git diff --check", command_id=""):
    root = _repo(tmp_path / "repo")
    state = tmp_path / "state"
    artifacts = _Artifacts()
    repository_revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    services = _Services(validation_command, command_id, repository_revision)
    task_state = AgentStateStore(state / "agent-state.sqlite3")
    tasks = TaskStore(task_state)
    task_id = "verified-handoff-task"
    repository_id = resolve_project_context(str(root), state).coordination_id
    tasks.create(
        GoalContract(goal="verified handoff", acceptance_criteria=["tests pass"]),
        ScopeContext(repository_id=repository_id),
        task_id=task_id,
        actor="handoff-owner",
        repo_root=str(root),
    )
    verification_store = VerificationStore(task_state, task_store=tasks, artifact_store=artifacts)
    orch = WorkOrchestrator(
        {"work_orchestrator": {"enabled": True, "max_steps": 16, "max_llm_steps": 10, "max_seconds": 60, "step_retry_limit": 0}},
        state,
        services,
        None,
        _Leases(),
        artifacts,
        verification_store=verification_store,
    )
    try:
        submitted = orch.submit({
            "root": str(root.resolve()),
            "task": "change a.txt and verify tests",
            "task_id": task_id,
            "acceptance_criteria": ["tests pass"],
        })
        result = _wait(orch, submitted["work_id"])
        return result, services, artifacts
    finally:
        orch.close()


def test_model_pass_and_diff_check_cannot_complete_test_criterion(tmp_path):
    result, services, _ = _run_handoff(tmp_path)
    assert "git diff --check" in services.commands_run
    assert result["status"] != "complete", result
    assert "receipt" in result.get("error", "").lower()


def test_successful_test_command_receipt_can_complete_test_criterion(tmp_path):
    result, services, _ = _run_handoff(tmp_path, "python -m pytest -q", "cmd-test-1")
    assert services.commands_run == ["python -m pytest -q"]
    assert result["status"] == "complete", result
    assert result["verification"]["receipt_gate"]["satisfied_criteria"] == ["tests pass"]


def test_worktree_creation_returns_separate_checkout_identity_and_owner_metadata(tmp_path):
    repo = _repo(tmp_path / "repo")
    created = create_git_worktree(
        repo,
        branch_name="owned-task",
        task_id="task-owned",
        owner="worker-1",
        created_at=100.0,
        ttl_seconds=120.0,
        expires_at=220.0,
    )

    assert created["success"] is True
    assert created["worktree_id"]
    assert created["worktree_id"] != created["lease_id"]
    assert created["task_id"] == "task-owned"
    assert created["owner"] == "worker-1"
    assert created["repo_root"] == str(repo.resolve())
    assert created["branch"] == "owned-task"
    assert created["created_at"] == 100.0
    assert created["ttl_seconds"] == 120.0
    assert created["expires_at"] == 220.0


@pytest.mark.parametrize(
    "metadata",
    [
        {"created_at": "invalid"},
        {"ttl_seconds": "invalid"},
        {"expires_at": "invalid"},
        {"created_at": float("nan")},
        {"ttl_seconds": float("inf")},
        {"expires_at": float("-inf")},
    ],
)
def test_worktree_creation_rejects_invalid_metadata_before_creating_checkout(tmp_path, metadata):
    repo = _repo(tmp_path / "repo")
    checkout = tmp_path / "checkout"

    result = create_git_worktree(
        repo, branch_name="bad-metadata", worktree_path=checkout, **metadata
    )

    assert result["success"] is False
    assert not checkout.exists()
    assert "metadata" in result["error"]


def test_worktree_cleanup_preserves_dirty_checkout(tmp_path):
    repo = _repo(tmp_path / "repo")
    created = create_git_worktree(repo, branch_name="owned-task", worktree_path=tmp_path / "owned")
    worktree = Path(created["worktree_path"])
    (worktree / "a.txt").write_text("user changes\n", encoding="utf-8")

    removed = remove_git_worktree(repo, worktree, branch_name="owned-task", worktree_id=created["worktree_id"])

    assert removed["success"] is False
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "user changes\n"


def test_worktree_creation_rejects_parent_traversal(tmp_path):
    repo = _repo(tmp_path / "repo")
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    escaped = temp_root / ".." / f"lah_escape_{time.time_ns()}"

    result = create_git_worktree(repo, branch_name="escaped", worktree_path=escaped)

    assert result["success"] is False
    assert "traversal" in result["error"]
    assert not escaped.resolve(strict=False).exists()


def test_worktree_creation_rejects_absolute_path_outside_temporary_root(tmp_path):
    repo = _repo(tmp_path / "repo")
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    escaped = temp_root.parent / f"lah_escape_{time.time_ns()}"

    result = create_git_worktree(repo, branch_name="escaped", worktree_path=escaped)

    assert result["success"] is False
    assert "escapes" in result["error"]
    assert not escaped.exists()


def test_worktree_cleanup_rejects_checkout_owned_by_another_repo(tmp_path):
    repo_a = _repo(tmp_path / "repo-a")
    repo_b = _repo(tmp_path / "repo-b")
    created = create_git_worktree(repo_b, branch_name="repo-b-task", worktree_path=tmp_path / "repo-b-checkout")
    worktree = Path(created["worktree_path"])

    removed = remove_git_worktree(repo_a, worktree, branch_name="repo-b-task", worktree_id=created["worktree_id"])

    assert removed["success"] is False
    assert worktree.is_dir()
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "old\n"


def test_worktree_cleanup_rejects_branch_changed_since_creation(tmp_path):
    repo = _repo(tmp_path / "repo")
    created = create_git_worktree(repo, branch_name="owned-task", worktree_path=tmp_path / "owned")
    worktree = Path(created["worktree_path"])
    switched = subprocess.run(
        ["git", "-C", str(worktree), "switch", "-c", "replacement-task"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert switched.returncode == 0, switched.stderr

    removed = remove_git_worktree(
        repo,
        worktree,
        branch_name="owned-task",
        worktree_id=created["worktree_id"],
    )

    assert removed["success"] is False
    assert worktree.is_dir()


def test_task_cleanup_checks_owner_and_preserves_dirty_worktree(tmp_path):
    repo = _repo(tmp_path / "repo")
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="safe worktree", acceptance_criteria=["feature"]),
        _repository_scope(repo, tmp_path / "project-state"),
        actor="owner-a", auto_worktree=True,
        repo_root=str(repo),
    )
    worktree_info = task.checkpoint.state_data["worktree"]
    worktree = Path(worktree_info["worktree_path"])
    try:
        assert task.lease_id == ""
        assert worktree_info["worktree_id"]
        assert worktree_info["task_id"] == task.task_id
        assert worktree_info["owner"] == "owner-a"
        assert Path(worktree_info["repo_root"]) == repo.resolve()
        assert worktree_info["branch"]
        assert worktree_info["expires_at"] == worktree_info["created_at"] + worktree_info["ttl_seconds"]
        foreign = tasks.cleanup_worktree(task.task_id, actor="owner-b")
        assert foreign["success"] is False
        assert worktree.is_dir()

        (worktree / "a.txt").write_text("keep these edits\n", encoding="utf-8")
        dirty = tasks.cleanup_worktree(task.task_id, actor="owner-a")
        assert dirty["success"] is False
        assert (worktree / "a.txt").read_text(encoding="utf-8") == "keep these edits\n"
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


def test_task_cleanup_removes_owned_clean_worktree_and_records_trace(tmp_path):
    repo = _repo(tmp_path / "repo")
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="clean owned worktree", acceptance_criteria=["feature"]),
        _repository_scope(repo, tmp_path / "project-state"),
        actor="owner-a",
        auto_worktree=True,
        repo_root=str(repo),
    )
    worktree = Path(task.checkpoint.state_data["worktree"]["worktree_path"])

    result = tasks.cleanup_worktree(task.task_id, actor="owner-a")

    assert result["success"] is True, result
    assert result["had_worktree"] is True
    assert not worktree.exists()
    cleaned = tasks.get(task.task_id)
    assert cleaned is not None
    assert cleaned.checkpoint.state_data["worktree"]["cleanup_success"] is True
    assert cleaned.checkpoint.state_data["worktree"]["cleaned_at"] > 0


@pytest.mark.parametrize(
    "field",
    ["task_id", "owner", "repo_root", "branch", "worktree_id", "created_at", "expires_at", "ttl_seconds"],
)
def test_task_cleanup_rejects_tampered_ownership_metadata(tmp_path, field):
    repo = _repo(tmp_path / "repo")
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="validate worktree identity", acceptance_criteria=["feature"]),
        _repository_scope(repo, tmp_path / "project-state"),
        actor="owner-a",
        auto_worktree=True,
        repo_root=str(repo),
    )
    original = dict(task.checkpoint.state_data["worktree"])
    worktree = Path(original["worktree_path"])
    tampered = dict(original)
    tampered[field] = {
        "task_id": "foreign-task",
        "owner": "owner-b",
        "repo_root": str(tmp_path / "foreign-repo"),
        "branch": "foreign-branch",
        "worktree_id": "wt_foreign000000",
        "created_at": original["created_at"] + 60,
        "expires_at": original["expires_at"] + 60,
        "ttl_seconds": original["ttl_seconds"] + 60,
    }[field]
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
def test_task_cleanup_rejects_reserved_or_missing_actor(tmp_path, actor):
    repo = _repo(tmp_path / "repo")
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="owner-gated cleanup", acceptance_criteria=["feature"]),
        _repository_scope(repo, tmp_path / "project-state"),
        actor="owner-a", auto_worktree=True,
        repo_root=str(repo),
    )
    worktree_info = task.checkpoint.state_data["worktree"]
    worktree = Path(worktree_info["worktree_path"])
    try:
        result = tasks.cleanup_worktree(task.task_id, actor=actor)
        assert result["success"] is False
        assert worktree.is_dir()
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


def test_task_cleanup_rejects_foreign_worktree_path(tmp_path):
    repo_a = _repo(tmp_path / "repo-a")
    repo_b = _repo(tmp_path / "repo-b")
    foreign = create_git_worktree(repo_b, branch_name="foreign-owner", worktree_path=tmp_path / "foreign-checkout")
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="safe worktree", acceptance_criteria=["feature"]),
        _repository_scope(repo_a, tmp_path / "project-state"),
        actor="owner-a", auto_worktree=True,
        repo_root=str(repo_a),
    )
    own_path = Path(task.checkpoint.state_data["worktree"]["worktree_path"])
    tampered = dict(task.checkpoint.state_data["worktree"])
    tampered["worktree_path"] = foreign["worktree_path"]
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={**task.checkpoint.state_data, "worktree": tampered}),
        actor="owner-a",
    )

    result = tasks.cleanup_worktree(task.task_id, actor="owner-a")

    assert result["success"] is False
    assert own_path.is_dir()
    assert Path(foreign["worktree_path"]).is_dir()
    shutil.rmtree(own_path, ignore_errors=True)
    shutil.rmtree(foreign["worktree_path"], ignore_errors=True)


def test_task_cleanup_rejects_same_repo_foreign_worktree_retarget(tmp_path):
    repo = _repo(tmp_path / "repo")
    foreign = create_git_worktree(
        repo,
        branch_name="foreign-task",
        worktree_path=tmp_path / "foreign-checkout",
    )
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="safe worktree", acceptance_criteria=["feature"]),
        _repository_scope(repo, tmp_path / "project-state"),
        actor="owner-a",
        auto_worktree=True,
        repo_root=str(repo),
    )
    own_worktree = dict(task.checkpoint.state_data["worktree"])
    own_path = Path(own_worktree["worktree_path"])
    retargeted = dict(own_worktree)
    retargeted["worktree_path"] = foreign["worktree_path"]
    retargeted["branch"] = foreign["branch"]
    retargeted["worktree_id"] = foreign["worktree_id"]
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(
            state_data={**task.checkpoint.state_data, "worktree": retargeted}
        ),
        actor="owner-a",
    )

    result = tasks.cleanup_worktree(task.task_id, actor="owner-a")

    assert result["success"] is False
    assert own_path.is_dir()
    assert Path(foreign["worktree_path"]).is_dir()
    shutil.rmtree(own_path, ignore_errors=True)
    shutil.rmtree(foreign["worktree_path"], ignore_errors=True)


def test_cancelled_task_cannot_reach_completed_handoff(tmp_path):
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.db"))
    task = tasks.create(
        GoalContract(goal="cancel before handoff", acceptance_criteria=["tests pass"]),
        ScopeContext(repository_id=str(tmp_path)),
        task_id="cancelled-task",
    )
    tasks.transition(task.task_id, TaskStatus.CANCELLED, reason="cancelled before verification", actor="agent", idempotency_key="cancel")

    try:
        tasks.transition(task.task_id, TaskStatus.COMPLETED, reason="attempt handoff", actor="agent", idempotency_key="complete")
    except InvalidTransitionError:
        pass
    else:
        raise AssertionError("cancelled task reached completed state")
