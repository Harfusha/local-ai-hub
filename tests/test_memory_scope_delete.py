from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp


def test_global_memory_delete_ignores_transport_tenant_but_keeps_root_scope(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39129\nstate_dir = "{(tmp_path / "state").as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()
    app.memory.put(str(root_a), "global-key", "global value", "owner-tenant")
    app.memory.put(str(root_b), "global-key", "other root value", "owner-tenant")

    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/memory/delete",
            data=json.dumps({"root": str(root_a), "key": "global-key", "scope": "global"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-LocalAI-Tenant": "codex", "Connection": "close"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            deleted = json.loads(response.read().decode("utf-8"))

        assert deleted["deleted"] is True
        assert app.memory.get(str(root_a), "global-key")["success"] is False
        assert app.memory.get(str(root_b), "global-key")["value"] == "other root value"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_tenant_memory_delete_requires_tenant_and_matches_provenance(tmp_path):
    from local_ai_hub.memory import WorkspaceMemoryStore

    store = WorkspaceMemoryStore(tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()
    store.put(str(root), "tenant-key", "value", "owner-tenant")

    missing_tenant = store.delete(str(root), "tenant-key", scope="tenant")
    wrong_tenant = store.delete(str(root), "tenant-key", tenant="codex", scope="tenant")
    matching_tenant = store.delete(str(root), "tenant-key", tenant="owner-tenant", scope="tenant")

    assert missing_tenant["deleted"] is False
    assert wrong_tenant["deleted"] is False
    assert matching_tenant["deleted"] is True
    assert store.get(str(root), "tenant-key")["success"] is False


def test_memory_delete_rejects_unknown_scope():
    from local_ai_hub.http_server import Handler, RequestBodyError

    with pytest.raises(RequestBodyError, match="scope must be 'global' or 'tenant'"):
        Handler._validate_payload("/api/memory/delete", {"key": "memo", "scope": "worktree"})
