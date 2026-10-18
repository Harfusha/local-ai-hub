import hashlib
import json
import subprocess
from types import SimpleNamespace

from local_ai_hub.commands import (
    CommandBroker,
    CommandInvocation,
    _ResolvedProjectCommand,
)
from local_ai_hub import commands as commands_module
from local_ai_hub.process_utils import hidden_run_kwargs
from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence


def test_project_command_fingerprints_preserve_receipt_inputs() -> None:
    command = "python -m pytest -q"
    configured = "python -m pytest"
    context = _ResolvedProjectCommand(
        alias="tests",
        command=command,
        environment={"ZED": "last", "ALPHA": "first"},
        config_digest="project-config-digest",
        cache_context="cache-context",
        configured_command=configured,
        caller_arguments=("--quiet", "café"),
    )

    assert CommandBroker._project_command_fingerprints(command, context) == (
        "tests",
        "project-config-digest",
        hashlib.sha256(b'{"ALPHA":"first","ZED":"last"}').hexdigest(),
        hashlib.sha256(configured.encode("utf-8")).hexdigest(),
        hashlib.sha256('["--quiet","café"]'.encode("utf-8")).hexdigest(),
    )


def test_project_command_fingerprints_encode_argv_invocation_identity() -> None:
    command = "python -m pytest -q"
    configured = CommandInvocation(argv=["python", "-m", "pytest"], cwd="repo", shell=False)
    context = _ResolvedProjectCommand(
        alias="tests",
        command=command,
        environment={},
        config_digest="cfg",
        cache_context="cache",
        configured_command=configured,
        caller_arguments=(),
    )
    configured_text = json.dumps(
        {"argv": configured.argv, "cwd": configured.cwd, "shell": configured.shell},
        sort_keys=True,
        separators=(",", ":"),
    )

    assert CommandBroker._project_command_fingerprints(command, context)[3] == (
        hashlib.sha256(configured_text.encode("utf-8")).hexdigest()
    )


def test_project_command_fingerprints_ignore_missing_or_mismatched_context() -> None:
    command = "python -m pytest -q"
    assert CommandBroker._project_command_fingerprints(command, None) == ("", "", "", "", "")
    context = _ResolvedProjectCommand(
        alias="tests",
        command=command,
        environment={},
        config_digest="cfg",
        cache_context="cache",
        configured_command=command,
        caller_arguments=(),
    )
    assert CommandBroker._project_command_fingerprints("python -m pytest", context) == (
        "", "", "", "", ""
    )


def test_finalize_run_result_compacts_and_attaches_execution_id() -> None:
    broker = object.__new__(CommandBroker)
    broker.policy_engine = None
    observed = {}

    def compact(result, command):
        observed.update(result=result, command=command)
        return {"success": result["success"]}

    broker._compact = compact
    source = {"success": True, "duration_ms": 125}
    finalized = broker._finalize_run_result(
        source,
        command="python -m pytest -q",
        cwd="repo",
        execution_id="execution-1",
        task_id="",
        auto_fix=False,
        max_repair_attempts=3,
        criterion="",
        declared_paths=None,
        effective_timeout=30,
        fix_generator=None,
        docker_image="python:3.11-slim",
        work_attempt_fence=None,
    )

    assert observed == {
        "result": source,
        "command": "python -m pytest -q",
    }
    assert finalized == {"success": True, "execution_id": "execution-1"}


def test_finalize_run_result_charges_compute_and_external_call() -> None:
    broker = object.__new__(CommandBroker)
    charges = []

    class PolicyEngine:
        def consume(self, task_id, cost):
            charges.append((task_id, cost.compute_seconds, cost.external_calls))

    broker.policy_engine = PolicyEngine()
    broker._compact = lambda result, command: dict(result)
    broker._finalize_run_result(
        {"success": True, "duration_ms": 1250},
        command="python -m pytest -q",
        cwd="repo",
        execution_id="execution-2",
        task_id="task-a",
        auto_fix=False,
        max_repair_attempts=3,
        criterion="",
        declared_paths=None,
        effective_timeout=30,
        fix_generator=None,
        docker_image="python:3.11-slim",
        work_attempt_fence=None,
    )

    assert charges == [("task-a", 1.25, 1)]


