from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

from local_ai_hub import http_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint, TaskStatus
from local_ai_hub.app import LocalAIApp
from local_ai_hub.project_config import resolve_project_context
from local_ai_hub.verification_rules import project_command_environment_sha256


def _record_command(
    app: LocalAIApp,
    *,
    criterion: str,
    receipt_task_id: str,
    proof_task_id: str,
    owner: str,
    revision: str,
    command_id: str,
    project_config_digest: str,
    repository_root: str | Path = "",
    record_root_override: str | Path = "",
) -> tuple[str, dict[str, object] | None]:
    del revision, command_id, project_config_digest
    root = record_root_override or repository_root
    task = app.agent_tasks.get(receipt_task_id)
    if (
        criterion not in {"test", "lint"}
        or not root
        or receipt_task_id != proof_task_id
        or task is None
        or task.owner != owner
    ):
        return "", None
    try:
        result = app.commands.run_project_command(
            criterion,
            str(root),
            task_id=proof_task_id,
            criterion=criterion,
            timeout=60,
            force=True,
        )
    except (OSError, ValueError):
        return "", None
    if result.get("success") is not True:
        return str(result.get("error") or result), None
    receipt = result.get("verification_receipt")
    if not isinstance(receipt, dict) or receipt.get("task_id") != receipt_task_id:
        details = {key: result.get(key) for key in (
            "status", "task_id", "criterion", "command_id", "verification_receipt",
            "error", "allowed", "reason", "classification", "summary", "stderr"
        ) if key in result}
        return f"missing authentic receipt: {details}; keys={sorted(result)}", None
    evidence_id = receipt.get("evidence_id")
    return (str(evidence_id), receipt) if isinstance(evidence_id, str) and evidence_id else ("", None)

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
    pytest.param("owner-mismatch", {"task_owner": "other-agent"}, False, id="owner-mismatch"),
    pytest.param("repository-mismatch", {"test_record_root": "other-repository"}, False, id="repository-mismatch"),
    pytest.param("task-mismatch", {"test_receipt_task_id": "other-task", "test_proof_task_id": "other-task"}, False, id="task-mismatch"),
    pytest.param("revision-mismatch", {"task_revision": "stale-revision"}, False, id="revision-mismatch"),
    pytest.param("criterion-mismatch", {"test_criterion": "lint"}, False, id="criterion-mismatch"),
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
    request: pytest.FixtureRequest,
) -> None:
    api_token = "t09-isolated-http-matrix-token-long"
    task_id = f"task-t09-{case}"
    project_root = tmp_path / "repo"
    project_root.mkdir()
    session_id = f"session-{task_id}"
    (project_root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -B -m pytest -p no:cacheprovider -q tests/test_contract.py"\n'
            'lint = "pyflakes src"\n'
        '[verification_rules]\ntest = ["test", "lint"]\n',
        encoding="utf-8",
    )
    (project_root / "tests").mkdir()
    (project_root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (project_root / "tests/test_contract.py").write_text("def test_contract():\n    assert True\n", encoding="utf-8")
    (project_root / "src").mkdir()
    (project_root / "src/__init__.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Agent OS Test"], cwd=project_root, check=True)
    subprocess.run(["git", "config", "user.email", "agent-os-test@example.invalid"], cwd=project_root, check=True)
    subprocess.run(["git", "add", "."], cwd=project_root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "test fixture"], cwd=project_root, check=True, capture_output=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_root, check=True, text=True, capture_output=True
    ).stdout.strip()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        "[prewarm]\nenabled = false\n"
        "[preprocessing]\nenabled = false\n"
        "[commands]\nenabled = true\nallow_validation = true\nallow_read = true\n"
        f'[security]\napi_token = "{api_token}"\n'
        f'allowed_roots = [{json.dumps(project_root.as_posix())}]\n',
        encoding="utf-8",
    )
    project_context = resolve_project_context(project_root, state_dir)
    project_config_digest = project_context.config_digest
    coordination_id = project_context.coordination_id
    assert isinstance(coordination_id, str) and coordination_id

    app = LocalAIApp(str(config_path))
    request.addfinalizer(app.close)
    app.commands.set_task_store(app.agent_tasks)
    app.commands.set_verification_store(app.agent_verification)
    app.agent_verification.set_command_execution_record_lookup(
        app.commands.get_command_execution_record
    )
    memory_context = changes.get("memory_context")
    if memory_context is not None:
        memory_context = {
            "schema_version": 2,
            "context": {
                "root": str(project_root.resolve()),
                "coordination_id": coordination_id,
                "task_id": task_id,
                "session_id": session_id,
                "clone_id": "",
                "worktree_id": "",
                "branch": "",
            },
            "instruction": "",
            "items": list(memory_context.get("items", [])),
            "warnings": list(memory_context.get("warnings", [])),
            "estimated_tokens": 0,
        }
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
            acceptance_criteria=("test", "lint"),
        ),
        ScopeContext(repository_id=coordination_id, task_id=task_id, session_id=session_id),
        task_id=task_id,
        actor=str(changes.get("task_owner", "agent-t09")),
        repo_root=str(project_root),
        repository_revision=("0" * 40 if case == "revision-mismatch" else revision),
    )
    task_owner = str(changes.get("task_owner", "agent-t09"))
    app.agent_tasks.transition(
        task_id,
        TaskStatus.ACTIVE,
        reason="begin verification",
        actor=task_owner,
        idempotency_key=f"{task_id}-active",
    )
    app.agent_tasks.transition(
        task_id,
        TaskStatus.VERIFYING,
        reason="receipt expected",
        actor=task_owner,
        idempotency_key=f"{task_id}-verifying",
    )
    if changes.get("memory_context") is None and changes.get("memory_audit") is None:
        app.agent_tasks.checkpoint(
            task_id,
            TaskCheckpoint(state_data={"repository_revision": revision, "mutation_generation": 0}),
            actor=task_owner,
            idempotency_key=f"{task_id}-revision",
        )
    if changes.get("test_receipt_task_id") == "other-task":
        app.agent_tasks.create(
            GoalContract(goal="unrelated task", acceptance_criteria=("test",)),
            ScopeContext(repository_id=coordination_id, task_id="other-task", session_id=session_id),
            task_id="other-task",
            actor=str(changes.get("task_owner", "agent-t09")),
            repo_root=str(project_root),
            repository_revision=revision,
        )
        app.agent_tasks.transition(
            "other-task",
            TaskStatus.ACTIVE,
            reason="begin verification",
            actor="agent-t09",
            idempotency_key="other-task-active",
        )
        app.agent_tasks.transition(
            "other-task",
            TaskStatus.VERIFYING,
            reason="receipt expected",
            actor="agent-t09",
            idempotency_key="other-task-verifying",
        )
        app.agent_tasks.checkpoint(
            "other-task",
            TaskCheckpoint(state_data={"repository_revision": revision, "mutation_generation": 0}),
            actor="agent-t09",
            idempotency_key="other-task-revision",
        )
    memory_audit = changes.get("memory_audit")
    if memory_context is not None or memory_audit is not None:
        task = app.agent_tasks.get(task_id)
        assert task is not None
        state_data = dict(task.checkpoint.state_data)
        state_data["repository_revision"] = str(changes.get("task_revision", revision))
        if memory_audit is not None:
            state_data["memory_audit"] = memory_audit
        checkpoint = TaskCheckpoint(phase="verification", state_data=state_data)
        if case in {
            "used-volatile-without-source",
            "unused-memory-without-reason",
            "skipped-memory-without-reason",
                "used-memory-requires-source-check",
                "unused-memory-requires-reason",
                "skipped-memory-requires-reason",
        }:
            # New writes reject invalid audits before persistence. Still exercise
            # completion's fail-closed handling of legacy/malformed stored state.
            before_checkpoint = app.agent_tasks.get(task_id)
            before_checkpoint_events = app.agent_state.events(f"task:{task_id}")
            with pytest.raises(CompletionGateError):
                app.agent_tasks.checkpoint(task_id, checkpoint, actor="agent-t09")
            assert app.agent_tasks.get(task_id) == before_checkpoint
            assert app.agent_state.events(f"task:{task_id}") == before_checkpoint_events
            with monkeypatch.context() as legacy_fixture:
                legacy_fixture.setattr(app.agent_tasks, "_validate_memory_audit", lambda _task: None)
                app.agent_tasks.checkpoint(task_id, checkpoint, actor="agent-t09")
        else:
            app.agent_tasks.checkpoint(task_id, checkpoint, actor="agent-t09")

    if "task_revision" in changes and memory_context is None and memory_audit is None:
        task = app.agent_tasks.get(task_id)
        assert task is not None
        state_data = dict(task.checkpoint.state_data)
        state_data["repository_revision"] = str(changes["task_revision"])
        app.agent_tasks.checkpoint(
            task_id,
            TaskCheckpoint(phase="verification", state_data=state_data),
            actor="agent-t09",
        )

    test_criterion = str(changes.get("test_criterion", "test"))
    test_owner = str(changes.get("test_owner", "agent-t09"))
    test_revision = str(changes.get("task_revision", revision))
    test_task_id = str(changes.get("test_receipt_task_id", task_id))
    test_proof_task_id = str(changes.get("test_proof_task_id", test_task_id))
    test_evidence_id, test_receipt = _record_command(
        app,
        criterion=test_criterion,
        receipt_task_id=test_task_id,
        proof_task_id=test_proof_task_id,
        owner=test_owner,
        revision=test_revision,
        command_id=f"cmd-{case}-test",
        project_config_digest=project_config_digest,
        repository_root=project_root,
        record_root_override=(project_root.parent / str(changes["test_record_root"])) if changes.get("test_record_root") else "",
    )
    test_receipt_recorded = isinstance(test_receipt, dict)
    # Receipt storage binds task owner; completion gates repository execution-record scope.
    assert test_receipt_recorded is (case not in {"repository-mismatch", "owner-mismatch"}), (
        case, test_evidence_id, test_receipt
    )
    if test_evidence_id and test_receipt_recorded:
        evidence_view = app.artifacts.get(test_evidence_id, max_chars=50_000)
        assert evidence_view.get("success") is True, (case, evidence_view)
    lint_receipt = None
    if changes.get("include_lint", True):
        lint_evidence_id, lint_receipt = _record_command(
            app,
            criterion="lint",
            receipt_task_id=task_id,
            proof_task_id=task_id,
            owner="agent-t09",
            revision=revision,
            command_id=f"cmd-{case}-lint",
            project_config_digest=project_config_digest,
            repository_root=project_root,
        )
        if case == "valid":
            assert isinstance(lint_receipt, dict), lint_evidence_id

    project_revision = (
        lint_receipt.get("repository_revision")
        if isinstance(lint_receipt, dict)
        else test_receipt.get("repository_revision") if isinstance(test_receipt, dict) else ""
    )
    if project_revision:
        revision = str(project_revision)
        if str(changes.get("task_revision", "")) != "stale-revision":
            task = app.agent_tasks.get(task_id)
            assert task is not None
            state_data = dict(task.checkpoint.state_data)
            state_data["repository_revision"] = revision
            checkpoint = TaskCheckpoint(phase="verification", state_data=state_data)
            if case in {
                "used-volatile-without-source",
                "unused-memory-without-reason",
                "skipped-memory-without-reason",
                "used-memory-requires-source-check",
                "unused-memory-requires-reason",
                "skipped-memory-requires-reason",
            }:
                with monkeypatch.context() as legacy_fixture:
                    legacy_fixture.setattr(app.agent_tasks, "_validate_memory_audit", lambda _task: None)
                    app.agent_tasks.checkpoint(
                        task_id, checkpoint, actor=str(changes.get("task_owner", "agent-t09"))
                    )
            else:
                app.agent_tasks.checkpoint(
                    task_id,
                    checkpoint,
                    actor=str(changes.get("task_owner", "agent-t09")),
                )

    if case == "revision-mismatch":
        task = app.agent_tasks.get(task_id)
        assert task is not None
        state_data = dict(task.checkpoint.state_data)
        state_data["repository_revision"] = "0" * 40
        app.agent_tasks.checkpoint(
            task_id,
            TaskCheckpoint(phase="verification", state_data=state_data),
            actor=task_owner,
        )

    if memory_context is not None:
        before_validation = app.agent_tasks.get(task_id)
        before_events = app.agent_state.events(f"task:{task_id}")
        try:
            app.agent_tasks.validate_completion(task_id)
            memory_gate_complete = True
            memory_gate_error = ""
        except CompletionGateError as error:
            memory_gate_complete = False
            memory_gate_error = str(error)
        receipt_identity = {
            key: test_receipt.get(key)
            for key in ("receipt_id", "task_id", "criterion", "owner", "repository_revision", "evidence_type", "mutation_generation")
        } if isinstance(test_receipt, dict) else None
        if receipt_identity is not None:
            receipt_identity["revision_matches_current"] = test_receipt.get("repository_revision") == revision
            receipt_identity["evidence_id"] = test_receipt.get("evidence_id")
        current_task = app.agent_tasks.get(task_id)
        assert memory_gate_complete is expected_success, (
            case,
            receipt_identity,
            getattr(current_task, "verification_receipts", None),
        )
        assert app.agent_tasks.get(task_id) == before_validation
        assert app.agent_state.events(f"task:{task_id}") == before_events

    verification_revision = "0" * 40 if case == "revision-mismatch" else revision
    preflight = app.agent_verification.completion(
        task_id,
        current_revision=verification_revision,
        current_mutation_generation=0,
        verification_rules=project_context.settings.verification_rules,
        configured_criteria=tuple(project_context.settings.commands),
        configured_commands=project_context.settings.commands,
        project_config_digest=project_config_digest,
        configured_environment_sha256={
            name: project_command_environment_sha256(project_context.settings, name)
            for name in project_context.settings.commands
        },
        project_root=project_root,
    )
    memory_gate_only_failures = {
        "used-volatile-without-source",
        "unused-memory-without-reason",
        "skipped-memory-without-reason",
    }
    assert preflight.complete is (expected_success or case in memory_gate_only_failures), (
        case, preflight.unsatisfied_criteria, preflight.stale_criteria,
    )

    monkeypatch.setattr(
        http_server,
        "_completion_revision_or_stop",
        lambda *_args: (verification_revision, None),
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
                "X-LocalAI-Token": api_token,
                "X-LocalAI-Agent": "agent-t09",
            },
            method="POST",
        )
        try:
            # Receipt/memory correctness includes SQLite close/checkpoint I/O;
            # this matrix does not impose a five-second throughput contract.
            with urllib.request.urlopen(request, timeout=15) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                payload = json.loads(error.read().decode("utf-8"))
        except TimeoutError as error:
            frames = sys._current_frames()
            stacks = {}
            for worker in threading.enumerate():
                frame = frames.get(worker.ident)
                stack = []
                while frame is not None and len(stack) < 16:
                    stack.append(f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}")
                    frame = frame.f_back
                stacks[worker.name] = stack
            raise AssertionError(f"completion HTTP timeout: {json.dumps(stacks, sort_keys=True)}") from error
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
        assert stored.owner == "agent-t09"
        assert stored.context.repository_id == coordination_id
        assert stored.checkpoint.state_data["repo_root"] == str(project_root.resolve())
        assert stored.checkpoint.state_data["repository_revision"] == revision
    else:
        assert status == (403 if case == "owner-mismatch" else 400)
        stored = app.agent_tasks.get(task_id)
        assert stored is not None
        assert stored.status.value != "completed"
