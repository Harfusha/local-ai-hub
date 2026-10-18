from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskStore
from local_ai_hub.agent_verification import CompletionResult, VerificationReceipt, VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub import http_server
from local_ai_hub import mcp_server
from local_ai_hub.project_config import resolve_project_context
from local_ai_hub.verification_rules import (
    complete_task_with_project_rules,
    evaluate_project_completion,
    project_command_environment_sha256,
)


class _VerificationStore:
    def __init__(self, result: CompletionResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def completion(self, task_id: str, **kwargs: object) -> CompletionResult:
        self.calls.append({"task_id": task_id, **kwargs})
        return self.result


class _TaskStore:
    preflight_completion_response_budget = TaskStore.preflight_completion_response_budget

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.task: object | None = None

    def get(self, _task_id: str) -> object | None:
        return self.task

    def complete(self, task_id: str, **kwargs: object) -> str:
        self.calls.append((task_id, kwargs))
        return "completed"


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        '[commands]\ncheck = "python -m pytest -q"\n'
        '[verification_rules]\nrequired_commands = ["check"]\n',
        encoding="utf-8",
    )
    return root, tmp_path / "state"


def _bind_execution_record(
    verification: VerificationStore, receipt, proof: dict, root: Path,
) -> None:
    canonical_root = str(root.resolve())
    record = {
        "schema": "command_execution_record.v2",
        "command_id": receipt.command_id,
        "task_id": receipt.task_id,
        "owner": receipt.owner,
        "criterion": receipt.criterion,
        "evidence_id": receipt.evidence_id,
        "receipt_sha256": hashlib.sha256(
            json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "command_sha256": proof["command_sha256"],
        "evidence_type": receipt.evidence_type,
        "repository_root": canonical_root,
        "repository_root_sha256": hashlib.sha256(canonical_root.encode("utf-8")).hexdigest(),
        "repository_revision": receipt.repository_revision,
        "mutation_generation": receipt.mutation_generation,
        "configured_command_sha256": proof.get("configured_command_sha256", ""),
        "caller_arguments_sha256": proof.get("caller_arguments_sha256", ""),
        "exit_code": 0,
        "cached": False,
        "created_at_unix": 0,
        **{
            key: proof.get(key, "")
            for key in (
                "project_alias", "project_config_digest", "project_environment_sha256",
                "project_execution_binding_sha256",
            )
        },
    }
    record["record_sha256"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    verification.set_command_execution_record_lookup(
        lambda command_id, **kwargs: record
        if command_id == receipt.command_id
        and kwargs.get("task_id") == receipt.task_id
        and kwargs.get("repository_root") == canonical_root
        else None
    )


def test_evaluate_project_completion_passes_rules_and_configured_commands(tmp_path: Path) -> None:
    root, state_dir = _project(tmp_path)
    coordination_id = resolve_project_context(root, state_dir).coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    result = CompletionResult("task-1", False, (), ("criterion",), (), ())
    verification = _VerificationStore(result)
    task = SimpleNamespace(
        task_id="task-1",
        owner="owner-1",
        context=SimpleNamespace(repository_id=coordination_id),
        checkpoint=SimpleNamespace(state_data={"mutation_generation": 0}),
    )
    verification.task_store = SimpleNamespace(get=lambda task_id: task if task_id == task.task_id else None)

    actual = evaluate_project_completion(
        verification,
        "task-1",
        root=root,
        state_dir=state_dir,
        current_revision="rev-1",
        now=123.0,
    )

    assert actual is result
    assert len(verification.calls) == 1
    call = verification.calls[0]
    assert call["task_id"] == "task-1"
    assert call["now"] == 123.0
    assert call["current_revision"] == "rev-1"
    assert call["current_mutation_generation"] == 0
    assert call["verification_rules"] == {"required_commands": ("check",)}
    assert call["configured_criteria"] == ("check",)
    assert call["configured_commands"]
    assert call["project_config_digest"]
    assert call["project_root"] == root.resolve()


def test_completion_handler_does_not_mutate_task_when_receipts_fail(tmp_path: Path) -> None:
    root, state_dir = _project(tmp_path)
    coordination_id = resolve_project_context(root, state_dir).coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    result = CompletionResult("task-1", False, (), ("required_commands",), (), ())
    task_store = _TaskStore()
    task_store.task = SimpleNamespace(
        task_id="task-1",
        owner="owner-1",
        context=SimpleNamespace(repository_id=coordination_id),
        checkpoint=SimpleNamespace(state_data={"mutation_generation": 0}),
    )
    verification = _VerificationStore(result)
    verification.task_store = task_store

    with pytest.raises(CompletionGateError, match="required_commands"):
        complete_task_with_project_rules(
            task_store,
            verification,
            "task-1",
            root=root,
            state_dir=state_dir,
            current_revision="rev-1",
        )

    assert task_store.calls == []
    assert len(verification.calls) == 1


def test_http_task_completion_uses_project_verification_rules(monkeypatch, tmp_path: Path) -> None:
    root, state_dir = _project(tmp_path)
    state_dir.mkdir()
    coordination_id = resolve_project_context(root, state_dir).coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    receipt = VerificationReceipt.create(
        "task-1",
        "check",
        evidence_id="evidence-check",
        command_id="cmd-check",
        owner="agent",
        repository_revision="rev-1",
        mutation_generation=0,
        evidence_type="test",
    )
    result = CompletionResult("task-1", True, ("check",), (), (), (receipt,))

    class Verification:
        state_store = SimpleNamespace(db_path=state_dir / "agent_state.sqlite")
        calls: list[dict[str, object]] = []
        task_store = None

        def completion(self, task_id: str, **kwargs: object) -> CompletionResult:
            self.calls.append({"task_id": task_id, **kwargs})
            return result

    class Tasks:
        state_store = SimpleNamespace(enabled=True)

        def get(self, _task_id: str) -> object:
            return SimpleNamespace(
                task_id="task-1",
                owner="agent",
                context=SimpleNamespace(repository_id=coordination_id, session_id="default"),
                checkpoint=SimpleNamespace(state_data={
                    "repo_root": str(root.resolve()),
                    "repository_revision": "rev-1",
                    "mutation_generation": 0,
                }),
                contract=SimpleNamespace(acceptance_criteria=("check",)),
            )

        def complete(self, task_id: str, **kwargs: object) -> object:
            return SimpleNamespace(to_dict=lambda: {"task_id": task_id, **kwargs})

    class Recovery:
        def lookup(self, *_args: object) -> None:
            return None

        def begin(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            return {"claimed": True}

    verification = Verification()
    app_tasks = Tasks()
    verification.task_store = app_tasks
    app = SimpleNamespace(
        config={},
        debug_traces=None,
        recovery=Recovery(),
        agent_tasks=app_tasks,
        agent_verification=verification,
        repo_state=SimpleNamespace(
            fingerprint=lambda *_args, **_kwargs: {
                "success": True,
                "fingerprint": "rev-1",
                "stale": False,
                "degraded": False,
            }
        ),
        repo_tools=None,
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "action": "complete",
        "task_id": "task-1",
        "root": str(root),
        "reason": "done",
    }
    handler._validate_payload = lambda _path, _payload: None
    handler._agent = lambda: "agent"
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", app)

    handler.do_POST()

    assert responses[0][0] == 200
    assert verification.calls[0]["current_revision"] == "rev-1"
    assert verification.calls[0]["verification_rules"] == {"required_commands": ("check",)}
    assert verification.calls[0]["configured_criteria"] == ("check",)


@pytest.mark.parametrize("session_id", ["session-a", "session-b"])
def test_mcp_task_completion_enforces_project_verification_rules(
    monkeypatch, tmp_path: Path, session_id: str,
) -> None:
    root, state_dir = _project(tmp_path)
    (root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q"\n'
        '[verification_rules]\nrequired_commands = ["test"]\n',
        encoding="utf-8",
    )
    state_dir.mkdir()
    coordination_id = resolve_project_context(root, state_dir).coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    state_store = AgentStateStore(state_dir / "agent_state.sqlite")
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verification_store = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )
    task_store.create(
        GoalContract(goal="verify configured rule", acceptance_criteria=("required_commands",)),
        ScopeContext(task_id="task-mcp", repository_id=coordination_id, session_id=session_id),
        task_id="task-mcp",
        repo_root=str(root),
    )

    class Recovery:
        def lookup(self, *_args: object) -> None:
            return None

        def begin(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            return {"claimed": True}

    app = SimpleNamespace(
        config={},
        debug_traces=None,
        recovery=Recovery(),
        agent_tasks=task_store,
        agent_verification=verification_store,
        repo_state=SimpleNamespace(
            fingerprint=lambda *_args, **_kwargs: {
                "success": True,
                "fingerprint": "rev-mcp",
                "stale": False,
                "degraded": False,
            }
        ),
        repo_tools=None,
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    responses = []

    class Client:
        def coord(self, *, action: str, **kwargs: object) -> dict[str, object]:
            assert action == "task_complete"
            payload = {"action": "complete", **kwargs}
            handler = http_server.Handler.__new__(http_server.Handler)
            handler.path = "/api/agent-state/tasks"
            handler.headers = {"Content-Type": "application/json"}
            handler._begin_trace = lambda _path: None
            handler._require_authorized = lambda: True
            handler._read_json = lambda: payload
            handler._validate_payload = lambda _path, _payload: None
            handler._agent = lambda: "agent"
            handler._send = lambda status, data: responses.append((status, data))
            handler.do_POST()
            return responses.pop()[1]

    monkeypatch.setattr(mcp_server, "CLIENT", Client())

    blocked = mcp_server.local_ai_coord(
        action="task_complete", task_id="task-mcp", root=str(root), reason="done"
    )
    assert blocked["success"] is False
    assert "required_commands" in blocked["error"]
    assert task_store.get("task-mcp").status.value == "planned"

    source_evidence = artifact_store.put_json(
        {
            "kind": "work_source_review",
            "passed": True,
            "task_id": "task-mcp",
            "owner": "agent",
            "repository_revision": "rev-mcp",
            "mutation_generation": 0,
            "criteria": ["required_commands"],
        },
        kind="source_review",
    )
    project = resolve_project_context(root, state_dir)
    command = "python -m pytest -q"
    command_digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    environment_digest = project_command_environment_sha256(project.settings, "test")
    arguments_digest = hashlib.sha256(b"[]").hexdigest()
    binding = {
        "project_alias": "test",
        "project_config_digest": project.config_digest,
        "configured_command_sha256": command_digest,
        "caller_arguments_sha256": arguments_digest,
        "command_sha256": command_digest,
        "project_environment_sha256": environment_digest,
    }
    execution_binding_digest = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    command_proof = {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": "task-mcp",
            "owner": "agent",
            "repository_revision": "rev-mcp",
            "mutation_generation": 0,
            "criterion": "test",
            "command_id": "cmd-mcp",
            "command_classification": "test",
            "command": command,
            "command_sha256": command_digest,
            **binding,
            "project_execution_binding_sha256": execution_binding_digest,
            "exit_code": 0,
            "result": {"success": True, "exit_code": 0},
            "cached": False,
        }
    command_evidence = artifact_store.put_json(
        command_proof,
        kind="command_verification",
    )
    verification_store.record(
        VerificationReceipt.create(
            "task-mcp",
            "required_commands",
            evidence_id=source_evidence,
            owner="agent",
            repository_revision="rev-mcp",
        )
    )
    command_receipt = VerificationReceipt.create(
        "task-mcp",
        "test",
        evidence_id=command_evidence,
        command_id="cmd-mcp",
        owner="agent",
        repository_revision="rev-mcp",
        mutation_generation=0,
        evidence_type="test",
    )
    verification_store.record(command_receipt)
    _bind_execution_record(
        verification_store,
        command_receipt,
        command_proof,
        root,
    )
    first_completion_attempt = mcp_server.local_ai_coord(
        action="task_complete", task_id="task-mcp", root=str(root), reason="done"
    )
    assert first_completion_attempt["success"] is False
    assert task_store.get("task-mcp").status.value == "planned"
    _bind_execution_record(
        verification_store,
        command_receipt,
        command_proof,
        root,
    )

    completed = mcp_server.local_ai_coord(
        action="task_complete", task_id="task-mcp", root=str(root), reason="done"
    )
    assert completed["success"] is True
    assert completed["task"]["status"] == "completed"


def test_invalid_project_configuration_blocks_completion(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text("[verification_rules]\nbad = false\n", encoding="utf-8")
    verification = _VerificationStore(CompletionResult("task-1", False, (), ("check",), (), ()))
    task = SimpleNamespace(
        task_id="task-1",
        owner="owner-1",
        context=SimpleNamespace(repository_id=str(root.resolve())),
        checkpoint=SimpleNamespace(state_data={"mutation_generation": 0}),
    )
    verification.task_store = SimpleNamespace(get=lambda task_id: task if task_id == task.task_id else None)

    result = evaluate_project_completion(
        verification,
        "task-1",
        root=root,
        state_dir=tmp_path / "state",
    )

    assert not result.complete
    assert result.unsatisfied_criteria == ("project_configuration",)
    assert verification.calls == []


def test_project_completion_rejects_root_not_bound_to_task(tmp_path: Path) -> None:
    trusted_root, state_dir = _project(tmp_path)
    coordination_id = resolve_project_context(trusted_root, state_dir).coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    verification = _VerificationStore(CompletionResult("task-1", False, (), ("check",), (), ()))
    task = SimpleNamespace(
        task_id="task-1",
        owner="owner-1",
        context=SimpleNamespace(repository_id=coordination_id),
        checkpoint=SimpleNamespace(state_data={"mutation_generation": 0}),
    )
    verification.task_store = SimpleNamespace(get=lambda task_id: task if task_id == task.task_id else None)

    result = evaluate_project_completion(
        verification,
        "task-1",
        root=foreign_root,
        state_dir=state_dir,
        current_revision="rev-1",
    )

    assert not result.complete
    assert result.unsatisfied_criteria == ("trusted_project_root",)
    assert verification.calls == []


def test_completion_handler_uses_persisted_receipts_and_completes_task(tmp_path: Path) -> None:
    root, state_dir = _project(tmp_path)
    (root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q"\n'
        '[verification_rules]\nrequired_commands = ["test"]\n',
        encoding="utf-8",
    )
    state_dir.mkdir(exist_ok=True)
    coordination_id = resolve_project_context(root, state_dir).coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    state_store = AgentStateStore(state_dir / "agent_state.sqlite")
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verification_store = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )
    task_store.create(
        GoalContract(goal="verify configured rule", acceptance_criteria=("required_commands",)),
        ScopeContext(task_id="task-live", repository_id=coordination_id, session_id="session-live"),
        task_id="task-live",
        repo_root=str(root),
    )

    source_evidence = artifact_store.put_json(
        {
            "kind": "work_source_review",
            "passed": True,
            "task_id": "task-live",
            "owner": "agent",
            "repository_revision": "rev-live",
            "mutation_generation": 0,
            "criteria": ["required_commands"],
        },
        kind="source_review",
    )
    project = resolve_project_context(root, state_dir)
    command = "python -m pytest -q"
    command_digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    environment_digest = project_command_environment_sha256(project.settings, "test")
    arguments_digest = hashlib.sha256(b"[]").hexdigest()
    binding = {
        "project_alias": "test",
        "project_config_digest": project.config_digest,
        "configured_command_sha256": command_digest,
        "caller_arguments_sha256": arguments_digest,
        "command_sha256": command_digest,
        "project_environment_sha256": environment_digest,
    }
    execution_binding_digest = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    command_proof = {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": "task-live",
            "owner": "agent",
            "repository_revision": "rev-live",
            "mutation_generation": 0,
            "criterion": "test",
            "command_id": "cmd-live",
            "command_classification": "test",
            "command": command,
            **binding,
            "project_execution_binding_sha256": execution_binding_digest,
            "exit_code": 0,
            "result": {"success": True, "exit_code": 0},
            "cached": False,
        }
    command_evidence = artifact_store.put_json(
        command_proof,
        kind="command_verification",
    )
    verification_store.record(
        VerificationReceipt.create(
            "task-live",
            "required_commands",
            evidence_id=source_evidence,
            owner="agent",
            repository_revision="rev-live",
        )
    )
    command_receipt = VerificationReceipt.create(
        "task-live",
        "test",
        evidence_id=command_evidence,
        command_id="cmd-live",
        owner="agent",
        repository_revision="rev-live",
        mutation_generation=0,
        evidence_type="test",
    )
    verification_store.record(command_receipt)
    _bind_execution_record(verification_store, command_receipt, command_proof, root)

    task = complete_task_with_project_rules(
        task_store,
        verification_store,
        "task-live",
        root=root,
        state_dir=state_dir,
        current_revision="rev-live",
    )

    assert task.status.value == "completed"
