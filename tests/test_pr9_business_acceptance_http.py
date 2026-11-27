from __future__ import annotations

import json
import threading
from contextlib import closing
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_incidents import build_project_incident_record
from local_ai_hub.repo_project_memory import build_project_memory_record
from local_ai_hub.repo_project_tasks import build_project_task_record
from local_ai_hub.sqlite_support import connect_sqlite


def _post(base_url: str, path: str, payload: dict, *, dashboard: bool = False):
    headers = {
        "Content-Type": "application/json",
        "Origin": base_url,
        "Sec-Fetch-Site": "same-origin",
        "Connection": "close",
    }
    if dashboard:
        headers["X-LocalAI-Client"] = "dashboard"
    request = Request(
        f"{base_url}{path}", data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(base_url: str, path: str, params: dict):
    request = Request(f"{base_url}{path}?{urlencode(params)}", method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def test_real_http_publish_rebuild_and_read_business_state(tmp_path, monkeypatch):
    root = tmp_path / "billing-service"
    control = root / ".local-ai-hub"
    control.mkdir(parents=True)
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (control / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(root)

    records = [
        build_project_task_record(store, {
            "task_id": "task-idempotent-billing",
            "status": "in_progress",
            "contract": {
                "goal": "Prevent duplicate charges during payment retries",
                "description": "Customer retries after a slow gateway response.",
                "acceptance_criteria": ["One charge per idempotency key"],
                "non_goals": [], "constraints": ["Keep retries safe"], "risk_profile": "high",
            },
            "checkpoint": {
                "phase": "implementation", "next_action": "verify retry behavior",
                "blockers": [], "affected_paths": ["src/payments.py"],
            },
        }),
        build_project_memory_record(store, {
            "record_id": "mem-billing-retry-rule", "kind": "rule", "scope": "project",
            "key": "payment_retry_policy", "value": "Reuse the same idempotency key for every retry.",
        }),
        build_project_incident_record(store, {
            "incident_id": "inc-billing-timeout", "operation_class": "verification",
            "error_class": "TimeoutError", "signature_hash": "d2f8bc11aa33cc44",
            "resolved": False, "redacted_message": "Gateway timed out after accepting request.",
        }),
        {
            "schema_version": 1, "project_id": project_id, "kind": "business_rule",
            "id": "rule-billing-idempotency",
            "payload": {
                "title": "Prevent duplicate billing",
                "statement": "Payment retries reuse one idempotency key.",
                "layer": "intended",
            },
            "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": [],
        },
    ]
    batch = {"root": str(root), "action": "preview_batch", "records": [
        {"record": record, "expected_revision": ""} for record in records
    ]}

    state_dir = tmp_path / "hub-state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "[local_ai_hub]", "config_schema_version = 1", "", "[server]",
            'bind = "127.0.0.1"', 'state_dir = "' + state_dir.as_posix() + '"', "",
            "[security]", 'allowed_roots = ["' + tmp_path.as_posix() + '"]', "",
            "[agent_state]", "enabled = true", "", "[prewarm]", "enabled = false", "",
        ]), encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, preview = _post(base_url, "/api/repo/knowledge/manage", batch)
        assert status == 200 and preview["success"] is True

        save = {
            **batch, "action": "save_batch", "preview_digest": preview["preview_digest"],
            "operation_id": "publish-billing-v1", "apply": True,
        }
        status, denied = _post(base_url, "/api/repo/knowledge/manage", save)
        assert status == 403 and denied["success"] is False
        assert not (control / "agent-os/tasks/task-idempotent-billing.json").exists()

        status, published = _post(base_url, "/api/repo/knowledge/manage", save, dashboard=True)
        assert status == 200 and published["success"] is True
        assert len(published["file_revisions"]) == 4

        status, rebuilt = _post(base_url, "/api/repo/knowledge/manage", {
            "root": str(root), "action": "rebuild_projection",
        })
        assert status == 200 and rebuilt["success"] is True
        assert rebuilt["rebuilt"] == {"tasks": 1, "memory": 1, "incidents": 1}
        assert [item.incident_id for item in app.agent_incidents.list_incidents(root=str(root))] == [
            "inc-billing-timeout",
        ]

        status, task_result = _post(base_url, "/api/agent-state/tasks", {
            "action": "get", "root": str(root), "task_id": "task-idempotent-billing",
        })
        assert status == 200 and task_result["success"] is True, task_result
        assert task_result["task"]["status"] == "active"
        assert task_result["task"]["checkpoint"]["next_action"] == "verify retry behavior"

        status, memory_result = _get(base_url, "/api/agent-state/memory", {
            "record_id": "mem-billing-retry-rule", "scope": "repository", "root": str(root),
        })
        assert status == 200 and memory_result["success"] is True, memory_result
        assert "same idempotency key" in str(memory_result)

        status, incidents_result = _get(base_url, "/api/agent-state/incidents", {
            "root": str(root), "limit": 20,
        })
        assert status == 200 and incidents_result["success"] is True
        assert any(row["incident_id"] == "inc-billing-timeout" for row in incidents_result["incidents"])

        status, query = _post(base_url, "/api/repo/knowledge/query", {
            "root": str(root), "query": "payment retry",
        })
        assert status == 200 and query["success"] is True
        assert any(row["record"]["id"] == "rule-billing-idempotency" for row in query["records"])
        assert store.get("task", "task-idempotent-billing")["record"]["payload"]["checkpoint"]["next_action"] == "verify retry behavior"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def test_http_projection_recovery_requires_operator_and_preserves_event_history(tmp_path, monkeypatch):
    root = tmp_path / "recovery-service"
    control = root / ".local-ai-hub"
    control.mkdir(parents=True)
    project_id = "608c48ba-c68d-4551-8643-4a53b57b6510"
    (control / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    state_dir = tmp_path / "recovery-state"
    config_path = tmp_path / "recovery-config.toml"
    config_path.write_text("\n".join([
        "[local_ai_hub]", "config_schema_version = 1", "", "[server]",
        'bind = "127.0.0.1"', 'state_dir = "' + state_dir.as_posix() + '"', "",
        "[security]", 'allowed_roots = ["' + tmp_path.as_posix() + '"]', "",
        "[agent_state]", "enabled = true", "", "[prewarm]", "enabled = false", "",
    ]), encoding="utf-8")
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        task_id = "task-http-projection-recovery"
        task = app.agent_tasks.create(
            GoalContract(goal="Close monthly customer billing accurately"),
            ScopeContext(repository_id=project_id, task_id=task_id),
            task_id=task_id,
            repo_root=str(root),
        )
        with closing(connect_sqlite(app.agent_tasks.state_store.db_path)) as con:
            con.execute("DELETE FROM agent_tasks_projection WHERE task_id = ?", (task_id,))
            con.commit()
        original_events = app.agent_tasks.state_store.events(f"task:{task_id}")

        status, preview = _post(base_url, "/api/agent-state/tasks", {
            "action": "projection_restore_preview", "root": str(root), "task_id": task_id,
        })
        assert status == 200 and preview["eligible"] is True
        status, wrong_root = _post(base_url, "/api/agent-state/tasks", {
            "action": "projection_restore_preview", "root": str(tmp_path.parent), "task_id": task_id,
        })
        assert status == 403 and wrong_root["success"] is False

        restore = {
            "action": "projection_restore", "root": str(root), "task_id": task_id,
            "event_digest": preview["event_digest"],
        }
        status, restored = _post(base_url, "/api/agent-state/tasks", restore, dashboard=True)
        assert status == 200 and restored["restored"] is True
        assert app.agent_tasks.get(task_id).to_dict() == task.to_dict()
        assert app.agent_tasks.state_store.events(f"task:{task_id}") == original_events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()
