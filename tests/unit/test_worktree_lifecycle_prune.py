import subprocess
import tempfile
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
import local_ai_hub.process_utils as process_utils
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore
from local_ai_hub.app import LocalAIApp


@pytest.fixture(autouse=True)
def _isolate_temp_worktrees(monkeypatch, tmp_path):
    isolated_temp = tmp_path / "test-temp"
    isolated_temp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(isolated_temp))
from local_ai_hub.process_utils import create_git_worktree, remove_git_worktree, prune_git_worktrees


def _create_repo_and_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    created = create_git_worktree(repo, owner="agent-1")
    assert created.get("success") is True
    return repo, Path(created["worktree_path"]), created["worktree_id"]


def _create_owned_task(tmp_path):
    repo = tmp_path / "task-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    tasks = TaskStore(AgentStateStore(tmp_path / "agent-state.sqlite"))
    task = tasks.create(
        GoalContract("finish task"),
        ScopeContext(repository_id=str(repo)),
        task_id="task-lifecycle-test",
        actor="agent-1",
        auto_worktree=True,
        repo_root=str(repo),
        worktree_ttl_seconds=3600,
    )
    return repo, tasks, task


def _cleanup_task_worktree(repo, task):
    worktree = task.checkpoint.state_data.get("worktree", {})
    path = Path(worktree.get("worktree_path", ""))
    if path.is_dir():
        remove_git_worktree(repo, path, worktree_id=worktree.get("worktree_id", ""), force=True)


def _run_owned_task_cleanup(repo, tasks, task):
    root_head = process_utils.run_hidden(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    return tasks.cleanup_worktree(
        task.task_id, actor="agent-1", _required_base_commit=root_head,
    )

def test_remove_git_worktree_prunes_stale_metadata(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)

    # Create worktree
    res = create_git_worktree(repo, owner="agent-1")
    assert res.get("success") is True
    wt_path = res["worktree_path"]
    wt_id = res["worktree_id"]
    assert Path(wt_path).exists()

    # Add an untracked file to worktree to verify force removal works
    (Path(wt_path) / "untracked.txt").write_text("untracked")

    # Remove worktree
    del_res = remove_git_worktree(wt_path, repo_root=repo, worktree_id=wt_id, force=True)
    assert del_res.get("success") is True
    assert not Path(wt_path).exists()

    # Verify worktree list only contains the main repo
    p = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True)
    assert wt_path not in p.stdout


def test_force_remove_preserves_checkout_when_git_refuses(monkeypatch, tmp_path):
    repo, wt_path, worktree_id = _create_repo_and_worktree(tmp_path)
    marker = wt_path / "untracked.txt"
    marker.write_text("preserve on Git failure")
    original_run_hidden = process_utils.run_hidden
    reject_removal = True

    def refuse_remove(command, *args, **kwargs):
        if reject_removal and "worktree" in command and "remove" in command:
            return SimpleNamespace(returncode=1, stdout="", stderr="injected remove failure")
        return original_run_hidden(command, *args, **kwargs)

    monkeypatch.setattr(process_utils, "run_hidden", refuse_remove)
    try:
        result = remove_git_worktree(repo, wt_path, worktree_id=worktree_id, force=True)

        assert result.get("success") is False
        assert "remove failure" in result.get("error", "")
        assert wt_path.is_dir()
        assert marker.read_text() == "preserve on Git failure"
    finally:
        reject_removal = False
        if wt_path.exists():
            cleanup = remove_git_worktree(repo, wt_path, worktree_id=worktree_id, force=True)
            assert cleanup.get("success") is True


def test_remove_reports_prune_failure_after_git_removal(monkeypatch, tmp_path):
    repo, wt_path, worktree_id = _create_repo_and_worktree(tmp_path)
    events = []
    original_run_hidden = process_utils.run_hidden

    def record_remove(command, *args, **kwargs):
        if "worktree" in command and "remove" in command:
            events.append("remove")
        return original_run_hidden(command, *args, **kwargs)

    def fail_prune(repo_root, expire=None, **_kwargs):
        events.append("prune")
        return {"success": False, "error": "injected prune failure"}

    monkeypatch.setattr(process_utils, "run_hidden", record_remove)
    monkeypatch.setattr(process_utils, "prune_git_worktrees", fail_prune)
    result = remove_git_worktree(repo, wt_path, worktree_id=worktree_id)

    assert events == ["remove", "prune"]
    assert result.get("success") is False
    assert "prune failure" in result.get("error", "")
    assert not wt_path.exists()


