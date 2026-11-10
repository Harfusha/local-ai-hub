import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import textwrap

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_policy import PolicyEngine
from local_ai_hub.repo_plan.host_adapters import (
    HostCapabilitySnapshot,
    HostOperationStatus,
    HostShadowRequest,
    HostVerificationStatus,
    _antigravity_init_matches,
    authorize_antigravity_cli_turn,
    parse_antigravity_stream_event,
    parse_codex_app_server_notification,
    record_codex_shadow_event,
    record_antigravity_shadow_event,
    record_shadow_observation,
    resolve_antigravity_cli,
    reserve_antigravity_cli_turn,
)


def request(**overrides):
    values = {
        "host_name": "codex",
        "host_version": "0.167.0-alpha.3.2",
        "surface": "app_server",
        "session_type": "thread",
        "session_id": "raw-session-id",
        "repository_id": "a" * 64,
        "event_id": "raw-turn-id",
        "event_type": "turn.completed",
        "proposed_action": "read_only_review",
        "reason_code": "task_scope_match",
        "task_id": "task_123",
        "evidence_ids": ("evidence_123",),
    }
    values.update(overrides)
    return HostShadowRequest(**values)


def capability(**overrides):
    values = {
        "host_name": "codex",
        "host_version": "0.167.0-alpha.3.2",
        "surface": "app_server",
        "session_type": "thread",
        "hub_managed": True,
        "available_events": ("turn.completed",),
        "available_commands": ("thread.start",),
        "available_permissions": ("command.approval",),
        "permission_mode": "request_review",
        "permissions_verified": True,
        "would_be_denied": None,
        "verification_status": HostVerificationStatus.VERIFIED,
    }
    values.update(overrides)
    return HostCapabilitySnapshot(**values)


