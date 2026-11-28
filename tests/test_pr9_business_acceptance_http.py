from __future__ import annotations

import json
import threading
from contextlib import closing
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_incidents import ToolOutcome
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord
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
    import subprocess

    (control / ".gitignore").write_text("local/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "--quiet"], check=True, timeout=15)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "add", "."], check=True, timeout=15)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "bootstrap"],
                   check=True, timeout=15)
    initial_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True,
        text=True, timeout=15,
    ).stdout.strip()
    store = RepoKnowledgeStore(root)

    records = [
        build_project_task_record(store, {
            "task_id": "task-idempotent-billing",
            "status": "active",
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
        ordinary_contract = {
            "goal": "Keep billing retries idempotent", "description": "",
            "acceptance_criteria": ["Only one charge is created per request key"],
            "non_goals": [], "constraints": [], "risk_profile": "normal",
        }
        status, ordinary_task = _post(base_url, "/api/agent-state/tasks", {
            "action": "create", "root": str(root), "repo_root": str(root),
            "task_id": "task-ordinary-billing",
            "context": {"session_id": "private-session-should-stay-local"},
            "contract": ordinary_contract,
        })
        assert status == 200 and ordinary_task["success"] is True, ordinary_task
        canonical_task = control / "agent-os/tasks/task-ordinary-billing.json"
        assert canonical_task.is_file(), "ordinary task creation must publish its durable contract to Git"
        canonical_text = canonical_task.read_text(encoding="utf-8")
        assert "Keep billing retries idempotent" in canonical_text
        assert '"lease_id"' not in canonical_text and '"verification_receipts"' not in canonical_text
        assert "private-session-should-stay-local" not in canonical_text and str(root) not in canonical_text
        status, replayed_task = _post(base_url, "/api/agent-state/tasks", {
            "action": "create", "root": str(root), "repo_root": str(root),
            "task_id": "task-ordinary-billing", "contract": ordinary_contract,
        })
        assert status == 200 and replayed_task["success"] is True, replayed_task

        from concurrent.futures import ThreadPoolExecutor

        concurrent_create = {
            "action": "create", "root": str(root), "repo_root": str(root),
            "task_id": "task-concurrent-billing", "contract": ordinary_contract,
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_results = list(executor.map(
                lambda _: _post(base_url, "/api/agent-state/tasks", concurrent_create),
                range(2),
            ))
        assert all(status == 200 and result["success"] is True for status, result in concurrent_results), concurrent_results
        assert (control / "agent-os/tasks/task-concurrent-billing.json").is_file()
        assert subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True,
            text=True, timeout=15,
        ).stdout.strip() == initial_head
        assert subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet"], timeout=15).returncode == 0

        old_root = tmp_path / "pre-v4-checkout"
        old_control = old_root / ".local-ai-hub"
        old_control.mkdir(parents=True)
        (old_control / ".gitignore").write_text("local/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(old_root), "init", "--quiet"], check=True, timeout=15)
        subprocess.run(["git", "-C", str(old_root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "add", "."], check=True, timeout=15)
        subprocess.run(["git", "-C", str(old_root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "old checkout"],
                       check=True, timeout=15)
        bootstrap = {
            "action": "bootstrap", "root": str(old_root),
            "project_id": "53e9f982-49f9-4a49-98fb-59491a38f140", "mode": "shared",
            "operation_id": "bootstrap-http-old-checkout", "apply": True,
        }
        status, denied_bootstrap = _post(base_url, "/api/repo/knowledge/manage", bootstrap)
        assert status == 403 and denied_bootstrap["success"] is False
        assert not (old_control / "project.json").exists()
        status, bootstrapped = _post(base_url, "/api/repo/knowledge/manage", bootstrap, dashboard=True)
        assert status == 200 and bootstrapped["success"] is True
        status, retried_bootstrap = _post(base_url, "/api/repo/knowledge/manage", bootstrap, dashboard=True)
        assert status == 200 and retried_bootstrap["success"] is True

        uninitialized_root = tmp_path / "uninitialized-project"
        uninitialized_control = uninitialized_root / ".local-ai-hub"
        uninitialized_control.mkdir(parents=True)
        (uninitialized_control / ".gitignore").write_text("local/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(uninitialized_root), "init", "--quiet"], check=True, timeout=15)
        subprocess.run(["git", "-C", str(uninitialized_root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "add", "."], check=True, timeout=15)
        subprocess.run(["git", "-C", str(uninitialized_root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "uninitialized"],
                       check=True, timeout=15)
        status, uninitialized_task = _post(base_url, "/api/agent-state/tasks", {
            "action": "create", "root": str(uninitialized_root), "repo_root": str(uninitialized_root),
            "task_id": "task-uninitialized-project", "contract": {
                "goal": "No project task before stable identity", "description": "",
                "acceptance_criteria": ["No SQLite-only project task"],
                "non_goals": [], "constraints": [], "risk_profile": "normal",
            },
        })
        assert status == 400 and uninitialized_task["success"] is False
        assert "stable project_id" in uninitialized_task["error"]
        assert not app.agent_tasks.has_task("task-uninitialized-project")

        readonly_root = tmp_path / "readonly-project"
        readonly_control = readonly_root / ".local-ai-hub"
        readonly_control.mkdir(parents=True)
        (readonly_control / ".gitignore").write_text("local/\n", encoding="utf-8")
        (readonly_control / "project.json").write_text(json.dumps({
            "schema_version": 1, "project_id": "86d64932-5af8-4541-9fa6-62a38bc8c55f",
            "mode": "read_only",
        }), encoding="utf-8")
        subprocess.run(["git", "-C", str(readonly_root), "init", "--quiet"], check=True, timeout=15)
        subprocess.run(["git", "-C", str(readonly_root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "add", "."], check=True, timeout=15)
        subprocess.run(["git", "-C", str(readonly_root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "read-only"],
                       check=True, timeout=15)
        status, readonly_task = _post(base_url, "/api/agent-state/tasks", {
            "action": "create", "root": str(readonly_root), "repo_root": str(readonly_root),
            "task_id": "task-readonly-project", "contract": {
                "goal": "Do not publish into read-only project", "description": "",
                "acceptance_criteria": ["Write is denied"],
                "non_goals": [], "constraints": [], "risk_profile": "normal",
            },
        })
        assert status == 200 and readonly_task["success"] is True, readonly_task
        assert app.agent_tasks.has_task("task-readonly-project")
        assert not (readonly_control / "agent-os/tasks/task-readonly-project.json").exists()

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
        assert rebuilt["rebuilt"] == {"tasks": 3, "memory": 1, "incidents": 1}
        assert [item.incident_id for item in app.agent_incidents.list_incidents(root=str(root))] == [
            "inc-billing-timeout",
        ]

        status, task_result = _post(base_url, "/api/agent-state/tasks", {
            "action": "get", "root": str(root), "task_id": "task-idempotent-billing",
        })
        assert status == 200 and task_result["success"] is True, task_result
        assert task_result["task"]["status"] == "active"
        assert task_result["task"]["checkpoint"]["next_action"] == "verify retry behavior"
        status, ordinary_result = _post(base_url, "/api/agent-state/tasks", {
            "action": "get", "root": str(root), "task_id": "task-ordinary-billing",
        })
        assert status == 200 and ordinary_result["success"] is True
        assert ordinary_result["task"]["contract"]["goal"] == "Keep billing retries idempotent"

        status, memory_result = _get(base_url, "/api/agent-state/memory", {
            "record_id": "mem-billing-retry-rule", "scope": "repository", "root": str(root),
        })
        assert status == 200 and memory_result["success"] is True, memory_result
        assert "same idempotency key" in str(memory_result)

        status, unstated_scope_write = _post(base_url, "/api/agent-state/memory", {
            "action": "record", "root": str(root),
            "record": {"kind": "fact", "key": "must-not-infer-repository", "value": "no direct write"},
        })
        assert status == 409 and unstated_scope_write["success"] is False

        status, legacy_write = _post(base_url, "/api/agent-state/memory", {
            "action": "record", "root": str(root), "scope": "repository",
            "record": {
                "kind": "fact", "scope": "repository", "key": "must-use-git",
                "value": "Repository facts require reviewed Git publication.",
            },
        })
        assert status == 409 and legacy_write["success"] is False, legacy_write
        with closing(connect_sqlite(app.agent_state.db_path, read_only=True)) as con:
            assert con.execute(
                "SELECT COUNT(*) FROM agent_memory_records WHERE key = ?", ("must-use-git",)
            ).fetchone()[0] == 0
        status, repository_delete = _post(base_url, "/api/agent-state/memory", {
            "action": "delete", "root": str(root), "scope": "repository",
            "record_id": "mem-billing-retry-rule",
        })
        assert status == 409 and repository_delete["success"] is False
        status, memory_result = _get(base_url, "/api/agent-state/memory", {
            "record_id": "mem-billing-retry-rule", "scope": "repository", "root": str(root),
        })
        assert status == 200 and memory_result["success"] is True, memory_result

        status, legacy_incident = _post(base_url, "/api/agent-state/incidents", {
            "action": "record", "root": str(root), "message": "unreviewed incident write",
            "operation_class": "test", "state_revision": "fixture-rev",
        })
        assert status == 403 and legacy_incident["success"] is False

        status, incidents_result = _get(base_url, "/api/agent-state/incidents", {
            "root": str(root), "limit": 20,
        })
        assert status == 200 and incidents_result["success"] is True
        assert any(row["incident_id"] == "inc-billing-timeout" for row in incidents_result["incidents"])
        legacy_only = app.agent_memory.record(MemoryRecord.create(
            kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY,
            scope_id=project_id, key="legacy-only-key", value="SQLite-only secret",
            provenance={"root": str(root), "repository_id": project_id},
        ), actor="test")
        legacy_incident = app.agent_incidents.capture(ToolOutcome(
            tool_name="command", error="SQLite-only failure", exit_code=1,
            repository_root=str(root),
        ))
        assert legacy_only is not None and legacy_incident is not None
        status, memory_search = _get(base_url, "/api/agent-state/memory", {
            "scope": "repository", "root": str(root), "query": "legacy-only-key",
        })
        assert status == 200 and memory_search["records"] == []
        status, incident_recheck = _get(base_url, "/api/agent-state/incidents", {
            "root": str(root), "limit": 20,
        })
        assert status == 200 and all(
            row["incident_id"] != legacy_incident.incident_id
            for row in incident_recheck["incidents"]
        )

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
            GoalContract(goal="Close monthly customer billing accurately", acceptance_criteria=["Billing state is reconciled"]),
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