def test_finalize_run_result_routes_failed_autofix_once() -> None:
    broker = object.__new__(CommandBroker)
    broker.policy_engine = None
    broker._compact = lambda result, command: dict(result)
    calls = []

    def repair(*args, **kwargs):
        calls.append((args, kwargs))
        return {"success": True, "repaired": True}

    broker.repair_loop = repair
    finalized = broker._finalize_run_result(
        {"success": False, "error": "failed"},
        command="python -m pytest -q",
        cwd="repo",
        execution_id="execution-3",
        task_id="task-a",
        auto_fix=True,
        max_repair_attempts=2,
        criterion="criterion-a",
        declared_paths=["src/file.py"],
        effective_timeout=30,
        fix_generator=None,
        docker_image="python:3.11-slim",
        work_attempt_fence=None,
    )

    assert len(calls) == 1
    assert calls[0][0][:2] == ("python -m pytest -q", "repo")
    assert calls[0][1]["initial_result"]["execution_id"] == "execution-3"
    assert finalized == {"success": True, "repaired": True, "execution_id": "execution-3"}


def _public_run_broker(tmp_path, monkeypatch, *, result, classification):
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}},
        artifacts=None,
        repo_state=None,
    )
    monkeypatch.setattr(broker, "classify", lambda _command: dict(classification))
    monkeypatch.setattr(broker, "_project_environment", lambda *_args: ("", {}, None))
    monkeypatch.setattr(broker, "_tool_identity", lambda *_args, **_kwargs: "tool-identity")
    monkeypatch.setattr(broker, "_attempt_key", lambda *_args, **_kwargs: "attempt-key")
    monkeypatch.setattr(
        broker,
        "_key",
        lambda *_args, **_kwargs: (
            "result-key",
            {"fingerprint": "revision-1", "root": str(tmp_path)},
        ),
    )
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(broker, "_execute", lambda *_args, **_kwargs: dict(result))
    monkeypatch.setattr(broker, "_extract_diagnostics", lambda _result: [])
    monkeypatch.setattr(broker, "_record_command_verification", lambda *_args, **_kwargs: None)
    return broker


def _configured_command_context(command):
    configured = CommandInvocation(
        argv=["python", "-m", "pytest"],
        cwd="repo",
        shell=False,
    )
    return _ResolvedProjectCommand(
        alias="tests",
        command=command,
        environment={"ZED": "last", "ALPHA": "café"},
        config_digest="project-config-digest",
        cache_context="cache-context",
        configured_command=configured,
        caller_arguments=("--quiet", "café"),
    )