def test_shadow_observation_records_metadata_only_and_deduplicates(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    observed = request()

    first = record_shadow_observation(observed, capability(), store)
    second = record_shadow_observation(observed, capability(), store)

    assert first.status is HostOperationStatus.SHADOW_ONLY
    assert first.recorded and not first.duplicate
    assert second.status is HostOperationStatus.SHADOW_ONLY
    assert second.recorded and second.duplicate
    events = store.events(f"host-shadow:{first.session_ref}")
    assert len(events) == 1
    payload = events[0].payload
    serialized = json.dumps(payload)
    assert "raw-session-id" not in serialized
    assert "raw-turn-id" not in serialized
    assert "prompt" not in payload
    assert "transcript" not in serialized
    assert "source_code" not in serialized
    assert payload["proposal"]["status"] == "proposed"
    assert payload["outcome"] == "simulated"
    assert payload["permission_check"] == {
        "status": "not_evaluated",
        "would_be_denied": None,
    }
    assert payload["content_stored"] is False


def test_shadow_observation_deduplicates_after_event_store_restart(tmp_path):
    db_path = tmp_path / "agent_state.sqlite"
    runner = tmp_path / "record_shadow_event.py"
    runner.write_text(textwrap.dedent("""\
        import json
        from pathlib import Path
        import sys

        from local_ai_hub.agent_events import AgentStateStore
        from local_ai_hub.repo_plan.host_adapters import (
            HostCapabilitySnapshot,
            HostShadowRequest,
            HostVerificationStatus,
            record_shadow_observation,
        )

        store = AgentStateStore(Path(sys.argv[1]), enabled=True)
        request = HostShadowRequest(
            host_name="codex",
            host_version="0.167.0-alpha.3.2",
            surface="app_server",
            session_type="thread",
            session_id="raw-session-id",
            repository_id="a" * 64,
            event_id="restart-safe-event",
            event_type="thread.started",
            proposed_action="observe_event",
            reason_code="restart_persistence_test",
            task_id="task_123",
            evidence_ids=(),
        )
        capability = HostCapabilitySnapshot(
            host_name="codex",
            host_version="0.167.0-alpha.3.2",
            surface="app_server",
            session_type="thread",
            hub_managed=True,
            available_events=("thread.started",),
            available_commands=("thread.start",),
            available_permissions=("command.approval",),
            permission_mode="request_review",
            permissions_verified=False,
            would_be_denied=None,
            verification_status=HostVerificationStatus.VERIFIED,
        )
        result = record_shadow_observation(request, capability, store)
        print(json.dumps({
            "status": result.status.value,
            "recorded": result.recorded,
            "duplicate": result.duplicate,
            "event_count": len(store.events(f"host-shadow:{result.session_ref}")),
        }))
    """), encoding="utf-8")

    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (src_path, env.get("PYTHONPATH", "")) if value
    )
    project_root = Path(__file__).resolve().parents[1]

    def record_in_new_process():
        completed = subprocess.run(
            [sys.executable, str(runner), str(db_path)],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    first = record_in_new_process()
    after_process_restart = record_in_new_process()

    assert first == {
        "status": HostOperationStatus.SHADOW_ONLY.value,
        "recorded": True,
        "duplicate": False,
        "event_count": 1,
    }
    assert after_process_restart == {
        "status": HostOperationStatus.SHADOW_ONLY.value,
        "recorded": True,
        "duplicate": True,
        "event_count": 1,
    }


def test_codex_thread_started_parser_checks_scope_and_strips_private_fields(tmp_path):
    root = tmp_path.resolve()
    line = json.dumps({
        "method": "thread/started",
        "params": {
            "thread": {
                "id": "raw-thread-id",
                "cwd": str(root),
                "cliVersion": "0.167.0-alpha.3.2",
                "preview": "private first prompt",
                "path": str(root / "private-thread.jsonl"),
            }
        },
    })

    observation = parse_codex_app_server_notification(
        line, sequence=0, repo_root=root, expected_cli_version="0.167.0-alpha.3.2"
    )

    assert observation.host_name == "codex"
    assert observation.surface == "app_server"
    assert observation.event_type == "thread.started"
    assert "raw-thread-id" not in json.dumps(observation.to_dict())
    assert "private first prompt" not in json.dumps(observation.to_dict())
    assert str(root) not in json.dumps(observation.to_dict())

    other_root = tmp_path / "elsewhere"
    other_root.mkdir()
    with pytest.raises(ValueError, match="repository mismatch"):
        parse_codex_app_server_notification(
            line, sequence=1, repo_root=other_root, expected_cli_version="0.167.0-alpha.3.2"
        )
    with pytest.raises(ValueError, match="version mismatch"):
        parse_codex_app_server_notification(
            line, sequence=1, repo_root=root, expected_cli_version="other-version"
        )
    with pytest.raises(ValueError, match="unsupported"):
        parse_codex_app_server_notification(
            json.dumps({"method": "turn/completed", "params": {}}),
            sequence=1, repo_root=root, expected_cli_version="0.167.0-alpha.3.2",
        )
    with pytest.raises(ValueError, match="unsupported"):
        parse_codex_app_server_notification(
            json.dumps({"method": "thread/started", "id": 1, "params": {}}),
            sequence=1, repo_root=root, expected_cli_version="0.167.0-alpha.3.2",
        )


def test_codex_thread_started_uses_shared_shadow_sink(tmp_path):
    root = tmp_path.resolve()
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    observation = parse_codex_app_server_notification(
        json.dumps({
            "method": "thread/started",
            "params": {"thread": {
                "id": "thread-secret",
                "cwd": str(root),
                "cliVersion": "0.167.0-alpha.3.2",
                "preview": "secret prompt",
            }},
        }),
        sequence=3,
        repo_root=root,
        expected_cli_version="0.167.0-alpha.3.2",
    )
    snapshot = capability(
        host_name="codex",
        host_version="0.167.0-alpha.3.2",
        surface="app_server",
        session_type="thread",
        available_events=("thread.started",),
    )

    recorded = record_codex_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
        task_id="task_123",
    )

    assert recorded.status is HostOperationStatus.SHADOW_ONLY
    assert recorded.recorded
    payload = store.events(f"host-shadow:{recorded.session_ref}")[0].payload
    serialized = json.dumps(payload)
    assert "thread-secret" not in serialized
    assert "secret prompt" not in serialized
    assert str(root) not in serialized


