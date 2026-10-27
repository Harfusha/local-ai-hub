from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub import trace_context
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStatus
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint
from local_ai_hub.app import LocalAIApp
from local_ai_hub.verification_rules import complete_task_with_project_rules
from task_memory_support import repository_memory_id


def test_project_completion_rejects_skipped_memory_without_not_used_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q"\nrequired_commands = "python -m pyflakes review"\n'
        '[verification_rules]\nrequired_commands = ["test"]\n',
        encoding="utf-8",
    )
    (project_root / "test_project.py").write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    (project_root / "review").mkdir()
    (project_root / "review" / "reviewed.py").write_text("value = 1\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    repository_id = repository_memory_id(project_root, app.agent_state)
    app.agent_memory.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=repository_id,
            key="stale-project-memory",
            value="stale evidence",
            status=MemoryStatus.STALE,
            provenance={"root": str(project_root), "repository_id": repository_id},
        )
    )
    task_id = "project-completion-skipped-memory"
    token = trace_context.set_context(agent="trace-agent", request_id="trace-request")
    try:
        app.agent_tasks.create(
            GoalContract(
                goal="complete with configured receipts",
                acceptance_criteria=("required_commands",),
            ),
            ScopeContext(task_id=task_id, repository_id=str(project_root)),
            task_id=task_id,
            actor="agent",
            repo_root=str(project_root),
        )
    finally:
        trace_context.reset_context(token)
    task = app.agent_tasks.get(task_id)
    assert task is not None
    assert any(
        warning["code"] == "memory_stale_skipped"
        for warning in task.checkpoint.state_data["memory_context"]["warnings"]
    )
    checkpoint = TaskCheckpoint(
        phase="work",
        state_data={"memory_audit": {"used_ids": []}},
    )
    before_checkpoint = app.agent_tasks.get(task_id)
    before_checkpoint_events = app.agent_state.events(f"task:{task_id}")
    with pytest.raises(CompletionGateError, match="not_used_reason"):
        app.agent_tasks.checkpoint(task_id, checkpoint, actor="agent")
    assert app.agent_tasks.get(task_id) == before_checkpoint
    assert app.agent_state.events(f"task:{task_id}") == before_checkpoint_events
    # Completion must still reject a legacy invalid audit already in storage.
    with monkeypatch.context() as legacy_fixture:
        legacy_fixture.setattr(app.agent_tasks, "_validate_memory_audit", lambda _task: None)
        app.agent_tasks.checkpoint(task_id, checkpoint, actor="agent")
    receipts = []
    for criterion in ("required_commands", "test"):
        result = app.commands.run_project_command(
            criterion, str(project_root), task_id=task_id, criterion=criterion,
            timeout=60, force=True,
        )
        assert result.get("success") is True, result
        receipt = result.get("verification_receipt")
        assert isinstance(receipt, dict), result
        receipts.append(receipt)
    repository_revision = receipts[0]["repository_revision"]
    assert receipts[1]["repository_revision"] == repository_revision

    with pytest.raises(CompletionGateError, match="not_used_reason"):
        complete_task_with_project_rules(
            app.agent_tasks,
            app.agent_verification,
            task_id,
            root=project_root,
            state_dir=state_dir,
            current_revision=repository_revision,
            actor="agent",
        )

    stored = app.agent_tasks.get(task_id)
    assert stored is not None
    assert stored.status.value != "completed"