def test_task_completion_schedules_then_owner_cleans_clean_worktree(tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    worktree = Path(task.checkpoint.state_data["worktree"]["worktree_path"])

    try:
        completed = tasks.complete(task.task_id, actor="agent-1")

        assert completed.status is TaskStatus.COMPLETED
        assert worktree.is_dir()
        assert completed.checkpoint.state_data["worktree"]["cleanup_scheduled"] is True
        assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
        assert _run_owned_task_cleanup(repo, tasks, completed)["success"] is True
        assert not worktree.exists()
        assert tasks.get(task.task_id).checkpoint.state_data["worktree"]["cleanup_success"] is True
    finally:
        _cleanup_task_worktree(repo, tasks.get(task.task_id))


def test_task_completion_preserves_dirty_worktree_with_pending_cleanup(tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    worktree_record = task.checkpoint.state_data["worktree"]
    worktree = Path(worktree_record["worktree_path"])
    marker = worktree / "untracked.txt"
    marker.write_text("preserve until owner resolves")

    try:
        completed = tasks.complete(task.task_id, actor="agent-1")

        assert completed.status is TaskStatus.COMPLETED
        assert worktree.is_dir()
        assert marker.read_text() == "preserve until owner resolves"
        assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
    finally:
        _cleanup_task_worktree(repo, tasks.get(task.task_id))


def test_owner_cleanup_removes_completed_worktree_merged_into_newer_root_head(tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    worktree = Path(task.checkpoint.state_data["worktree"]["worktree_path"])
    (repo / "root-update.txt").write_text("new root head")
    subprocess.run(["git", "add", "root-update.txt"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "advance root"], cwd=str(repo), check=True, capture_output=True)

    try:
        completed = tasks.complete(task.task_id, actor="agent-1")

        assert completed.status is TaskStatus.COMPLETED
        assert worktree.is_dir()
        assert completed.checkpoint.state_data["worktree"]["cleanup_scheduled"] is True
        assert _run_owned_task_cleanup(repo, tasks, completed)["success"] is True
        assert not worktree.exists()
        assert tasks.get(task.task_id).checkpoint.state_data["worktree"]["cleanup_success"] is True
    finally:
        _cleanup_task_worktree(repo, tasks.get(task.task_id))


def test_task_completion_preserves_unique_commit_worktree_with_pending_cleanup(tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    worktree_record = task.checkpoint.state_data["worktree"]
    worktree = Path(worktree_record["worktree_path"])
    (worktree / "unique.txt").write_text("unique worktree commit")
    subprocess.run(["git", "add", "unique.txt"], cwd=str(worktree), check=True)
    subprocess.run(["git", "commit", "-m", "unique worktree commit"], cwd=str(worktree), check=True, capture_output=True)
    branch_head = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    try:
        completed = tasks.complete(task.task_id, actor="agent-1")

        assert completed.status is TaskStatus.COMPLETED
        assert worktree.is_dir()
        assert subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip() == branch_head
        assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
    finally:
        _cleanup_task_worktree(repo, tasks.get(task.task_id))


def test_completion_rechecks_history_before_remove_and_preserves_racing_commit(monkeypatch, tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    wt = Path(task.checkpoint.state_data["worktree"]["worktree_path"])
    original_run_hidden = process_utils.run_hidden
    injected = False

    def commit_before_ancestry_proof(command, *args, **kwargs):
        nonlocal injected
        if not injected and "merge-base" in command:
            injected = True
            (wt / "racing-commit.txt").write_text("retain unique commit")
            original_run_hidden(["git", "add", "racing-commit.txt"], cwd=str(wt), check=True, timeout=5)
            original_run_hidden(["git", "commit", "-m", "racing unique commit"], cwd=str(wt), check=True, capture_output=True, timeout=5)
        return original_run_hidden(command, *args, **kwargs)

    monkeypatch.setattr(process_utils, "run_hidden", commit_before_ancestry_proof)
    try:
        completed = tasks.complete(task.task_id, actor="agent-1")

        assert completed.status is TaskStatus.COMPLETED
        assert injected is False
        assert completed.checkpoint.state_data["worktree"]["cleanup_scheduled"] is True
        cleanup = _run_owned_task_cleanup(repo, tasks, completed)
        assert cleanup["success"] is False
        assert injected
        assert wt.is_dir()
        assert (wt / "racing-commit.txt").read_text() == "retain unique commit"
        assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
        assert original_run_hidden(
            ["git", "-C", str(repo), "branch", "--list", task.checkpoint.state_data["worktree"]["branch"]],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
    finally:
        monkeypatch.setattr(process_utils, "run_hidden", original_run_hidden)
        _cleanup_task_worktree(repo, tasks.get(task.task_id))


def test_idle_sweep_removes_only_expired_terminal_dead_owner_checkout(monkeypatch, tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    task = tasks.fail(task.task_id, actor="agent-1")
    wt = dict(task.checkpoint.state_data["worktree"])
    wt["created_at"] -= 7200
    wt["expires_at"] -= 7200
    state_data = {**task.checkpoint.state_data, "worktree": wt}
    from local_ai_hub.agent_tasks import TaskCheckpoint
    checkpoint = TaskCheckpoint(
        phase=task.checkpoint.phase, next_action=task.checkpoint.next_action,
        affected_paths=task.checkpoint.affected_paths, evidence_ids=task.checkpoint.evidence_ids,
        blockers=task.checkpoint.blockers, state_data=state_data,
    )
    task = tasks.checkpoint(task.task_id, checkpoint, actor="agent-1")
    marker = process_utils._worktree_ownership_path(Path(wt["worktree_path"]))
    metadata = process_utils.get_git_worktree_ownership(repo, wt["worktree_path"])
    metadata.update(created_at=wt["created_at"], expires_at=wt["expires_at"])
    marker.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(process_utils, "process_owner_state", lambda *_args: "stale")

    result = tasks.cleanup_idle_worktrees()

    assert result["scanned"] == 1, result
    assert result["cleaned"] == 1, result
    assert not Path(wt["worktree_path"]).exists()
    assert tasks.get(task.task_id).checkpoint.state_data["worktree"]["cleanup_success"] is True


@pytest.mark.parametrize("creator_state", ["owned", "unknown"])
def test_idle_sweep_preserves_live_or_unknown_creator(monkeypatch, tmp_path, creator_state):
    repo, tasks, task = _create_owned_task(tmp_path)
    task = tasks.fail(task.task_id, actor="agent-1")
    wt = dict(task.checkpoint.state_data["worktree"])
    wt["created_at"] -= 7200
    wt["expires_at"] -= 7200
    state_data = {**task.checkpoint.state_data, "worktree": wt}
    from local_ai_hub.agent_tasks import TaskCheckpoint
    cp = TaskCheckpoint(task.checkpoint.phase, task.checkpoint.next_action,
                        task.checkpoint.affected_paths, task.checkpoint.evidence_ids,
                        task.checkpoint.blockers, state_data)
    task = tasks.checkpoint(task.task_id, cp, actor="agent-1")
    marker = process_utils._worktree_ownership_path(Path(wt["worktree_path"]))
    metadata = process_utils.get_git_worktree_ownership(repo, wt["worktree_path"])
    metadata.update(created_at=wt["created_at"], expires_at=wt["expires_at"])
    marker.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(process_utils, "process_owner_state", lambda *_args: creator_state)

    result = tasks.cleanup_idle_worktrees()

    assert result["cleaned"] == 0
    assert Path(wt["worktree_path"]).is_dir()
    assert tasks.get(task.task_id).status is TaskStatus.FAILED


def test_idle_sweep_retries_pending_after_owner_resolves_dirty_checkout(monkeypatch, tmp_path):
    repo, tasks, task = _create_owned_task(tmp_path)
    wt = Path(task.checkpoint.state_data["worktree"]["worktree_path"])
    marker_file = wt / "later-clean.txt"
    marker_file.write_text("owner work in progress")
    completed = tasks.complete(task.task_id, actor="agent-1")
    assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
    receipts_before = dict(completed.verification_receipts)
    preserved_state = {key: value for key, value in completed.checkpoint.state_data.items() if key != "worktree"}
    marker_file.unlink()
    record = dict(completed.checkpoint.state_data["worktree"])
    record["created_at"] -= 7200
    record["expires_at"] -= 7200
    from local_ai_hub.agent_tasks import TaskCheckpoint
    cp = TaskCheckpoint(
        phase=completed.checkpoint.phase, next_action=completed.checkpoint.next_action,
        affected_paths=completed.checkpoint.affected_paths, evidence_ids=completed.checkpoint.evidence_ids,
        blockers=completed.checkpoint.blockers,
        state_data={**completed.checkpoint.state_data, "worktree": record},
    )
    tasks.checkpoint(task.task_id, cp, actor="agent-1")
    marker = process_utils._worktree_ownership_path(wt)
    metadata = process_utils.get_git_worktree_ownership(repo, wt)
    metadata.update(created_at=record["created_at"], expires_at=record["expires_at"])
    marker.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(process_utils, "process_owner_state", lambda *_args: "stale")

    result = tasks.cleanup_idle_worktrees()
    retried = tasks.get(task.task_id)

    assert result["cleaned"] == 1
    assert not wt.exists()
    assert retried.status is TaskStatus.COMPLETED
    assert retried.verification_receipts == receipts_before
    assert {key: value for key, value in retried.checkpoint.state_data.items() if key != "worktree"} == preserved_state


def test_idle_sweep_does_not_start_cleanup_after_shared_budget_expires(monkeypatch, tmp_path):
    import local_ai_hub.agent_tasks as agent_tasks_module
    import local_ai_hub.worktrees as worktrees_module

    repo, tasks, task = _create_owned_task(tmp_path)
    task = tasks.fail(task.task_id, actor="agent-1")
    wt = dict(task.checkpoint.state_data["worktree"])
    wt["created_at"] -= 7200
    wt["expires_at"] -= 7200
    from local_ai_hub.agent_tasks import TaskCheckpoint
    cp = TaskCheckpoint(
        phase=task.checkpoint.phase, next_action=task.checkpoint.next_action,
        affected_paths=task.checkpoint.affected_paths, evidence_ids=task.checkpoint.evidence_ids,
        blockers=task.checkpoint.blockers, state_data={**task.checkpoint.state_data, "worktree": wt},
    )
    tasks.checkpoint(task.task_id, cp, actor="agent-1")
    marker = process_utils._worktree_ownership_path(Path(wt["worktree_path"]))
    metadata = process_utils.get_git_worktree_ownership(repo, wt["worktree_path"])
    metadata.update(created_at=wt["created_at"], expires_at=wt["expires_at"])
    marker.write_text(json.dumps(metadata), encoding="utf-8")

    clock = [100.0]
    fake_time = SimpleNamespace(monotonic=lambda: clock[0], time=time.time)
    monkeypatch.setattr(agent_tasks_module, "time", fake_time)
    monkeypatch.setattr(process_utils, "process_owner_state", lambda *_args: "stale")
    def exhaust_budget(*_args, **_kwargs):
        clock[0] = 108.0
        return True, ""
    monkeypatch.setattr(worktrees_module, "worktree_is_clean_ancestor", exhaust_budget)
    cleanup_calls = []
    monkeypatch.setattr(tasks, "cleanup_worktree", lambda *_args, **_kwargs: cleanup_calls.append("called") or {"success": True})

    result = tasks.cleanup_idle_worktrees(deadline_seconds=8.0)

    assert result["cleaned"] == 0
    assert cleanup_calls == []
    assert tasks.get(task.task_id).status is TaskStatus.FAILED


def test_removal_and_prune_share_one_fake_clock_deadline(monkeypatch, tmp_path):
    repo, worktree, worktree_id = _create_repo_and_worktree(tmp_path)
    metadata = process_utils.get_git_worktree_ownership(repo, worktree)
    base_commit = metadata["base_commit"]
    clock = [0.0]
    deadline = 8.0
    original_run_hidden = process_utils.run_hidden
    original_popen = process_utils.popen_managed
    children = []
    started_at = []
    commands_started = []
    fake_clock = SimpleNamespace(monotonic=lambda: clock[0])

    def tracked_popen(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    def advancing_runner(command, *args, **kwargs):
        started_at.append(clock[0])
        commands_started.append(tuple(command))
        # The simulated worktree deadline must not replace the real clock used
        # by subprocess polling and cleanup inside run_hidden.
        monkeypatch.setattr(process_utils, "time", time)
        try:
            result = original_run_hidden(command, *args, **kwargs)
        finally:
            monkeypatch.setattr(process_utils, "time", fake_clock)
        clock[0] += 3.0
        return result

    monkeypatch.setattr(process_utils, "time", fake_clock)
    monkeypatch.setattr(process_utils, "run_hidden", advancing_runner)
    monkeypatch.setattr(process_utils, "popen_managed", tracked_popen)
    try:
        result = remove_git_worktree(
            repo, worktree, worktree_id=worktree_id, required_base_commit=base_commit,
            timeout_seconds=8.0, deadline_monotonic=deadline,
        )

        assert all(start < deadline for start in started_at)
        assert not any("remove" in command and "worktree" in command for command in commands_started)
        assert not any("prune" in command for command in commands_started)
        assert result["success"] is False
        assert worktree.is_dir()
        assert children and all(child.poll() is not None for child in children)
    finally:
        monkeypatch.setattr(process_utils, "run_hidden", original_run_hidden)
        monkeypatch.setattr(process_utils, "time", time)
        if worktree.exists():
            remove_git_worktree(repo, worktree, worktree_id=worktree_id, force=True)


def test_watchdog_runs_idle_worktree_sweep_only_when_scheduler_idle_and_active_mode(monkeypatch, tmp_path):
    class OneIteration:
        def __init__(self):
            self.wait_calls = 0

        def wait(self, _interval):
            self.wait_calls += 1
            return self.wait_calls > 1

    from local_ai_hub import operational_mode
    for scheduler_state, mode, degraded, expected in (
        ({"queued": 0, "inflight": 0}, "active", False, 1),
        ({"queued": 1, "inflight": 0}, "active", False, 0),
        ({"queued": 0, "inflight": 1}, "active", False, 0),
        ({"queued": 0, "inflight": 0}, "gaming", False, 0),
        ({"queued": 0, "inflight": 0}, "maintenance", False, 0),
        ({"queued": 0, "inflight": 0}, "active", True, 0),
    ):
        monkeypatch.setattr(
            operational_mode, "load_operational_mode",
            lambda _state_dir, selected=mode, is_degraded=degraded: SimpleNamespace(mode=selected, degraded=is_degraded),
        )
        calls = []
        tasks = SimpleNamespace(
            reap_expired_heartbeats=lambda: None,
            cleanup_idle_worktrees=lambda: calls.append("cleanup"),
        )
        app = LocalAIApp.__new__(LocalAIApp)
        app.config = {
            "resilience": {"watchdog_interval_seconds": 1, "maintenance_interval_seconds": 60},
            "observability": {"snapshot_interval_seconds": 60},
            "server": {"state_dir": str(tmp_path)},
        }
        app._shutdown = OneIteration()
        app.recovery = SimpleNamespace(mark_abandoned=lambda: None)
        app.async_jobs = SimpleNamespace(tick=lambda: None)
        app.debug_traces = SimpleNamespace(cleanup=lambda: None)
        app.scheduler = SimpleNamespace(
            ensure_dispatcher=lambda: None,
            status=lambda: dict(scheduler_state, stats={}),
        )
        app.preprocessor = SimpleNamespace(ensure_running=lambda: None, stats=lambda: {})
        app.agent_state = SimpleNamespace(
            enabled=True,
            tasks=tasks,
            cleanup=lambda **_kwargs: None,
            memory=SimpleNamespace(reap_expired=lambda: None),
        )
        app.runtime = SimpleNamespace(is_online=lambda: True)
        app.logger = SimpleNamespace(debug=lambda *_args: None, warning=lambda *_args: None)
        app.telemetry = SimpleNamespace(record_snapshot=lambda *_args: None, record_error=lambda *_args: None)
        app.services = SimpleNamespace(fallback_count=0)

        app._watchdog_loop()

        assert len(calls) == expected