@pytest.mark.skipif(
    os.environ.get("LOCAL_AI_HUB_RUN_CODEX_APP_SERVER_SMOKE") != "1",
    reason="set LOCAL_AI_HUB_RUN_CODEX_APP_SERVER_SMOKE=1 for isolated live Codex smoke",
)
def test_installed_codex_app_server_event_uses_metadata_only_shadow_sink(tmp_path):
    executable = shutil.which("codex")
    if not executable:
        pytest.skip("Codex CLI is not installed")

    repo_root = Path(__file__).resolve().parents[1]
    version_result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=5
    )
    assert version_result.returncode == 0
    version = version_result.stdout.strip().removeprefix("codex-cli ")
    assert version

    environment = os.environ.copy()
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    environment["CODEX_HOME"] = str(codex_home)
    process = subprocess.Popen(
        [executable, "app-server", "--listen", "stdio://"],
        cwd=repo_root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.put(line)
        output.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    sent_methods: list[str] = []

    def send(message: dict) -> None:
        assert process.stdin is not None
        sent_methods.append(message.get("method", ""))
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def receive_response(request_id: int, timeout: float = 8.0) -> tuple[dict | None, list[dict]]:
        deadline = time.monotonic() + timeout
        messages: list[dict] = []
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                messages.append(message)
                if message.get("id") == request_id:
                    return message, messages
        return None, messages

    try:
        send({
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "local_ai_hub_shadow_smoke",
                    "title": "Local AI Hub shadow smoke",
                    "version": "0.1.0",
                }
            },
        })
        initialized, messages = receive_response(1)
        assert initialized is not None and "result" in initialized

        send({"method": "initialized", "params": {}})
        send({
            "method": "thread/start",
            "id": 2,
            "params": {"cwd": str(repo_root), "ephemeral": True},
        })
        started, start_messages = receive_response(2)
        assert started is not None and "result" in started
        messages.extend(start_messages)

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                messages.append(message)

        notification = next(
            (message for message in messages if message.get("method") == "thread/started"),
            None,
        )
        assert notification is not None
        assert "turn/start" not in sent_methods

        observation = parse_codex_app_server_notification(
            json.dumps(notification),
            sequence=0,
            repo_root=repo_root,
            expected_cli_version=version,
        )
        capability_snapshot = HostCapabilitySnapshot(
            host_name="codex",
            host_version=version,
            surface="app_server",
            session_type="thread",
            hub_managed=True,
            available_events=("thread.started",),
            available_commands=("thread.start",),
            permission_mode="unknown",
            permissions_verified=False,
            verification_status=HostVerificationStatus.VERIFIED,
        )
        store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
        result = record_codex_shadow_event(
            observation,
            repository_id="a" * 64,
            capability=capability_snapshot,
            event_store=store,
        )

        assert result.status is HostOperationStatus.SHADOW_ONLY
        assert result.recorded
        events = store.events(f"host-shadow:{result.session_ref}")
        assert len(events) == 1
        payload = events[0].payload
        serialized = json.dumps(payload)
        assert payload["permission_check"] == {
            "status": "not_evaluated",
            "would_be_denied": None,
        }
        assert payload["content_stored"] is False
        assert notification["params"]["thread"]["id"] not in serialized
        assert str(repo_root) not in serialized
        assert "prompt" not in payload
        assert "transcript" not in serialized
        assert "source_code" not in serialized
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()


def test_unknown_or_unowned_session_fails_closed_without_storage(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)

    unknown = record_shadow_observation(
        request(),
        capability(verification_status=HostVerificationStatus.NOT_VERIFIED),
        store,
    )
    unowned = record_shadow_observation(
        request(event_id="turn-2"),
        capability(hub_managed=False),
        store,
    )

    assert unknown.status is HostOperationStatus.UNCERTAIN
    assert unowned.status is HostOperationStatus.REFUSED
    assert store.events(f"host-shadow:{unknown.session_ref}") == []


