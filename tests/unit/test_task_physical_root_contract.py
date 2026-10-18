from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import process_utils
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    GoalContract,
    TaskStore,
    TaskWorktreeError,
    _task_scope_root,
)


def _task_store(tmp_path: Path) -> TaskStore:
    return TaskStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))


def test_active_task_preserves_filesystem_case_boundaries(tmp_path):
    store = _task_store(tmp_path)
    upper = tmp_path / "Project"
    lower = tmp_path / "project"
    upper.mkdir()
    store.create(
        GoalContract(goal="upper project", acceptance_criteria=()),
        ScopeContext(repository_id="shared-coordination", task_id="upper-task"),
        task_id="upper-task", repo_root=str(upper),
    )
    try:
        lower.mkdir()
    except FileExistsError:
        assert store.get_active_task(str(lower)).task_id == "upper-task"
    else:
        store.create(
            GoalContract(goal="lower project", acceptance_criteria=()),
            ScopeContext(repository_id="shared-coordination", task_id="lower-task"),
            task_id="lower-task", repo_root=str(lower),
        )
        assert store.get_active_task(str(upper)).task_id == "upper-task"
        assert store.get_active_task(str(lower)).task_id == "lower-task"


def test_auto_worktree_requires_explicit_physical_root_before_prepare(tmp_path, monkeypatch):
    store = _task_store(tmp_path)
    prepare_calls = []
    monkeypatch.setattr(
        process_utils,
        "prepare_git_worktree",
        lambda *args, **kwargs: prepare_calls.append((args, kwargs)),
    )

    with pytest.raises(TaskWorktreeError) as raised:
        store.create(
            GoalContract(goal="Worktree root contract", acceptance_criteria=("worktree",)),
            ScopeContext(repository_id=str(tmp_path)),
            task_id="task-needs-explicit-root",
            auto_worktree=True,
        )

    assert raised.value.mutation_applied is False
    assert raised.value.operation_not_started is True
    assert raised.value.outcome_unknown is False
    assert prepare_calls == []
    assert store.get("task-needs-explicit-root") is None


def test_logical_repository_id_does_not_replace_task_physical_root(tmp_path):
    store = _task_store(tmp_path)
    physical_root = tmp_path / "checked-out-project"
    physical_root.mkdir()
    logical_repository_id = "coordination:project-4821"

    task = store.create(
        GoalContract(goal="Separate identities", acceptance_criteria=("root-bound",)),
        ScopeContext(repository_id=logical_repository_id, task_id="task-separated-root"),
        task_id="task-separated-root",
        repo_root=str(physical_root),
    )

    assert task.context.repository_id == logical_repository_id
    assert _task_scope_root(task) == str(physical_root.resolve())
    assert _task_scope_root(task) != task.context.repository_id


def test_path_looking_context_id_does_not_reconstruct_missing_memory_root(tmp_path):
    store = _task_store(tmp_path)
    path_looking_id = str((tmp_path / "looks-like-a-repository").resolve())
    request_seen = []

    class _Compiler:
        def compile(self, request):
            request_seen.append(request)
            return SimpleNamespace(elements=(), warnings=())

    class _MemoryStore:
        def diagnostic_summary(self, **_kwargs):
            return {}

        def find(self, **_kwargs):
            return []

    store.memory_context_compiler = _Compiler()
    store.memory_store = _MemoryStore()
    snapshot = store._collect_task_memory_context(
        "task-no-physical-root",
        GoalContract(goal="Do not infer root", acceptance_criteria=("rootless",)),
        ScopeContext(repository_id=path_looking_id, task_id="task-no-physical-root"),
        root_override="",
        deadline=time.monotonic() + 5,
        cancelled=threading.Event(),
    )

    assert len(request_seen) == 1
    assert request_seen[0].root == ""
    assert request_seen[0].coordination_id == ""
    assert request_seen[0].repository_id == path_looking_id
    assert snapshot is None
