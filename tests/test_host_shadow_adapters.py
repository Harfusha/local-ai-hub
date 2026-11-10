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
    HostTokenUsage,
    HostVerificationStatus,
    _antigravity_init_matches,
    authorize_antigravity_cli_turn,
    parse_antigravity_stream_event,
    parse_codex_app_server_approval_request,
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
        "connection_status": "connected",
    }
    values.update(overrides)
    return HostCapabilitySnapshot(**values)


def test_shadow_request_rejects_usage_from_unsupported_host_surface():
    with pytest.raises(ValueError, match="unsupported for this host surface"):
        request(
            host_name="cursor",
            surface="ide",
            token_usage=HostTokenUsage(input_tokens=1),
        )


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
            connection_status="connected",
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
            json.dumps({"method": "item/started", "params": {}}),
            sequence=1, repo_root=root, expected_cli_version="0.167.0-alpha.3.2",
        )
    with pytest.raises(ValueError, match="unsupported"):
        parse_codex_app_server_notification(
            json.dumps({"method": "thread/started", "id": 1, "params": {}}),
            sequence=1, repo_root=root, expected_cli_version="0.167.0-alpha.3.2",
        )


def test_codex_token_usage_parser_keeps_only_cumulative_counts(tmp_path):
    root = tmp_path.resolve()
    line = json.dumps({
        "method": "thread/tokenUsage/updated",
        "params": {
            "threadId": "raw-thread-id",
            "turnId": "raw-turn-id",
            "tokenUsage": {
                "last": {
                    "inputTokens": 7,
                    "outputTokens": 3,
                    "cachedInputTokens": 2,
                    "reasoningOutputTokens": 1,
                    "totalTokens": 10,
                },
                "total": {
                    "inputTokens": 107,
                    "outputTokens": 23,
                    "cachedInputTokens": 32,
                    "reasoningOutputTokens": 11,
                    "totalTokens": 130,
                    "cacheWriteInputTokens": 4,
                },
            },
            "private": "must not persist",
        },
    })

    observation = parse_codex_app_server_notification(
        line,
        sequence=4,
        repo_root=root,
        expected_cli_version="0.167.0-alpha.3.2",
        expected_thread_id="raw-thread-id",
        stream_instance_id="process-one",
    )

    assert observation.event_type == "thread.token_usage.updated"
    assert observation.token_usage == HostTokenUsage(
        input_tokens=107,
        output_tokens=23,
        thinking_tokens=11,
        cache_read_tokens=32,
        total_tokens=130,
    )
    serialized = json.dumps(observation.to_dict())
    for secret in ("raw-thread-id", "raw-turn-id", "cacheWriteInputTokens", "must not persist"):
        assert secret not in serialized
    assert str(root) not in serialized
    assert observation.source_stream_ref

    store = AgentStateStore(tmp_path / "codex_token_usage.sqlite", enabled=True)
    snapshot = capability(
        host_name="codex",
        host_version="0.167.0-alpha.3.2",
        surface="app_server",
        session_type="thread",
        available_events=("thread.token_usage.updated",),
    )
    recorded = record_codex_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
        task_id="task_123",
    )
    assert recorded.status is HostOperationStatus.SHADOW_ONLY
    payload = store.events(f"host-shadow:{recorded.session_ref}")[0].payload
    assert payload["token_usage"] == {
        "input_tokens": 107,
        "output_tokens": 23,
        "thinking_tokens": 11,
        "cache_read_tokens": 32,
        "total_tokens": 130,
    }
    assert payload["token_usage_scope"] == "session_cumulative"
    assert payload["source_sequence"] == 4
    assert "raw-thread-id" not in json.dumps(payload)
    assert "raw-turn-id" not in json.dumps(payload)

    duplicate = parse_codex_app_server_notification(
        line,
        sequence=4,
        repo_root=root,
        expected_cli_version="0.167.0-alpha.3.2",
        expected_thread_id="raw-thread-id",
        stream_instance_id="process-one",
    )
    restarted = parse_codex_app_server_notification(
        line,
        sequence=4,
        repo_root=root,
        expected_cli_version="0.167.0-alpha.3.2",
        expected_thread_id="raw-thread-id",
        stream_instance_id="process-restart",
    )
    assert duplicate.event_id == observation.event_id
    assert restarted.session_ref == observation.session_ref
    assert restarted.event_id != observation.event_id
    assert restarted.source_stream_ref != observation.source_stream_ref

    with pytest.raises(ValueError, match="thread identity mismatch"):
        parse_codex_app_server_notification(
            line,
            sequence=5,
            repo_root=root,
            expected_cli_version="0.167.0-alpha.3.2",
            expected_thread_id="different-thread",
            stream_instance_id="process-one",
        )

    with pytest.raises(ValueError, match="stream instance"):
        parse_codex_app_server_notification(
            line,
            sequence=5,
            repo_root=root,
            expected_cli_version="0.167.0-alpha.3.2",
            expected_thread_id="raw-thread-id",
        )


