from __future__ import annotations

import json
import hashlib
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

from local_ai_hub import http_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint
from local_ai_hub.agent_verification import VerificationReceipt, criterion_evidence_type
from local_ai_hub.app import LocalAIApp
from local_ai_hub.project_config import resolve_project_context


def _record_command(
    app: LocalAIApp,
    *,
    criterion: str,
    receipt_task_id: str,
    proof_task_id: str,
    owner: str,
    artifact_tenant: str,
    revision: str,
    command_id: str,
    project_config_digest: str,
) -> tuple[str, bool]:
    command_text = {
        "test": "python -m pytest -q tests/test_contract.py",
        "lint": "python -m ruff check src",
    }.get(criterion, "unknown configured command")
    command_sha256 = hashlib.sha256(command_text.encode("utf-8")).hexdigest()
    project_environment_sha256 = hashlib.sha256(b"{}").hexdigest()
    configured_command_sha256 = hashlib.sha256(command_text.encode("utf-8")).hexdigest()
    caller_arguments_sha256 = hashlib.sha256(b"[]").hexdigest()
    execution_binding = hashlib.sha256(
        json.dumps(
            {
                "project_alias": criterion,
                "project_config_digest": project_config_digest,
                "configured_command_sha256": configured_command_sha256,
                "caller_arguments_sha256": caller_arguments_sha256,
                "command_sha256": command_sha256,
                "project_environment_sha256": project_environment_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    evidence_id = app.artifacts.put_json(
        {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": proof_task_id,
            "owner": owner,
            "repository_revision": revision,
            "mutation_generation": 0,
            "criterion": criterion,
            "command_id": command_id,
            "command_classification": criterion_evidence_type(criterion),
            "command": command_text,
            "project_alias": criterion,
            "project_config_digest": project_config_digest,
            "project_environment_sha256": project_environment_sha256,
            "configured_command_sha256": configured_command_sha256,
            "caller_arguments_sha256": caller_arguments_sha256,
            "project_execution_binding_sha256": execution_binding,
            "command_sha256": command_sha256,
            "exit_code": 0,
            "result": {"success": True, "exit_code": 0},
        },
        artifact_tenant,
        "command_verification",
    )
    try:
        app.agent_verification.record(
            VerificationReceipt.create(
                receipt_task_id,
                criterion,
                evidence_id=evidence_id,
                command_id=command_id,
                owner=owner,
                repository_revision=revision,
                mutation_generation=0,
                evidence_type=criterion_evidence_type(criterion),
            )
        )
    except ValueError:
        return evidence_id, False
    return evidence_id, True


_CASES = (
    pytest.param(
        "valid",
        {
            "memory_context": {"items": [{"id": "mem-unused"}]},
            "memory_audit": {"used_ids": [], "not_used_reason": "not relevant to this task"},
        },
        True,
        id="project-rules-add-receipt-criteria-and-valid-memory-audit",
    ),
    pytest.param(
        "valid-used-memory",
        {
            "memory_context": {"items": [{"id": "mem-volatile", "volatile": True}]},
            "memory_audit": {
                "used_ids": ["mem-volatile"],
                "source_checks": {"mem-volatile": {"source": "current source"}},
            },
        },
        True,
        id="used-volatile-memory-has-current-source-check",
    ),
    pytest.param("owner-mismatch", {"test_owner": "other-agent"}, False, id="owner-mismatch"),
    pytest.param("tenant-mismatch", {"test_artifact_tenant": "other-agent", "expect_record_rejected": True}, False, id="artifact-tenant-mismatch"),
    pytest.param("task-mismatch", {"test_receipt_task_id": "other-task", "test_proof_task_id": "other-task"}, False, id="task-mismatch"),
    pytest.param("revision-mismatch", {"test_revision": "stale-revision"}, False, id="revision-mismatch"),
    pytest.param("criterion-mismatch", {"test_criterion": "test-other"}, False, id="criterion-mismatch"),
    pytest.param("missing-project-lint", {"include_lint": False}, False, id="additive-project-command-required"),
    pytest.param(
        "used-volatile-without-source",
        {"memory_context": {"items": [{"id": "mem-volatile", "volatile": True}]}, "memory_audit": {"used_ids": ["mem-volatile"]}},
        False,
        id="used-memory-requires-source-check",
    ),
    pytest.param(
        "unused-memory-without-reason",
        {"memory_context": {"items": [{"id": "mem-unused"}]}, "memory_audit": {"used_ids": []}},
        False,
        id="unused-memory-requires-reason",
    ),
    pytest.param(
        "skipped-memory-without-reason",
        {"memory_context": {"items": [], "warnings": [{"code": "memory_stale_skipped"}]}, "memory_audit": {"used_ids": []}},
        False,
        id="skipped-memory-requires-reason",
    ),
)


@pytest.mark.parametrize(("case", "changes", "expected_success"), _CASES)
def test_task_completion_http_receipt_and_memory_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    changes: dict[str, object],
    expected_success: bool,
) -> None:
    tenant = "agent-t09"
    task_id = f"task-t09-{case}"
    revision = "rev-t09-matrix-current"
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q tests/test_contract.py"\n'
        'lint = "python -m ruff check src"\n'
        '[verification_rules]\ntest = ["test", "lint"]\n',
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
    project_config_digest = resolve_project_context(project_root, state_dir).config_digest

    app = LocalAIApp(str(config_path))
    memory_context = changes.get("memory_context")
    if memory_context is not None:
        # Model the memory bundle injected by the server at task creation.
        # T08 makes that field immutable through the checkpoint API.
        monkeypatch.setattr(
            app.agent_tasks,
            "_task_memory_context",
            lambda _task_id, _contract, _context, **_kwargs: memory_context,
        )
    app.agent_tasks.create(
        GoalContract(
            goal="exercise project completion receipt gates over HTTP",
            acceptance_criteria=("test",),
        ),
        ScopeContext(repository_id=str(project_root), task_id=task_id),
        task_id=task_id,
        actor=tenant,
        repo_root=str(project_root),
    )
    if changes.get("test_receipt_task_id") == "other-task":
        app.agent_tasks.create(
            GoalContract(goal="unrelated task", acceptance_criteria=("test",)),
            ScopeContext(repository_id=str(project_root), task_id="other-task"),
            task_id="other-task",
            actor=tenant,
            repo_root=str(project_root),
        )
    memory_audit = changes.get("memory_audit")
    if memory_audit is not None:
        task = app.agent_tasks.get(task_id)
        assert task is not None
        state_data = dict(task.checkpoint.state_data)
        state_data["memory_audit"] = memory_audit
        app.agent_tasks.checkpoint(
            task_id,
            TaskCheckpoint(
                phase="verification",
                state_data=state_data,
            ),
            actor=tenant,
        )

    test_criterion = str(changes.get("test_criterion", "test"))
    test_owner = str(changes.get("test_owner", tenant))
    test_artifact_tenant = str(changes.get("test_artifact_tenant", test_owner))
    test_revision = str(changes.get("test_revision", revision))
    test_task_id = str(changes.get("test_receipt_task_id", task_id))
    test_proof_task_id = str(changes.get("test_proof_task_id", test_task_id))
    test_evidence_id, test_receipt_recorded = _record_command(
        app,
        criterion=test_criterion,
        receipt_task_id=test_task_id,
        proof_task_id=test_proof_task_id,
        owner=test_owner,
        artifact_tenant=test_artifact_tenant,
        revision=test_revision,
        command_id=f"cmd-{case}-test",
        project_config_digest=project_config_digest,
    )
    expected_receipt_recorded = not bool(changes.get("expect_record_rejected"))
    assert test_receipt_recorded is expected_receipt_recorded, case
    if not test_receipt_recorded:
        task_tenant_view = app.artifacts.get(test_evidence_id, max_chars=50_000, tenant=tenant)
        assert task_tenant_view.get("success") is False, (case, task_tenant_view)
    if changes.get("include_lint", True):
        _record_command(
            app,
            criterion="lint",
            receipt_task_id=task_id,
            proof_task_id=task_id,
            owner=tenant,
            artifact_tenant=tenant,
            revision=revision,
            command_id=f"cmd-{case}-lint",
            project_config_digest=project_config_digest,
        )

    monkeypatch.setattr(
        http_server,
        "_completion_revision_or_stop",
        lambda *_args: (revision, None),
    )
    previous_app = http_server.APP
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
                    "reason": "receipt matrix case verified",
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Agent": tenant,
                "X-LocalAI-Tenant": tenant,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            status = error.code
            payload = json.loads(error.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app

    assert payload["success"] is expected_success, (case, status, payload)
    if expected_success:
        assert status == 200
        assert payload["task"]["task_id"] == task_id
        assert payload["task"]["status"] == "completed"
        stored = app.agent_tasks.get(task_id)
        assert stored is not None
        assert stored.owner == tenant
        assert stored.context.repository_id == str(project_root)
        assert stored.checkpoint.state_data["repo_root"] == str(project_root.resolve())
        assert stored.checkpoint.state_data["repository_revision"] == revision
    else:
        assert status == 400
        stored = app.agent_tasks.get(task_id)
        assert stored is not None
        assert stored.status.value != "completed"
