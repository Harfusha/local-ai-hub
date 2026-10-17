from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import types
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode

import pytest

from local_ai_hub import http_server
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus
from local_ai_hub.app import LocalAIApp


def test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    state_dir.mkdir()
    repo_a.mkdir()
    repo_b.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39131\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n\n[security]\napi_token_tenant = \"codex\"\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    project_config = types.ModuleType("local_ai_hub.project_config")

    def resolve_project_context(root, configured_dir):
        resolved_root = Path(root).expanduser().resolve(strict=True)
        return types.SimpleNamespace(root=resolved_root, coordination_id=resolved_root.name)

    project_config.resolve_project_context = resolve_project_context
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)
    global_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="global-http-tenant",
        value="shared global value",
        provenance={"root": str(repo_a), "repository_id": "repo-a"},
    )
    app.agent_memory.record(global_record, actor="user")
    session_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        key="session-http-tenant",
        value="private session value",
        provenance={"tenant": "codex"},
    )
    app.agent_memory.record(session_record, actor="user")
    owned_global_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="tenant-owned-global-http",
        value="private global value",
        provenance={"root": str(repo_a), "repository_id": "repo-a", "tenant": "owner-tenant"},
    )
    app.agent_memory.record(owned_global_record, actor="user")
    authenticated_global_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="authenticated-global-http-delete",
        value="tenant-owned global value",
        provenance={"root": str(repo_a), "repository_id": "repo-a", "tenant": "codex"},
    )
    app.agent_memory.record(authenticated_global_record, actor="user")

    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Tenant": "codex",
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        global_payload = {
            "action": "get",
            "record_id": global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
            "tenant": "codex",
        }
        status, found = post(global_payload)
        assert status == 200
        assert found["record"]["record_id"] == global_record.record_id

        wrong_root = {**global_payload, "root": str(repo_b)}
        status, denied_root = post(wrong_root)
        assert status == 404
        assert denied_root["success"] is False

        session_payload = {
            "action": "get",
            "record_id": session_record.record_id,
            "scope": "session",
            "scope_id": "session-codex",
            "tenant": "other-tenant",
        }
        status, denied_tenant = post(session_payload)
        assert status == 403
        assert denied_tenant["error_code"] == "tenant_binding_mismatch"

        owned_global_payload = {
            "record_id": owned_global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
            "tenant": "codex",
        }
        status, denied_owned_global = post({**owned_global_payload, "action": "get"})
        assert status == 404
        assert denied_owned_global["success"] is False
        status, found_owned_global = post({**owned_global_payload, "action": "get", "tenant": "owner-tenant"})
        assert status == 403
        assert found_owned_global["success"] is False

        authenticated_delete = {
            "action": "delete",
            "record_id": authenticated_global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
            "tenant": "codex",
        }
        status, deleted_authenticated_global = post(authenticated_delete)
        assert status == 200
        assert deleted_authenticated_global["deleted"] is True

        delete_payload = {
            "action": "delete",
            "record_id": global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
            "tenant": "codex",
        }
        status, denied_delete = post({**delete_payload, "root": str(repo_b)})
        assert status == 404
        assert denied_delete["success"] is False
        with closing(sqlite3.connect(app.agent_memory.state_store.db_path)) as con:
            row = con.execute(
                "SELECT 1 FROM agent_memory_records WHERE record_id = ?",
                (global_record.record_id,),
            ).fetchone()
        assert row is not None

        original_delete = app.agent_memory.delete
        rewritten = False

        def reassign_identity_before_delete(*args, **kwargs):
            nonlocal rewritten
            if not rewritten and args[0] == global_record.record_id and kwargs.get("root") == str(repo_a):
                reassigned_provenance = dict(global_record.provenance)
                reassigned_provenance.update({"root": str(repo_b), "repository_id": "repo-b"})
                with closing(sqlite3.connect(app.agent_memory.state_store.db_path)) as con:
                    con.execute(
                        "UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?",
                        (json.dumps(reassigned_provenance), global_record.record_id),
                    )
                    con.commit()
                rewritten = True
            return original_delete(*args, **kwargs)

        monkeypatch.setattr(app.agent_memory, "delete", reassign_identity_before_delete)
        status, stale_identity_delete = post(delete_payload)
        assert rewritten is True
        assert status == 404
        assert stale_identity_delete["success"] is False
        monkeypatch.setattr(app.agent_memory, "delete", original_delete)
        assert app.agent_memory.get(
            global_record.record_id,
            scope=AgentScope.GLOBAL,
            root=str(repo_b),
            repository_id="repo-b",
        ) is not None
        with closing(sqlite3.connect(app.agent_memory.state_store.db_path)) as con:
            con.execute(
                "UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?",
                (json.dumps(global_record.provenance), global_record.record_id),
            )
            con.commit()

        status, deleted = post(delete_payload)
        assert status == 200
        assert deleted["deleted"] is True
        assert app.agent_memory.get(global_record.record_id) is None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identity(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    repo_a = tmp_path / "repo-a"
    state_dir.mkdir()
    repo_a.mkdir()
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39132\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n\n[security]\napi_token_tenant = \"attacker\"\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    use_real_store = hasattr(app.agent_memory.state_store, "append_in_transaction")
    if os.environ.get("T05_OVERLAY_SOURCE"):
        import local_ai_hub.agent_events as agent_events

        overlay_source = Path(os.environ["T05_OVERLAY_SOURCE"]).resolve()
        root_source = Path(os.environ["T05_ROOT_SOURCE"]).resolve()
        assert Path(http_server.__file__).resolve() == overlay_source / "local_ai_hub" / "http_server.py"
        assert Path(sys.modules["local_ai_hub.agent_memory"].__file__).resolve() == overlay_source / "local_ai_hub" / "agent_memory.py"
        assert Path(sys.modules["local_ai_hub.app"].__file__).resolve() == root_source / "src" / "local_ai_hub" / "app.py"
        assert Path(agent_events.__file__).resolve() == root_source / "src" / "local_ai_hub" / "agent_events.py"
    project_resolutions = []
    project_config = types.ModuleType("local_ai_hub.project_config")

    def resolve_project_context(root, configured_dir):
        resolved_root = Path(root).expanduser().resolve(strict=True)
        resolved_state = Path(configured_dir).expanduser().resolve()
        project_resolutions.append((resolved_root, resolved_state))
        return types.SimpleNamespace(
            root=resolved_root,
            coordination_id=f"server-{resolved_root.name}",
        )

    project_config.resolve_project_context = resolve_project_context
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    class MemoryHarness:
        def __init__(self):
            self.state_store = types.SimpleNamespace(enabled=True)
            self.records = []

        def _matches(self, record, filters):
            if filters.get("record_id") and record.record_id != filters["record_id"]:
                return False
            if filters.get("scope") is not None and record.scope is not filters["scope"]:
                return False
            if filters.get("scope_id") is not None and record.scope_id != filters["scope_id"]:
                return False
            for identity_key in (
                "root", "repository_id", "tenant", "task_id", "session_id",
                "clone_id", "worktree_id", "branch",
            ):
                expected = filters.get(identity_key)
                if expected is not None and record.provenance.get(identity_key) != expected:
                    return False
            return filters.get("key") is None or record.key == filters["key"]

        def record(self, record, **_kwargs):
            self.records.append(record)
            return record

        def find(self, **filters):
            limit = filters.pop("limit", 100)
            return [record for record in self.records if self._matches(record, filters)][:limit]

        def get(self, record_id, **filters):
            matches = self.find(record_id=record_id, limit=1, **filters)
            return matches[0] if matches else None

        def delete(self, record_id, **filters):
            record = self.get(record_id, **filters)
            if record is None:
                return False
            self.records.remove(record)
            return True

    previous_memory = app.agent_memory
    memory = app.agent_memory if use_real_store else MemoryHarness()
    app.agent_memory = memory

    def record(key, *, repository_id, tenant):
        saved = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.GLOBAL,
            key=key,
            value=f"private value for {key}",
            provenance={
                "root": str(repo_a),
                "repository_id": repository_id,
                "tenant": tenant,
            },
        )
        if use_real_store:
            return memory.record(saved, actor="user")
        memory.records.append(saved)
        return saved

    victim = record("private-tenant-record", repository_id="server-repo-a", tenant="victim")
    spoofed_repository = record(
        "private-repository-record", repository_id="client-repository", tenant="attacker"
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, *, tenant="attacker", query=None, payload=None):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory"
        if query:
            url += "?" + urlencode(query)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"X-LocalAI-Tenant": tenant, "Connection": "close"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        call = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(call) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        status, denied_get = request(
            "GET",
            query={
                "record_id": victim.record_id,
                "scope": "global",
                "root": str(repo_a),
                "repository_id": "server-repo-a",
                "tenant": "victim",
            },
        )
        assert status == 404
        assert denied_get["success"] is False

        status, unresolved_project = request(
            "GET",
            query={
                "record_id": victim.record_id,
                "scope": "global",
                "root": str(tmp_path / "missing-project"),
                "repository_id": "server-repo-a",
                "tenant": "victim",
            },
        )
        assert status == 403
        assert unresolved_project["success"] is False

        status, denied_find = request(
            "GET",
            query={
                "scope": "global",
                "root": str(repo_a),
                "repository_id": "client-repository",
                "tenant": "attacker",
                "key": "private-repository-record",
            },
        )
        assert status == 200
        assert denied_find["records"] == []

        status, denied_post_find = request(
            "POST",
            payload={
                "action": "find",
                "scope": "global",
                "root": str(repo_a),
                "repository_id": "client-repository",
                "tenant": "attacker",
                "key": "private-repository-record",
            },
        )
        assert status == 200
        assert denied_post_find["records"] == []

        status, denied_post_get = request(
            "POST",
            payload={
                "action": "get",
                "record_id": victim.record_id,
                "scope": "global",
                "root": str(repo_a),
                "repository_id": "server-repo-a",
                "tenant": "victim",
            },
        )
        assert status == 403
        assert denied_post_get["success"] is False

        status, created = request(
            "POST",
            payload={
            "action": "record",
            "root": str(repo_a),
            "record": {
                    "kind": "fact",
                    "scope": "global",
                    "key": "server-bound-write",
                    "value": "safe value",
                    "provenance": {
                        "root": str(repo_a),
                        "repository_id": "client-repository",
                        "tenant": "victim",
                    },
                },
                "root": str(repo_a),
                "repository_id": "client-repository",
                "tenant": "victim",
            },
        )
        assert status == 200
        assert created["record"]["provenance"]["root"] == str(repo_a.resolve())
        assert created["record"]["provenance"]["repository_id"] == "server-repo-a"
        assert created["record"]["provenance"]["tenant"] == "attacker"
        assert created["record"]["provenance"]["discarded_identity_fields"] == [
            "repository_id",
            "root",
            "tenant",
        ]
        if use_real_store:
            with closing(sqlite3.connect(memory.state_store.db_path)) as con:
                row = con.execute(
                    "SELECT provenance FROM agent_memory_records WHERE record_id = ?",
                    (created["record"]["record_id"],),
                ).fetchone()
            assert row is not None
            assert json.loads(row[0]) == created["record"]["provenance"]

        status, nested_root_created = request(
            "POST",
            payload={
                "action": "record",
                "record": {
                    "kind": "fact",
                    "scope": "global",
                    "key": "nested-root-binding",
                    "value": "safe nested value",
                    "provenance": {
                        "root": str(repo_a),
                        "repository_id": "client-repository",
                        "tenant": "victim",
                    },
                },
            },
        )
        assert status == 200
        assert nested_root_created["record"]["provenance"]["root"] == str(repo_a.resolve())
        assert nested_root_created["record"]["provenance"]["repository_id"] == "server-repo-a"
        assert nested_root_created["record"]["provenance"]["tenant"] == "attacker"
        assert nested_root_created["record"]["provenance"]["discarded_identity_fields"] == [
            "repository_id",
            "root",
            "tenant",
        ]

        status, denied_delete = request(
            "POST",
            payload={
                "action": "delete",
                "record_id": victim.record_id,
                "scope": "global",
                "root": str(repo_b),
                "repository_id": "server-repo-a",
                "tenant": "victim",
            },
        )
        assert status == 403
        assert denied_delete["success"] is False
        assert memory.get(
            victim.record_id,
            scope=AgentScope.GLOBAL,
            root=str(repo_a),
            repository_id="server-repo-a",
            tenant="victim",
        ) is not None

        status, deleted = request(
            "POST",
            payload={
                "action": "delete",
                "record_id": victim.record_id,
                "scope": "global",
                "root": str(repo_a),
                "repository_id": "client-repository",
                "tenant": "victim",
            },
        )
        assert status == 403
        assert deleted["success"] is False
        assert memory.get(
            victim.record_id,
            scope=AgentScope.GLOBAL,
            root=str(repo_a),
            repository_id="server-repo-a",
            tenant="victim",
        ) is not None
        assert project_resolutions
        assert all(state == state_dir.resolve() for _, state in project_resolutions)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.agent_memory = previous_memory
        app.close()