def test_codex_turn_notification_keeps_status_and_drops_turn_content(tmp_path):
    root = tmp_path.resolve()
    line = json.dumps({
        "method": "turn/completed",
        "params": {
            "threadId": "raw-thread-id",
            "turn": {
                "id": "raw-turn-id",
                "status": "interrupted",
                "items": [{"type": "agentMessage", "text": "private turn output"}],
                "error": {"message": "private error"},
            },
        },
    })

    observation = parse_codex_app_server_notification(
        line,
        sequence=12,
        repo_root=root,
        expected_cli_version="0.167.0-alpha.3.2",
        expected_thread_id="raw-thread-id",
        stream_instance_id="process-turn-test",
    )

    assert observation.event_type == "turn.completed"
    assert observation.source_result == "interrupted"
    serialized = json.dumps(observation.to_dict())
    for secret in ("raw-thread-id", "raw-turn-id", "private turn output", "private error"):
        assert secret not in serialized

    store = AgentStateStore(tmp_path / "codex_turn_status.sqlite", enabled=True)
    snapshot = capability(
        host_name="codex",
        host_version="0.167.0-alpha.3.2",
        surface="app_server",
        session_type="thread",
        available_events=("turn.completed",),
    )
    recorded = record_codex_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
    )
    assert recorded.status is HostOperationStatus.SHADOW_ONLY
    payload = store.events(f"host-shadow:{recorded.session_ref}")[0].payload
    assert payload["source_result"] == "interrupted"
    assert payload["event_type"] == "turn.completed"
    assert "private turn output" not in json.dumps(payload)

    with pytest.raises(ValueError, match="unsupported Codex turn status"):
        parse_codex_app_server_notification(
            json.dumps({
                "method": "turn/completed",
                "params": {"threadId": "raw-thread-id", "turn": {"id": "turn", "status": "unknown", "items": []}},
            }),
            sequence=13,
            repo_root=root,
            expected_cli_version="0.167.0-alpha.3.2",
            expected_thread_id="raw-thread-id",
            stream_instance_id="process-turn-test",
        )


def test_codex_thread_status_keeps_enum_and_drops_active_flags(tmp_path):
    root = tmp_path.resolve()
    line = json.dumps({
        "method": "thread/status/changed",
        "params": {
            "threadId": "raw-thread-id",
            "status": {"type": "active", "activeFlags": ["private-approval-context"]},
        },
    })

    observation = parse_codex_app_server_notification(
        line,
        sequence=14,
        repo_root=root,
        expected_cli_version="0.167.0-alpha.3.2",
        expected_thread_id="raw-thread-id",
        stream_instance_id="process-status-test",
    )

    assert observation.event_type == "thread.status.changed"
    assert observation.source_result == "active"
    serialized = json.dumps(observation.to_dict())
    assert "raw-thread-id" not in serialized
    assert "private-approval-context" not in serialized

    store = AgentStateStore(tmp_path / "codex_thread_status.sqlite", enabled=True)
    snapshot = capability(
        host_name="codex",
        host_version="0.167.0-alpha.3.2",
        surface="app_server",
        session_type="thread",
        available_events=("thread.status.changed",),
    )
    recorded = record_codex_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
    )
    assert recorded.status is HostOperationStatus.SHADOW_ONLY
    payload = store.events(f"host-shadow:{recorded.session_ref}")[0].payload
    assert payload["source_result"] == "active"
    assert "activeFlags" not in json.dumps(payload)


