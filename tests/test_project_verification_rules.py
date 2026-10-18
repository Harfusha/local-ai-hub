from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any
import urllib.request

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint, TaskStore
from local_ai_hub.agent_verification import (
    CompletionResult,
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.project_config import CommandDefinition, ProjectSettings
from local_ai_hub.project_config import resolve_project_context
from local_ai_hub.verification_rules import evaluate_project_completion, project_command_environment_sha256


class _T09CompletionStore:
    """T09 completion API stand-in around the current persisted receipt store."""

    def __init__(self, task_store: TaskStore, persisted_store: VerificationStore):
        self.task_store = task_store
        self.persisted_store = persisted_store
        self.arguments: dict[str, Any] = {}
        self.completion_calls = 0

    def completion(
        self,
        task_id: str,
        now: float | None = None,
        *,
        current_revision: str = "",
        current_mutation_generation: int | None = None,
        verification_rules=None,
        configured_criteria=None,
        configured_commands=None,
        project_config_digest="",
        configured_environment_sha256=None,
        project_root="",
    ) -> CompletionResult:
        self.completion_calls += 1
        task = self.task_store.get(task_id)
        assert task is not None
        persisted = self.persisted_store.completion(
            task_id, now=now, current_revision=current_revision
        )
        self.arguments = {
            "task_id": task_id,
            "required_criteria": task.contract.acceptance_criteria,
            "owner": task.owner,
            "repository_revision": current_revision,
            "mutation_generation": current_mutation_generation,
            "mapped_receipt_ids": dict(task.verification_receipts),
            "receipts": persisted.receipts,
            "verification_rules": verification_rules,
            "configured_criteria": configured_criteria,
            "configured_commands": configured_commands,
            "project_config_digest": project_config_digest,
            "configured_environment_sha256": configured_environment_sha256,
            "project_root": project_root,
        }
        return CompletionResult(
            task_id=task_id,
            complete=False,
            satisfied_criteria=(),
            unsatisfied_criteria=("acceptance",),
            stale_criteria=(),
            receipts=persisted.receipts,
        )


def test_project_completion_forwards_config_and_task_generation_to_t09_store(
    tmp_path: Path,
) -> None:
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    task_store = TaskStore(state_store)
    persisted_store = VerificationStore(state_store, task_store=task_store)
    task = task_store.create(
        GoalContract(goal="project task", acceptance_criteria=("acceptance",)),
        ScopeContext(task_id="task-21"),
        task_id="task-21",
        actor="owner-21",
    )
    task_store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"mutation_generation": 7}),
        actor="owner-21",
    )
    receipt = persisted_store.record(
        VerificationReceipt.create(
            task_id=task.task_id,
            criterion="acceptance",
            evidence_id="evidence-21",
            repository_revision="revision-21",
        )
    )
    task_store.add_verification_receipt(
        task.task_id, "acceptance", receipt.receipt_id
    )
    completion_store = _T09CompletionStore(task_store, persisted_store)
    settings = ProjectSettings(
        commands={"check": CommandDefinition(("pytest",))},
        verification_rules={"acceptance": ("check",)},
    )

    result = evaluate_project_completion(
        completion_store,
        settings,
        task_id=task.task_id,
        repository_revision="revision-21",
    )

    assert result.task_id == "task-21"
    assert completion_store.arguments == {
        "task_id": "task-21",
        "required_criteria": ("acceptance",),
        "owner": "owner-21",
        "repository_revision": "revision-21",
        "mutation_generation": 7,
        "mapped_receipt_ids": {"acceptance": receipt.receipt_id},
        "receipts": result.receipts,
        "verification_rules": {"acceptance": ("check",)},
        "configured_criteria": ("check",),
        "configured_commands": settings.commands,
        "project_config_digest": "",
        "configured_environment_sha256": None,
        "project_root": "",
    }
    assert result.receipts[0].receipt_id == receipt.receipt_id
    assert result.receipts[0].repository_revision == "revision-21"


