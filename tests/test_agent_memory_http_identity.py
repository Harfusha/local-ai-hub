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


def test_http_global_memory_identity_uses_repository_scope_and_session_id(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    state_dir.mkdir()
    repo_a.mkdir()
    repo_b.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39131\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n",
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
        key="global-http-owner-scope",
        value="shared global value",
        provenance={"root": str(repo_a), "repository_id": "repo-a"},
    )
    app.agent_memory.record(global_record, actor="user")
    session_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        key="session-http-private",
        value="private session value",
        provenance={},
    )
    app.agent_memory.record(session_record, actor="user")
    owned_global_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="repository-provenance-global-http",
        value="private global value",
        provenance={"root": str(repo_a), "repository_id": "repo-a"},
    )
    app.agent_memory.record(owned_global_record, actor="user")
    authenticated_global_record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="authenticated-global-http-delete",
        value="repository-provenance global value",
        provenance={"root": str(repo_a), "repository_id": "repo-a"},
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
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        global_payload = {
            "action": "get",
            "record_id": global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
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
            "session_id": "session-codex",
        }
        status, found_session = post(session_payload)
        assert status == 200
        assert found_session["record"]["record_id"] == session_record.record_id

        owned_global_payload = {
            "record_id": owned_global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
        }
        status, found_owned_global = post({**owned_global_payload, "action": "get"})
        assert status == 200
        assert found_owned_global["record"]["record_id"] == owned_global_record.record_id

        authenticated_delete = {
            "action": "delete",
            "record_id": authenticated_global_record.record_id,
            "scope": "global",
            "root": str(repo_a),
            "repository_id": "repo-a",
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


def test_http_memory_rejects_retired_tenant_field(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    repo = tmp_path / "repo"
    state_dir.mkdir()
    repo.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39132\nstate_dir = "{state_dir.as_posix()}"\n\n'
        "[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps({"action": "find", "tenant": None}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        with error.value:
            assert error.value.code in {400, 422}
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()