def test_codex_approval_request_shadow_keeps_only_type_and_permission_check(tmp_path):
    line = json.dumps({
        "id": "private-rpc-request-id",
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": "raw-thread-id",
            "turnId": "raw-turn-id",
            "itemId": "raw-item-id",
            "startedAtMs": 1234,
            "command": "python private-source.py --secret value",
            "cwd": str(tmp_path),
            "reason": "private command reason",
        },
    })

    observation = parse_codex_app_server_approval_request(
        line,
        sequence=20,
        expected_thread_id="raw-thread-id",
        stream_instance_id="approval-process",
    )

    assert observation.event_type == "approval.command_execution.requested"
    serialized = json.dumps(observation.to_dict())
    for secret in (
        "private-rpc-request-id", "raw-thread-id", "raw-turn-id", "raw-item-id",
        "private-source.py", "secret value", str(tmp_path), "private command reason",
    ):
        assert secret not in serialized

    store = AgentStateStore(tmp_path / "codex_approval.sqlite", enabled=True)
    snapshot = capability(
        host_name="codex",
        host_version="0.167.0-alpha.3.2",
        surface="app_server",
        session_type="thread",
        available_events=("approval.command_execution.requested",),
        would_be_denied=True,
    )
    recorded = record_codex_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
    )
    assert recorded.status is HostOperationStatus.REFUSED
    assert recorded.reason == "existing_permissions_would_deny"
    assert recorded.recorded
    payload = store.events(f"host-shadow:{recorded.session_ref}")[0].payload
    assert payload["permission_check"] == {"status": "would_deny", "would_be_denied": True}
    assert payload["proposal"]["status"] == "proposed"
    assert payload["outcome"] == "simulated"
    assert "private-source.py" not in json.dumps(payload)

    with pytest.raises(ValueError, match="thread identity mismatch"):
        parse_codex_app_server_approval_request(
            line,
            sequence=21,
            expected_thread_id="different-thread",
            stream_instance_id="approval-process",
        )


@pytest.mark.parametrize(
    ("method", "params", "event_type", "private_values"),
    [
        (
            "item/fileChange/requestApproval",
            {
                "threadId": "raw-thread-id", "turnId": "raw-turn-id", "itemId": "raw-item-id",
                "startedAtMs": 1234, "grantRoot": "C:\\private\\repo", "reason": "private reason",
            },
            "approval.file_change.requested",
            ("raw-turn-id", "raw-item-id", "C:\\private\\repo", "private reason"),
        ),
        (
            "item/permissions/requestApproval",
            {
                "threadId": "raw-thread-id", "turnId": "raw-turn-id", "itemId": "raw-item-id",
                "startedAtMs": 1234, "cwd": "C:\\private\\repo", "permissions": ["network", "write"],
            },
            "approval.permissions.requested",
            ("raw-turn-id", "raw-item-id", "C:\\private\\repo", "network", "write"),
        ),
    ],
)
def test_codex_non_command_approval_requests_keep_only_event_type(
    method, params, event_type, private_values
):
    observation = parse_codex_app_server_approval_request(
        json.dumps({"id": 17, "method": method, "params": params}),
        sequence=30,
        expected_thread_id="raw-thread-id",
        stream_instance_id="approval-process",
    )

    assert observation.event_type == event_type
    serialized = json.dumps(observation.to_dict())
    for value in private_values:
        assert value not in serialized


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
            connection_status="connected",
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