def _expected_receipt_fingerprints(context):
    environment_sha256 = hashlib.sha256(
        json.dumps(context.environment, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    configured = context.configured_command
    configured_sha256 = hashlib.sha256(
        json.dumps(
            {"argv": configured.argv, "cwd": configured.cwd, "shell": configured.shell},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    caller_arguments_sha256 = hashlib.sha256(
        json.dumps(
            list(context.caller_arguments),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return environment_sha256, configured_sha256, caller_arguments_sha256


def test_public_run_binds_invocation_unicode_and_cache_receipt(tmp_path, monkeypatch) -> None:
    command = "python -m pytest -q"
    context = _configured_command_context(command)
    receipts = []
    broker = _public_run_broker(
        tmp_path,
        monkeypatch,
        result={"success": True, "stdout": "ok", "stderr": "", "duration_ms": 125},
        classification={"class": "validation", "allowed": True, "cacheable": True},
    )
    monkeypatch.setattr(
        broker,
        "_record_command_verification",
        lambda _result, **fields: receipts.append(dict(fields)),
    )
    charges = []

    class Budget:
        def is_exhausted(self):
            return False

    class PolicyEngine:
        def get_budget(self, _task_id):
            return Budget()

        def consume(self, task_id, cost):
            charges.append((task_id, cost.compute_seconds, cost.external_calls))

    broker.policy_engine = PolicyEngine()
    executions = []
    monkeypatch.setattr(
        broker,
        "_execute",
        lambda *_args, **_kwargs: executions.append("executed")
        or {"success": True, "stdout": "ok", "stderr": "", "duration_ms": 125},
    )

    first = broker.run(
        command,
        str(tmp_path),
        task_id="task-a",
        criterion="public-run-contract",
        _project_command_context=context,
    )
    second = broker.run(
        command,
        str(tmp_path),
        task_id="task-a",
        criterion="public-run-contract",
        _project_command_context=context,
    )

    environment_sha256, configured_sha256, arguments_sha256 = _expected_receipt_fingerprints(context)
    assert first["success"] is True
    assert first["cache_hit"] is False
    assert first["coalesced"] is False
    assert first["execution_id"]
    assert second["success"] is True
    assert second["cache_hit"] is True
    assert second["coalesced"] is False
    assert executions == ["executed"]
    assert charges == [("task-a", 0.125, 1)]
    assert len(receipts) == 2
    for receipt in receipts:
        assert receipt["project_alias"] == "tests"
        assert receipt["project_config_digest"] == "project-config-digest"
        assert receipt["project_environment_sha256"] == environment_sha256
        assert receipt["configured_command_sha256"] == configured_sha256
        assert receipt["caller_arguments_sha256"] == arguments_sha256
    assert receipts[1]["cached"] is True


def test_public_run_failed_repair_keeps_execution_and_receipt_binding(
    tmp_path, monkeypatch
) -> None:
    command = "python -m pytest -q"
    context = _configured_command_context(command)
    source_root = tmp_path / "source"
    worktree = tmp_path / "task-worktree"
    source_root.mkdir()
    (source_root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(
        ["git", "init", "--quiet"], cwd=source_root, check=True, **hidden_run_kwargs()
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=source_root,
        check=True,
        **hidden_run_kwargs(),
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=source_root,
        check=True,
        **hidden_run_kwargs(),
    )
    subprocess.run(
        ["git", "add", "tracked.txt"], cwd=source_root, check=True, **hidden_run_kwargs()
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "initial"],
        cwd=source_root,
        check=True,
        **hidden_run_kwargs(),
    )
    branch = "test-command-run-repair"
    subprocess.run(
        ["git", "-C", str(source_root), "worktree", "add", "--quiet", "-b", branch, str(worktree), "HEAD"],
        check=True,
        **hidden_run_kwargs(),
    )
    receipts = []
    repair_calls = []
    broker = _public_run_broker(
        tmp_path,
        monkeypatch,
        result={"success": False, "error": "validation failed", "duration_ms": 250},
        classification={"class": "validation", "allowed": True, "cacheable": False},
    )
    monkeypatch.setattr(broker, "_distill_error", lambda _result: "validation failed")
    monkeypatch.setattr(broker, "_needs_model_error_distillation", lambda _result: False)
    monkeypatch.setattr(
        broker,
        "_run_private_transaction",
        lambda *_args, **_kwargs: {
            "success": False,
            "error": "validation failed",
            "duration_ms": 250,
        },
    )
    monkeypatch.setattr(
        commands_module,
        "_snapshot_rollback_scope",
        lambda *_args, **_kwargs: (None, None),
    )
    monkeypatch.setattr(
        broker,
        "_record_command_verification",
        lambda _result, **fields: receipts.append(dict(fields)),
    )
    broker.incident_store = None
    broker.set_task_store(SimpleNamespace(get=lambda _task_id: SimpleNamespace(
        checkpoint=SimpleNamespace(state_data={"worktree": {
            "success": True,
            "worktree_path": str(worktree),
            "repo_root": str(source_root),
            "branch": branch,
        }})
    )))
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())

    def repair(*args, **kwargs):
        repair_calls.append((args, kwargs))
        return {"success": True, "repaired": True}

    monkeypatch.setattr(broker, "repair_loop", repair)
    result = broker.run(
        command,
        str(worktree),
        task_id="task-a",
        criterion="public-run-repair-contract",
        auto_fix=True,
        paths=["generated.txt"],
        bypass_cache=True,
        _project_command_context=context,
    )

    environment_sha256, configured_sha256, arguments_sha256 = _expected_receipt_fingerprints(context)
    assert result["success"] is True
    assert result["repaired"] is True
    assert result["execution_id"]
    assert result.get("cache_hit") is None
    assert result.get("coalesced") is None
    assert len(repair_calls) == 1
    assert repair_calls[0][0][:3] == (command, str(worktree), "agent")
    initial_result = repair_calls[0][1]["initial_result"]
    assert initial_result["execution_id"] == result["execution_id"]
    assert initial_result["cache_hit"] is False
    assert initial_result["coalesced"] is False
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["project_environment_sha256"] == environment_sha256
    assert receipt["configured_command_sha256"] == configured_sha256
    assert receipt["caller_arguments_sha256"] == arguments_sha256