def test_version_mismatch_and_unsupported_host_fail_closed(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    mismatched = record_shadow_observation(
        request(), capability(host_version="0.168.0"), store
    )
    unsupported = record_shadow_observation(
        request(event_id="turn-unsupported"),
        capability(verification_status=HostVerificationStatus.UNSUPPORTED),
        store,
    )

    assert mismatched.status is HostOperationStatus.UNCERTAIN
    assert unsupported.status is HostOperationStatus.UNSUPPORTED
    assert store.events(f"host-shadow:{mismatched.session_ref}") == []


def test_unverified_permissions_are_recorded_as_unknown_and_denials_are_recorded(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    unknown_permissions = record_shadow_observation(
        request(), capability(permissions_verified=False, would_be_denied=True), store
    )
    denied = record_shadow_observation(
        request(event_id="turn-denied"), capability(would_be_denied=True), store
    )

    assert unknown_permissions.status is HostOperationStatus.SHADOW_ONLY
    assert unknown_permissions.recorded
    unknown_payload = store.events(f"host-shadow:{unknown_permissions.session_ref}")[0].payload
    assert unknown_payload["permission_check"] == {
        "status": "not_evaluated",
        "would_be_denied": None,
    }
    assert unknown_payload["content_stored"] is False
    assert denied.status is HostOperationStatus.REFUSED
    assert denied.recorded
    payload = store.events(f"host-shadow:{denied.session_ref}")[-1].payload
    assert payload["permission_check"]["status"] == "would_deny"
    assert payload["permission_check"]["would_be_denied"] is True


def test_unsupported_event_and_disabled_store_are_not_claimed_as_shadow_success(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=False)
    unsupported = record_shadow_observation(
        request(event_type="unknown.event"), capability(), store
    )
    unavailable = record_shadow_observation(request(), capability(), store)

    assert unsupported.status is HostOperationStatus.UNSUPPORTED
    assert unavailable.status is HostOperationStatus.UNCERTAIN
    assert not unsupported.recorded
    assert not unavailable.recorded


def test_uncertain_event_store_failure_never_becomes_success():
    class FailingStore:
        enabled = True

        def append(self, event):
            raise OSError("store unavailable")

    result = record_shadow_observation(request(), capability(), FailingStore())

    assert result.status is HostOperationStatus.UNCERTAIN
    assert not result.recorded


def test_capability_inventory_rejects_paths():
    with pytest.raises(ValueError, match="names, not paths"):
        capability(available_commands=(r"C:\Windows\System32\cmd.exe",))


def test_antigravity_stream_parser_keeps_metadata_and_discards_content():
    line = json.dumps({
        "event": "step_update",
        "step_update": {
            "conversation_id": "conversation-secret",
            "step_index": 7,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "run_command",
            "text_delta": "private answer",
            "tool_info": {
                "parameters": {"CommandLine": "private command"},
                "output": "private output",
            },
        },
    })

    observed = parse_antigravity_stream_event(line, sequence=4)

    assert observed.host_name == "antigravity"
    assert observed.event_type == "step_update.tool.done"
    assert observed.sequence == 4
    assert observed.verification_status is HostVerificationStatus.NOT_VERIFIED
    serialized = json.dumps(observed.to_dict())
    assert "private answer" not in serialized
    assert "private command" not in serialized
    assert "private output" not in serialized
    assert "conversation-secret" not in serialized


def test_antigravity_stream_parser_accepts_init_and_result_metadata_only():
    init = parse_antigravity_stream_event(json.dumps({
        "event": "init",
        "conversation_id": "conv-init",
        "init": {"cwd": "C:\\private", "tools": ["run_command"], "permission_mode": "request-review"},
    }), sequence=0)
    result = parse_antigravity_stream_event(json.dumps({
        "event": "result",
        "result": {"conversation_id": "conv-init", "status": "SUCCESS", "response": "private response"},
    }), sequence=9)

    assert init.event_type == "session.initialized"
    assert result.event_type == "session.result.success"
    assert "C:\\private" not in json.dumps(init.to_dict())
    assert "run_command" not in json.dumps(init.to_dict())
    assert "private response" not in json.dumps(result.to_dict())


def test_antigravity_stream_observation_uses_shared_shadow_gate(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    observation = parse_antigravity_stream_event(json.dumps({
        "event": "init",
        "conversation_id": "conversation-secret",
        "init": {"cwd": "C:\\private", "tools": ["run_command"], "permission_mode": "request-review"},
    }), sequence=0)
    snapshot = capability(
        host_name="antigravity",
        host_version="1.4.2",
        surface="cli_stream_json",
        session_type="conversation",
        available_events=("session.initialized",),
    )

    result = record_antigravity_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
        task_id="task_123",
    )

    assert result.status is HostOperationStatus.SHADOW_ONLY
    assert result.recorded
    events = store.events(f"host-shadow:{result.session_ref}")
    assert len(events) == 1
    serialized = json.dumps(events[0].payload)
    assert "conversation-secret" not in serialized
    assert "C:\\private" not in serialized
    assert "run_command" not in serialized
    assert "response" not in serialized


@pytest.mark.parametrize("line,sequence", [
    ("not-json", 0),
    (json.dumps({"event": "unknown", "conversation_id": "c"}), 0),
    (json.dumps({"event": "init", "conversation_id": "c", "init": {}}), -1),
    (json.dumps({"event": "step_update", "step_update": {"conversation_id": "c", "step_index": -1, "state": "ACTIVE", "step_type": "tool"}}), 1),
])
def test_antigravity_stream_parser_fails_closed(line, sequence):
    with pytest.raises(ValueError):
        parse_antigravity_stream_event(line, sequence=sequence)


def test_antigravity_cli_locator_finds_documented_windows_path(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    exe = tmp_path / "agy" / "bin" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"test executable marker")

    assert resolve_antigravity_cli() == exe.resolve()


def test_antigravity_cli_locator_returns_none_when_unavailable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert resolve_antigravity_cli() is None


def test_antigravity_cli_turn_requires_existing_policy_grant():
    class Broker:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def authorize_auxiliary_action(self, action, *, endpoint, task_id):
            self.calls.append((action, endpoint, task_id))
            return self.result

    denied_broker = Broker({
        "success": False,
        "allowed": False,
        "requires_approval": True,
        "reason": "network requires explicit approval or grant",
        "owner": "agent_policy",
        "side_effect_class": "model_execution",
    })
    allowed_broker = Broker({
        "success": True,
        "allowed": True,
        "requires_approval": False,
        "reason": "action permitted by capability grant",
        "owner": "agent_policy",
        "side_effect_class": "model_execution",
    })

    denied = authorize_antigravity_cli_turn(denied_broker, "task-123")
    allowed = authorize_antigravity_cli_turn(allowed_broker, "task-123")

    assert denied.allowed is False
    assert denied.requires_approval is True
    assert denied.side_effect_class == "model_execution"
    assert allowed.allowed is True
    assert allowed.requires_approval is False
    assert denied_broker.calls == [("model_inference", "antigravity_cli", "task-123")]
    assert allowed_broker.calls == [("model_inference", "antigravity_cli", "task-123")]


def test_antigravity_cli_turn_does_not_bypass_pending_approval():
    class Broker:
        def authorize_auxiliary_action(self, *_args, **_kwargs):
            return {"success": True, "allowed": True, "requires_approval": True}

    decision = authorize_antigravity_cli_turn(Broker(), "task-123")

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.reason == "approval_required"


def test_antigravity_cli_startup_requires_matching_root_model_and_no_tools(tmp_path):
    root = tmp_path.resolve()
    valid = json.dumps({
        "event": "init",
        "conversation_id": "conversation-id",
        "init": {
            "cwd": str(root),
            "model": "gemini-4-argon-high",
            "tools": [],
            "permission_mode": "request-review",
        },
    })
    with_tools = json.dumps({
        "event": "init",
        "conversation_id": "conversation-id",
        "init": {
            "cwd": str(root),
            "model": "gemini-4-argon-high",
            "tools": ["run_command"],
            "permission_mode": "request-review",
        },
    })
    wrong_model = valid.replace("gemini-4-argon-high", "other-model")

    assert _antigravity_init_matches(valid, repo_root=root, model="gemini-4-argon-high")
    assert not _antigravity_init_matches(with_tools, repo_root=root, model="gemini-4-argon-high")
    assert not _antigravity_init_matches(wrong_model, repo_root=root, model="gemini-4-argon-high")
    assert not _antigravity_init_matches("not-json", repo_root=root, model="gemini-4-argon-high")


@pytest.mark.parametrize("broker,task_id", [(None, "task-123"), (object(), "task-123"), (object(), "")])
def test_antigravity_cli_turn_fails_closed_without_broker_or_task(broker, task_id):
    decision = authorize_antigravity_cli_turn(broker, task_id)

    assert decision.allowed is False
    assert decision.requires_approval is False
    assert decision.side_effect_class == "model_execution"


def test_antigravity_cli_turn_fails_closed_on_broker_exception_or_malformed_result():
    class RaisingBroker:
        def authorize_auxiliary_action(self, *_args, **_kwargs):
            raise RuntimeError("policy unavailable")

    class MalformedBroker:
        def authorize_auxiliary_action(self, *_args, **_kwargs):
            return {"success": True, "allowed": "yes"}

    for broker in (RaisingBroker(), MalformedBroker()):
        decision = authorize_antigravity_cli_turn(broker, "task-123")
        assert decision.allowed is False
        assert decision.requires_approval is False


def test_antigravity_turn_reserves_durable_budget_once_before_launch(tmp_path):
    class Broker:
        policy_engine = PolicyEngine(AgentStateStore(tmp_path / "budget.sqlite", enabled=True))

        def authorize_auxiliary_action(self, *_args, **_kwargs):
            return {"success": True, "allowed": True, "requires_approval": False}

    broker = Broker()
    broker.policy_engine.set_budget("task-123", max_external_calls=1)

    first = reserve_antigravity_cli_turn(broker, "task-123", "1" * 32)
    duplicate = reserve_antigravity_cli_turn(broker, "task-123", "1" * 32)
    exhausted = reserve_antigravity_cli_turn(broker, "task-123", "2" * 32)

    assert first.allowed is True
    assert first.reservation.reserved is True
    assert duplicate.allowed is False
    assert duplicate.reason == "invocation_already_reserved"
    assert exhausted.allowed is False
    assert exhausted.reason == "external_call_budget_exhausted"
    assert broker.policy_engine.get_budget("task-123").used_external_calls == 1


def test_antigravity_turn_does_not_reserve_when_policy_denies(tmp_path):
    class Broker:
        policy_engine = PolicyEngine(AgentStateStore(tmp_path / "budget.sqlite", enabled=True))

        def authorize_auxiliary_action(self, *_args, **_kwargs):
            return {
                "success": False,
                "allowed": False,
                "requires_approval": True,
                "reason": "approval required",
            }

    broker = Broker()
    result = reserve_antigravity_cli_turn(broker, "task-123", "3" * 32)

    assert result.allowed is False
    assert result.reason == "approval_required"


def test_antigravity_cli_turn_is_unsupported_without_enforceable_cost_cap(monkeypatch, tmp_path):
    from local_ai_hub.repo_plan import host_adapters

    monkeypatch.setattr(
        host_adapters,
        "resolve_antigravity_cli",
        lambda: pytest.fail("unsupported active turn must not locate or launch the CLI"),
    )
    monkeypatch.setattr(
        host_adapters,
        "reserve_antigravity_cli_turn",
        lambda *_args: pytest.fail("call-count reservation is not a monetary cap"),
    )

    result = host_adapters.run_antigravity_cli_turn(
        command_broker=None,
        task_store=None,
        task_id="task-123",
        invocation_id="a" * 32,
        repo_root=tmp_path,
        model="gemini-4-argon-high",
        prompt="private prompt",
    )

    assert result.status is HostOperationStatus.UNSUPPORTED
    assert result.reason == "enforceable_monetary_budget_unavailable"
    assert result.response_text == ""
    assert not result.budget_reserved