@pytest.mark.parametrize(
    ("connection_status", "expected_reason"),
    [
        ("disconnected", "host_connection_lost"),
        ("unknown", "host_connection_not_verified"),
    ],
)
def test_host_connection_loss_fails_closed_without_shadow_storage(
    tmp_path, connection_status, expected_reason
):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    result = record_shadow_observation(
        request(), capability(connection_status=connection_status), store
    )

    assert result.status is HostOperationStatus.UNCERTAIN
    assert result.reason == expected_reason
    assert not result.recorded
    assert store.events(f"host-shadow:{result.session_ref}") == []


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

    observed = parse_antigravity_stream_event(
        line, sequence=4, stream_instance_id="parser-test"
    )

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
    }), sequence=0, stream_instance_id="init-test")
    result = parse_antigravity_stream_event(json.dumps({
        "event": "result",
        "result": {"conversation_id": "conv-init", "status": "SUCCESS", "response": "private response"},
    }), sequence=9, stream_instance_id="init-test")

    assert init.event_type == "session.initialized"
    assert result.event_type == "session.result.success"
    assert "C:\\private" not in json.dumps(init.to_dict())
    assert "run_command" not in json.dumps(init.to_dict())
    assert "private response" not in json.dumps(result.to_dict())


def test_antigravity_usage_counters_are_sanitized_shadow_metadata(tmp_path):
    usage = {
        "input_tokens": 12,
        "output_tokens": 5,
        "thinking_tokens": 2,
        "cache_read_tokens": 7,
        "total_tokens": 19,
        "raw_payload": "sensitive usage text",
    }
    expected_counters = {key: value for key, value in usage.items() if key != "raw_payload"}
    observation = parse_antigravity_stream_event(json.dumps({
        "event": "result",
        "result": {
            "conversation_id": "conversation-secret",
            "status": "SUCCESS",
            "response": "private response",
            "usage": usage,
        },
    }), sequence=10, stream_instance_id="usage-test")

    assert observation.token_usage.to_dict() == expected_counters
    assert "conversation-secret" not in json.dumps(observation.to_dict())
    assert "private response" not in json.dumps(observation.to_dict())
    assert "sensitive usage text" not in json.dumps(observation.to_dict())

    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    snapshot = capability(
        host_name="antigravity",
        host_version="1.4.12",
        surface="cli_stream_json",
        session_type="conversation",
        available_events=("session.result.success",),
        available_commands=(),
        available_permissions=(),
        permission_mode="request-review",
        permissions_verified=False,
        verification_status=HostVerificationStatus.VERIFIED,
    )
    recorded = record_antigravity_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=snapshot,
        event_store=store,
        task_id="task_123",
    )

    assert recorded.status is HostOperationStatus.SHADOW_ONLY
    event = store.events(f"host-shadow:{recorded.session_ref}")[0]
    assert event.kind == "host.shadow.observation.v2"
    payload = event.payload
    assert payload["schema"] == "local-ai-hub.host-shadow-observation.v2"
    assert payload["token_usage"] == expected_counters
    assert payload["token_usage_scope"] == "session_cumulative"
    serialized = json.dumps(payload)
    assert "conversation-secret" not in serialized
    assert "private response" not in serialized
    assert "sensitive usage text" not in serialized


@pytest.mark.parametrize("bad_value", [True, -1, 1.5, "12", 2**53])
def test_antigravity_usage_rejects_invalid_token_counts(bad_value):
    line = json.dumps({
        "event": "result",
        "result": {
            "conversation_id": "conversation-secret",
            "status": "SUCCESS",
            "usage": {"input_tokens": bad_value},
        },
    })

    with pytest.raises(ValueError, match="token usage"):
        parse_antigravity_stream_event(
            line, sequence=10, stream_instance_id="invalid-usage-test"
        )


def test_antigravity_usage_preserves_zero_without_filling_missing_counters():
    observed = parse_antigravity_stream_event(json.dumps({
        "event": "result",
        "result": {
            "conversation_id": "conversation-secret",
            "status": "SUCCESS",
            "usage": {"input_tokens": 0},
        },
    }), sequence=10, stream_instance_id="usage-stream")

    assert observed.token_usage.to_dict() == {"input_tokens": 0}


