"""Behavioral acceptance for selected HubClient HTTP target operations."""

import json

import pytest

from local_ai_hub.client import HubClient


@pytest.fixture
def fake_http_transport(tmp_path):
    config_path = tmp_path / "missing-hub.toml"
    config_path.write_text(
        "[security]\n"
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n',
        encoding="utf-8",
    )
    captured = []
    state = {"response": {"success": True, "operation": "accepted"}}

    def open_request(method, path, body, headers, timeout):
        captured.append(
            {
                "method": method,
                "path": path,
                "payload": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        return json.dumps(state["response"]).encode("utf-8")

    return {"captured": captured, "state": state, "open": open_request}


def test_client_create_task_targets_agent_state_tasks(tmp_path, monkeypatch, fake_http_transport):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "task_id": "task-17"}
    fake_http_transport["state"]["response"] = reply

    result = client.create_task(
        "Verify target mapping",
        acceptance_criteria=["route and payload match"],
        task_id="task-17",
        scope="task",
        root=str(tmp_path),
    )

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/agent-state/tasks",
            "payload": {
                "action": "create",
                "goal": "Verify target mapping",
                "acceptance_criteria": ["route and payload match"],
                "task_id": "task-17",
                "scope": "task",
                "root": str(tmp_path),
            },
        }
    ]


def test_client_context_compile_targets_agent_state_context(
    tmp_path, monkeypatch, fake_http_transport
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "context_id": "ctx-17"}
    fake_http_transport["state"]["response"] = reply

    result = client.context_compile(
        "task-17", token_budget=1200, changed_paths=["src/a.py"], since_hash="abc", compact=True
    )

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/agent-state/context",
            "payload": {
                "action": "compile",
                "task_id": "task-17",
                "token_budget": 1200,
                "changed_paths": ["src/a.py"],
                "compact": True,
                "since_hash": "abc",
            },
        }
    ]


def test_client_verify_receipt_targets_agent_state_verification(
    tmp_path, monkeypatch, fake_http_transport
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "receipt_id": "receipt-17"}
    fake_http_transport["state"]["response"] = reply

    result = client.verify_receipt(
        "task-17",
        "route assertion",
        passed=False,
        command_id="cmd-17",
        evidence_id="ev-17",
        details={"source": "acceptance"},
    )

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/agent-state/verification",
            "payload": {
                "action": "receipt",
                "receipt": {
                    "task_id": "task-17",
                    "criterion": "route assertion",
                    "passed": False,
                    "command_id": "cmd-17",
                    "evidence_id": "ev-17",
                    "details": {"source": "acceptance"},
                },
            },
        }
    ]


def test_client_record_memory_targets_agent_state_memory(
    tmp_path, monkeypatch, fake_http_transport
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "record_id": "memory-17"}
    fake_http_transport["state"]["response"] = reply

    result = client.record_memory(
        "decision-17", {"choice": "bounded"}, scope="task", kind="fact",
        task_id="task-17", root=str(tmp_path)
    )

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/agent-state/memory",
            "payload": {
                "action": "record",
                "key": "decision-17",
                "value": {"choice": "bounded"},
                "scope": "task",
                "kind": "fact",
                "task_id": "task-17",
                "root": str(tmp_path),
            },
        }
    ]


def test_client_incident_decision_targets_agent_state_incidents(
    tmp_path, monkeypatch, fake_http_transport
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "revision": "rev-18"}
    fake_http_transport["state"]["response"] = reply

    result = client.coord(
        "incident_decision",
        root=str(tmp_path),
        fingerprint={"error_class": "AssertionError", "operation_class": "test", "signature_hash": "case-17"},
        state_revision="rev-17",
    )

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/agent-state/incidents",
            "payload": {
                "action": "decision",
                "root": str(tmp_path),
                "fingerprint": {
                    "error_class": "AssertionError", "operation_class": "test", "signature_hash": "case-17"
                },
                "state_revision": "rev-17",
            },
        }
    ]


def test_client_worktree_lease_targets_coord_worktree_lease(
    tmp_path, monkeypatch, fake_http_transport
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "lease_id": "lease-17"}
    fake_http_transport["state"]["response"] = reply

    result = client.coord("worktree_lease", root="C:/repo", branch="feature/t01")

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/coord/worktree_lease",
            "payload": {"root": "C:/repo", "branch": "feature/t01"},
        }
    ]


def test_client_complexity_targets_repo_complexity(tmp_path, monkeypatch, fake_http_transport):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "modules": 3}
    fake_http_transport["state"]["response"] = reply

    result = client.complexity(root="C:/repo", path="src/module.py", max_results=7)

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/repo/complexity",
            "payload": {"root": "C:/repo", "path": "src/module.py", "max_results": 7},
        }
    ]


def test_client_package_audit_returns_target_error(tmp_path, monkeypatch, fake_http_transport):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": False, "error": "lockfile unsupported", "status_code": 422}
    fake_http_transport["state"]["response"] = reply

    result = client.package_audit(root="C:/repo", lockfile_path="pnpm-lock.yaml")

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/repo/package_audit",
            "payload": {"root": "C:/repo", "lockfile_path": "pnpm-lock.yaml"},
        }
    ]


@pytest.mark.parametrize("method", ["mock_server", "flaky_detect"])
def test_retired_command_sdk_helpers_do_not_send_requests(
    tmp_path, monkeypatch, fake_http_transport, method
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    with pytest.raises(AttributeError):
        getattr(client, method)
    assert fake_http_transport["captured"] == []


def test_client_ingest_diagram_targets_rag_artifact_operation(
    tmp_path, monkeypatch, fake_http_transport
):
    client = HubClient(
        config_path=str(tmp_path / "missing-hub.toml"),
        auto_start=False,
    )
    monkeypatch.setattr(client, "_pooled_open", fake_http_transport["open"])
    reply = {"success": True, "document_id": "diagram-17"}
    fake_http_transport["state"]["response"] = reply

    result = client.ingest_diagram(
        workspace="design-system",
        image_path="diagrams/system.svg",
        caption="Service topology",
        metadata={"task_id": "task-17"},
    )

    assert result == reply
    assert fake_http_transport["captured"] == [
        {
            "method": "POST",
            "path": "/api/rag/ingest_diagram",
            "payload": {
                "workspace": "design-system",
                "image_path": "diagrams/system.svg",
                "caption": "Service topology",
                "metadata": {"task_id": "task-17"},
            },
        }
    ]
