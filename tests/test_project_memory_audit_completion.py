from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub import trace_context
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStatus
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint
from local_ai_hub.agent_verification import VerificationReceipt
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
        '[commands]\ntest = "python -m pytest -q"\n'
        '[verification_rules]\nrequired_commands = ["test"]\n',
        encoding="utf-8",
    )
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
    source_evidence = app.artifacts.put_json(
        {
            "kind": "work_source_review",
            "passed": True,
            "task_id": task_id,
            "owner": "agent",
            "repository_revision": "rev-memory",
            "mutation_generation": 0,
            "criteria": ["required_commands"],
        },
        kind="source_review",
    )
    command_evidence = app.artifacts.put_json(
        {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": task_id,
            "owner": "agent",
            "repository_revision": "rev-memory",
            "mutation_generation": 0,
            "criterion": "test",
            "command_id": "cmd-memory",
            "exit_code": 0,
            "result": {"success": True, "exit_code": 0},
        },
        kind="command_verification",
    )
    app.agent_verification.record(
        VerificationReceipt.create(
            task_id,
            "required_commands",
            evidence_id=source_evidence,
            owner="agent",
            repository_revision="rev-memory",
        )
    )
    app.agent_verification.record(
        VerificationReceipt.create(
            task_id,
            "test",
            evidence_id=command_evidence,
            command_id="cmd-memory",
            owner="agent",
            repository_revision="rev-memory",
        )
    )

    with pytest.raises(CompletionGateError, match="not_used_reason"):
        complete_task_with_project_rules(
            app.agent_tasks,
            app.agent_verification,
            task_id,
            root=project_root,
            state_dir=state_dir,
            current_revision="rev-memory",
            actor="agent",
        )

    stored = app.agent_tasks.get(task_id)
    assert stored is not None
    assert stored.status.value != "completed"