def test_antigravity_stream_restart_separates_events_but_keeps_session(tmp_path):
    line = json.dumps({
        "event": "result",
        "result": {
            "conversation_id": "conversation-secret",
            "status": "SUCCESS",
            "response": "private response",
            "usage": {"input_tokens": 120, "total_tokens": 145},
        },
    })
    first = parse_antigravity_stream_event(
        line, sequence=8, stream_instance_id="process-first"
    )
    duplicate = parse_antigravity_stream_event(
        line, sequence=8, stream_instance_id="process-first"
    )
    restarted = parse_antigravity_stream_event(
        line, sequence=8, stream_instance_id="process-restart"
    )

    assert first.session_ref == restarted.session_ref
    assert first.event_id == duplicate.event_id
    assert first.event_id != restarted.event_id
    assert first.source_stream_ref != restarted.source_stream_ref

    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    snapshot = capability(
        host_name="antigravity",
        host_version="1.4.12",
        surface="cli_stream_json",
        session_type="conversation",
        available_events=("session.result.success",),
        available_commands=(),
        available_permissions=(),
        permissions_verified=False,
        verification_status=HostVerificationStatus.VERIFIED,
    )
    recorded_session_ref = None
    for observation in (first, restarted):
        result = record_antigravity_shadow_event(
            observation,
            repository_id="a" * 64,
            capability=snapshot,
            event_store=store,
        )
        assert result.status is HostOperationStatus.SHADOW_ONLY
        assert result.session_ref is not None
        if recorded_session_ref is None:
            recorded_session_ref = result.session_ref
        else:
            assert result.session_ref == recorded_session_ref

    events = store.events(f"host-shadow:{recorded_session_ref}")
    assert len(events) == 2
    assert {event.payload["source_sequence"] for event in events} == {8}
    assert len({event.payload["source_stream_ref"] for event in events}) == 2
    serialized = json.dumps([event.payload for event in events])
    assert "process-first" not in serialized
    assert "process-restart" not in serialized
    assert "conversation-secret" not in serialized
    assert "private response" not in serialized


def test_antigravity_stream_observation_uses_shared_shadow_gate(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    observation = parse_antigravity_stream_event(json.dumps({
        "event": "init",
        "conversation_id": "conversation-secret",
        "init": {"cwd": "C:\\private", "tools": ["run_command"], "permission_mode": "request-review"},
    }), sequence=0, stream_instance_id="sink-test")
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
        parse_antigravity_stream_event(
            line, sequence=sequence, stream_instance_id="invalid-event-test"
        )


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


def test_antigravity_post_tool_use_parser_discards_private_hook_fields(tmp_path):
    from local_ai_hub.repo_plan import host_adapters

    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "PRIVATE COMMAND", "Cwd": str(tmp_path)},
        },
        "stepIdx": 7,
        "error": "PRIVATE ERROR",
        "conversationId": "raw-antigravity-conversation",
        "workspacePaths": [str(tmp_path)],
        "transcriptPath": str(tmp_path / "transcript.jsonl"),
        "artifactDirectoryPath": str(tmp_path / "brain"),
        "modelName": "private-model-name",
    }

    observation = host_adapters.parse_antigravity_post_tool_use_event(
        payload,
        expected_conversation_id="raw-antigravity-conversation",
        expected_workspace_root=tmp_path,
    )

    assert observation.host_name == "antigravity"
    assert observation.surface == "antigravity_post_tool_use"
    assert observation.session_type == "conversation"
    assert observation.event_type == "tool.failed"
    assert observation.sequence == 7
    assert observation.verification_status is HostVerificationStatus.NOT_VERIFIED
    serialized = json.dumps(observation.to_dict())
    for private_value in (
        "raw-antigravity-conversation",
        "PRIVATE COMMAND",
        "PRIVATE ERROR",
        str(tmp_path),
        "transcript.jsonl",
        "private-model-name",
    ):
        assert private_value not in serialized

    duplicate = host_adapters.parse_antigravity_post_tool_use_event(
        payload,
        expected_conversation_id="raw-antigravity-conversation",
        expected_workspace_root=tmp_path,
    )
    next_step = dict(payload)
    next_step["stepIdx"] = 8
    following = host_adapters.parse_antigravity_post_tool_use_event(
        next_step,
        expected_conversation_id="raw-antigravity-conversation",
        expected_workspace_root=tmp_path,
    )
    assert duplicate.event_id == observation.event_id
    assert following.session_ref == observation.session_ref
    assert following.event_id != observation.event_id