@pytest.mark.parametrize("generation", [True, -1, "7", None])
def test_project_completion_rejects_invalid_mutation_generation_before_t09_call(
    tmp_path: Path, generation: Any
) -> None:
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    task_store = TaskStore(state_store)
    persisted_store = VerificationStore(state_store, task_store=task_store)
    task = task_store.create(
        GoalContract(goal="project task", acceptance_criteria=("acceptance",)),
        ScopeContext(task_id="task-21"),
        task_id="task-21",
        actor="owner-21",
    )
    task_store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"mutation_generation": generation}),
        actor="owner-21",
    )
    completion_store = _T09CompletionStore(task_store, persisted_store)

    with pytest.raises(ValueError, match="mutation_generation is invalid"):
        evaluate_project_completion(
            completion_store,
            ProjectSettings(),
            task_id=task.task_id,
            repository_revision="revision-21",
        )

    assert completion_store.completion_calls == 0


def test_http_task_completion_uses_persisted_project_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        "\n[agent_state]\nenabled = true\n"
        '[security]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    task_id = "task-http-completion"
    test_dir = project_root / "tests"
    test_dir.mkdir()
    (test_dir / "test_project_rules.py").write_text(
        "def test_project_rule():\n    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    app.agent_tasks.create(
        GoalContract(
            goal="verify configured project rules",
            acceptance_criteria=("required_commands",),
        ),
        ScopeContext(task_id=task_id, repository_id=str(project_root), session_id="agent"),
        task_id=task_id,
        actor="agent",
        repo_root=str(project_root),
    )
    command_result = app.commands.run_project_command(
        "test",
        str(project_root),

        task_id=task_id,
        criterion="test",
        timeout=60,
        force=True,
    )
    assert command_result.get("success") is True, command_result
    command_receipt = command_result.get("verification_receipt")
    assert isinstance(command_receipt, dict)
    repository_revision = str(command_receipt.get("repository_revision") or "")
    assert repository_revision
    source_evidence = app.artifacts.put_json(
        {
            "kind": "work_source_review",
            "passed": True,
            "task_id": task_id,
            "owner": "agent",
            "repository_revision": repository_revision,
            "mutation_generation": 0,
            "criteria": ["required_commands"],
        },
        kind="source_review",
    )
    app.agent_verification.record(
        VerificationReceipt.create(
            task_id,
            "required_commands",
            evidence_id=source_evidence,
            owner="agent",
            repository_revision=repository_revision,
        )
    )
    task = app.agent_tasks.get(task_id)
    assert task is not None
    state_data = dict(task.checkpoint.state_data)
    state_data["repository_revision"] = repository_revision
    app.agent_tasks.checkpoint(
        task_id,
        TaskCheckpoint(phase=task.checkpoint.phase, state_data=state_data),
        actor="agent",
        idempotency_key="http-test-revision",
    )
    project = resolve_project_context(project_root, state_dir)
    preflight = evaluate_project_completion(
        app.agent_verification,
        project.settings,
        task_id=task_id,
        repository_revision=repository_revision,
        project_config_digest=project.config_digest,
        configured_environment_sha256={
            name: project_command_environment_sha256(project.settings, name)
            for name in project.settings.commands
        },
        project_root=project_root,
    )
    assert preflight.complete, (preflight.unsatisfied_criteria, preflight.stale_criteria)
    monkeypatch.setattr(
        http_server,
        "_completion_revision_or_stop",
        lambda *_args: (repository_revision, None),
    )
    old_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/tasks",
            data=json.dumps(
                {
                    "action": "complete",
                    "task_id": task_id,
                    "root": str(project_root),
                    "reason": "verified",
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Agent": "agent",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            pytest.fail(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = old_app

    assert payload["success"] is True
    assert payload["task"]["status"] == "completed"
    stored = app.agent_tasks.get(task_id)
    assert stored is not None
    assert stored.checkpoint.state_data["repo_root"] == str(project_root.resolve())
    assert stored.checkpoint.state_data["repository_revision"] == repository_revision
    result = app.agent_verification.completion(
        task_id, current_revision=repository_revision, current_mutation_generation=0
    )
    assert result.complete is True
    assert {receipt.evidence_id for receipt in result.receipts} == {
        source_evidence,
        command_receipt["evidence_id"],
    }