def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(tmp_path, monkeypatch):
    import subprocess

    state_dir = tmp_path / "state"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    state_dir.mkdir()
    repo_a.mkdir()
    repo_b.mkdir()
    for repo in (repo_a, repo_b):
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True)

    root_source_raw = os.environ.get("T05_ROOT_SOURCE")
    if root_source_raw:
        import local_ai_hub

        root_package = Path(root_source_raw).resolve() / "src" / "local_ai_hub"
        package_paths = [Path(item).resolve() for item in local_ai_hub.__path__]
        if root_package not in package_paths:
            local_ai_hub.__path__.append(str(root_package))

    try:
        from local_ai_hub.project_config import resolve_project_context
    except ImportError:
        project_config = types.ModuleType("local_ai_hub.project_config")

        def resolve_project_context(root, configured_dir):
            resolved_root = Path(root).expanduser().resolve(strict=True)
            return types.SimpleNamespace(
                root=resolved_root,
                coordination_id=f"server-{resolved_root.name}",
            )

        project_config.resolve_project_context = resolve_project_context
        monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39133\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n\n[security]\napi_token_tenant = \"tenant-a\"\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    if os.environ.get("T05_OVERLAY_SOURCE") and root_source_raw:
        import local_ai_hub.agent_events as agent_events
        import local_ai_hub.agent_memory as agent_memory_module
        import local_ai_hub.project_config as project_config_module
        import local_ai_hub.sqlite_support as sqlite_support
        import local_ai_hub.state_paths as state_paths

        overlay_source = Path(os.environ["T05_OVERLAY_SOURCE"]).resolve()
        root_source = Path(root_source_raw).resolve()
        assert Path(http_server.__file__).resolve() == overlay_source / "local_ai_hub" / "http_server.py"
        assert Path(agent_memory_module.__file__).resolve() == overlay_source / "local_ai_hub" / "agent_memory.py"
        assert Path(sys.modules["local_ai_hub.app"].__file__).resolve() == root_source / "src" / "local_ai_hub" / "app.py"
        assert Path(agent_events.__file__).resolve() == root_source / "src" / "local_ai_hub" / "agent_events.py"
        assert Path(project_config_module.__file__).resolve() == root_source / "src" / "local_ai_hub" / "project_config.py"
        assert Path(sqlite_support.__file__).resolve() == root_source / "src" / "local_ai_hub" / "sqlite_support.py"
        assert Path(state_paths.__file__).resolve() == root_source / "src" / "local_ai_hub" / "state_paths.py"
        assert hasattr(app.agent_memory.state_store, "append_in_transaction")
        assert hasattr(app.agent_memory.state_store, "ordered_event_publication")

    repo_a_id = resolve_project_context(repo_a, state_dir).coordination_id
    legacy = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="http-exact-root-legacy",
        value="legacy root record",
        provenance={"root": str(repo_a.resolve()), "repository_id": repo_a_id},
    )
    tenant_owned = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="http-tenant-owned-global",
        value="tenant-owned record",
        provenance={"root": str(repo_a.resolve()), "repository_id": repo_a_id, "tenant": "tenant-a"},
    )
    promotion_candidate = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="http-promotion-requires-trusted-approval",
        value="repository-scoped fact",
        provenance={"root": str(repo_a.resolve()), "repository_id": repo_a_id, "tenant": "tenant-a"},
    )
    app.agent_memory.record(legacy, actor="user")
    app.agent_memory.record(tenant_owned, actor="user")
    app.agent_memory.record(promotion_candidate, actor="agent")

    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, *, params=None, payload=None, tenant="tenant-a"):
        path = "/api/agent-state/memory"
        if params:
            path += "?" + urlencode(params)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"X-LocalAI-Tenant": tenant, "Connection": "close"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        status, forged_promotion = request(
            "POST",
            payload={
                "action": "promote",
                "record_id": promotion_candidate.record_id,
                "target_scope": "global",
                "approver": "user",
                "root": str(repo_a),
                "repository_id": repo_a_id,
            },
        )
        assert status == 403
        assert forged_promotion["success"] is False
        still_scoped = app.agent_memory.get(
            promotion_candidate.record_id,
            root=str(repo_a),
            repository_id=repo_a_id,
            tenant="tenant-a",
        )
        assert still_scoped is not None
        assert still_scoped.scope is AgentScope.REPOSITORY

        status, hidden_by_tenant = request(
            "GET",
            params={
                "record_id": tenant_owned.record_id,
                "scope": "global",
                "root": str(repo_a),
                "tenant": "tenant-a",
            },
            tenant="tenant-b",
        )
        assert status == 403
        assert hidden_by_tenant["success"] is False

        status, hidden_by_root = request(
            "GET",
            params={
                "record_id": tenant_owned.record_id,
                "scope": "global",
                "root": str(repo_b),
            },
        )
        assert status == 404
        assert hidden_by_root["success"] is False

        status, tenant_list = request(
            "GET",
            params={
                "scope": "global",
                "root": str(repo_a),
                "key": tenant_owned.key,
                "tenant": "tenant-a",
            },
            tenant="tenant-b",
        )
        assert status == 403
        assert tenant_list["success"] is False

        status, spoofed_query_tenant = request(
            "GET",
            params={
                "scope": "global",
                "root": str(repo_a),
                "key": tenant_owned.key,
                "tenant": "tenant-b",
            },
        )
        assert status == 200
        assert [item["record_id"] for item in spoofed_query_tenant["records"]] == [tenant_owned.record_id]

        status, hidden_post_get = request(
            "POST",
            payload={
                "action": "get",
                "record_id": tenant_owned.record_id,
                "scope": "global",
                "root": str(repo_a),
                "tenant": "tenant-a",
            },
            tenant="tenant-b",
        )
        assert status == 403
        assert hidden_post_get["success"] is False

        status, post_find = request(
            "POST",
            payload={
                "action": "find",
                "scope": "global",
                "root": str(repo_a),
                "key": tenant_owned.key,
                "tenant": "tenant-b",
            },
        )
        assert status == 403
        assert post_find["success"] is False

        status, usable_legacy = request(
            "GET",
            params={
                "record_id": legacy.record_id,
                "scope": "global",
                "root": str(repo_a),
            },
        )
        assert status == 200
        assert usable_legacy["record"]["record_id"] == legacy.record_id

        status, rejected_origin = request(
            "POST",
            payload={
                "action": "record",
                "root": str(repo_a),
                "record": {
                    "kind": "fact",
                    "scope": "repository",
                    "key": "http-spoofed-origin-must-not-persist",
                    "value": "spoofed project origin",
                    "provenance": {
                        "root": str(repo_b),
                        "repository_id": "client-controlled-repository",
                        "tenant": "tenant-b",
                    },
                },
            },
        )
        assert status == 200
        assert rejected_origin["success"] is True
        saved_id = rejected_origin["record"]["record_id"]
        with closing(sqlite3.connect(app.agent_memory.state_store.db_path)) as con:
            persisted = con.execute(
                "SELECT record_id, provenance FROM agent_memory_records WHERE key = ?",
                ("http-spoofed-origin-must-not-persist",),
            ).fetchone()
        assert persisted is not None
        assert persisted[0] == saved_id
        stored_provenance = json.loads(persisted[1])
        assert stored_provenance["root"] == str(repo_a.resolve())
        assert stored_provenance["repository_id"] == repo_a_id
        assert stored_provenance["tenant"] == "tenant-a"
        assert stored_provenance["discarded_identity_fields"] == ["repository_id", "root", "tenant"]

        status, denied_delete = request(
            "POST",
            payload={
                "action": "delete",
                "record_id": tenant_owned.record_id,
                "scope": "global",
                "root": str(repo_b),
                "tenant": "tenant-a",
            },
        )
        assert status == 404
        assert denied_delete["success"] is False
        assert app.agent_memory.get(
            tenant_owned.record_id,
            scope=AgentScope.GLOBAL,
            root=str(repo_a),
            repository_id=repo_a_id,
            tenant="tenant-a",
        ) is not None

        status, authorized_delete = request(
            "POST",
            payload={
                "action": "delete",
                "record_id": tenant_owned.record_id,
                "scope": "global",
                "root": str(repo_a),
                "tenant": "tenant-a",
            },
            tenant="tenant-b",
        )
        assert status == 403
        assert authorized_delete["success"] is False
        assert app.agent_memory.get(
            tenant_owned.record_id,
            scope=AgentScope.GLOBAL,
            root=str(repo_a.resolve()),
            repository_id=repo_a_id,
            tenant="tenant-a",
        ) is not None

        assert app.agent_memory.get(
            tenant_owned.record_id,
            scope=AgentScope.GLOBAL,
            root=str(repo_a.resolve()),
            repository_id=repo_a_id,
            tenant="tenant-a",
        ) is not None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_http_unscoped_global_get_promote_and_delete(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39132\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n\n[security]\napi_token_tenant = \"transport-tenant\"\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="http-shared-global-unscoped-operations",
        value="shared memory",
    )
    app.agent_memory.record(record, actor="user", idempotency_key="http-shared-global")

    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Tenant": "transport-tenant",
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        shared_global = {"record_id": record.record_id, "scope": "global"}
        status, found = post({**shared_global, "action": "get"})
        assert status == 200
        assert found["record"]["record_id"] == record.record_id

        status, promoted = post({
            **shared_global,
            "action": "promote",
            "target_scope": "global",
            "approver": "user",
        })
        assert status == 403
        assert promoted["success"] is False

        status, deleted = post({**shared_global, "action": "delete"})
        assert status == 200
        assert deleted["deleted"] is True
        assert app.agent_memory.get(
            record.record_id,
            scope=AgentScope.GLOBAL,
            tenant="transport-tenant",
        ) is None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_http_unscoped_global_delete_then_record_replay_keeps_tombstone(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39133\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n\n[security]\napi_token_tenant = \"transport-tenant\"\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="http-global-delete-replay-tombstone",
        value="shared searchable memory",
    )
    app.agent_memory.record(record, actor="user", idempotency_key="http-delete-replay")
    assert app.agent_memory.set_embedding(record.record_id, [0.25, 0.75])
    stream_id = "memory:" + "".join(
        f"{len(part)}:{part}" for part in (record.scope.value, record.scope_id or "", record.key or record.record_id)
    )

    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
        data=json.dumps({"action": "delete", "record_id": record.record_id, "scope": "global"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-LocalAI-Tenant": "transport-tenant",
            "Connection": "close",
        },
        method="POST",
    )
    try:
        try:
            with urllib.request.urlopen(request) as response:
                status, deleted = response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status, deleted = exc.code, json.loads(exc.read().decode("utf-8"))
        assert status == 200
        assert deleted["deleted"] is True

        with pytest.raises(ValueError, match="memory record was deleted and cannot be replayed"):
            app.agent_memory.record(record, actor="user", idempotency_key="http-delete-replay")
        assert app.agent_memory.get(
            record.record_id,
            scope=AgentScope.GLOBAL,
            tenant="transport-tenant",
            include_expired=True,
        ) is None
        assert [event.kind for event in app.agent_memory.state_store.events(stream_id)] == [
            "memory.recorded",
            "memory.deleted",
        ]
        with closing(sqlite3.connect(app.agent_memory.state_store.db_path)) as con:
            assert con.execute(
                "SELECT COUNT(*) FROM agent_memory_embeddings WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()[0] == 0
            fts_exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_fts'"
            ).fetchone() is not None
            if fts_exists:
                assert con.execute(
                    "SELECT COUNT(*) FROM agent_memory_fts WHERE record_id = ?",
                    (record.record_id,),
                ).fetchone()[0] == 0
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()