def test_antigravity_post_tool_use_parser_rejects_unbound_conversation_or_workspace(tmp_path):
    from local_ai_hub.repo_plan import host_adapters

    payload = {
        "toolCall": {"name": "run_command", "args": {}},
        "stepIdx": 3,
        "conversationId": "another-conversation",
        "workspacePaths": [str(tmp_path)],
    }
    with pytest.raises(ValueError, match="conversation identity mismatch"):
        host_adapters.parse_antigravity_post_tool_use_event(
            payload,
            expected_conversation_id="expected-conversation",
            expected_workspace_root=tmp_path,
        )

    payload["conversationId"] = "expected-conversation"
    outside = tmp_path / "outside"
    outside.mkdir()
    payload["workspacePaths"] = [str(outside)]
    with pytest.raises(ValueError, match="workspace identity mismatch"):
        host_adapters.parse_antigravity_post_tool_use_event(
            payload,
            expected_conversation_id="expected-conversation",
            expected_workspace_root=tmp_path,
        )


def test_antigravity_post_tool_use_shadow_uses_shared_fail_closed_gate(tmp_path):
    from local_ai_hub.repo_plan import host_adapters

    payload = {
        "toolCall": {"name": "run_command", "args": {"secret": "PRIVATE ARG"}},
        "stepIdx": 9,
        "conversationId": "raw-antigravity-conversation",
        "workspacePaths": [str(tmp_path)],
    }
    observation = host_adapters.parse_antigravity_post_tool_use_event(
        payload,
        expected_conversation_id="raw-antigravity-conversation",
        expected_workspace_root=tmp_path,
    )
    store = AgentStateStore(tmp_path / "agent_state.sqlite", enabled=True)
    unverified = capability(
        host_name="antigravity",
        host_version="1.4.12",
        surface="antigravity_post_tool_use",
        session_type="conversation",
        available_events=("tool.completed", "tool.failed"),
        verification_status=HostVerificationStatus.NOT_VERIFIED,
        permissions_verified=False,
        hub_managed=True,
        connection_status="connected",
    )

    refused = host_adapters.record_antigravity_hook_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=unverified,
        event_store=store,
    )
    assert refused.status is HostOperationStatus.UNCERTAIN
    assert not refused.recorded
    assert store.events(f"host-shadow:{refused.session_ref}") == []

    verified = capability(
        host_name="antigravity",
        host_version="1.4.12",
        surface="antigravity_post_tool_use",
        session_type="conversation",
        available_events=("tool.completed", "tool.failed"),
        verification_status=HostVerificationStatus.VERIFIED,
        permissions_verified=False,
        hub_managed=True,
        connection_status="connected",
    )
    recorded = host_adapters.record_antigravity_hook_shadow_event(
        observation,
        repository_id="a" * 64,
        capability=verified,
        event_store=store,
    )
    assert recorded.status is HostOperationStatus.SHADOW_ONLY
    assert recorded.recorded and not recorded.duplicate
    payload = store.events(f"host-shadow:{recorded.session_ref}")[0].payload
    assert payload["permission_check"] == {
        "status": "not_evaluated",
        "would_be_denied": None,
    }
    assert payload["content_stored"] is False
    serialized = json.dumps(payload)
    assert "PRIVATE ARG" not in serialized
    assert "raw-antigravity-conversation" not in serialized
