from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp


def test_retired_tenant_header_is_rejected_before_root_scoped_delete(tmp_path):
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
    app.memory.put(str(root_a), "global-key", "global value")
    app.memory.put(str(root_b), "global-key", "other root value")

    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/memory/delete",
            data=json.dumps({"root": str(root_a), "key": "global-key"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-LocalAI-Tenant": "codex", "Connection": "close"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        assert rejected.value.code == 400
        assert json.loads(rejected.value.read().decode("utf-8"))["error_code"] == "retired_tenant_header"
        assert app.memory.get(str(root_a), "global-key")["success"] is True

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/memory/delete",
            data=json.dumps({"root": str(root_a), "key": "global-key"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close"},
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


def test_workspace_memory_delete_is_scoped_by_repository_root(tmp_path):
    from local_ai_hub.memory import WorkspaceMemoryStore

    store = WorkspaceMemoryStore(tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()
    other_root = tmp_path / "other-repo"
    other_root.mkdir()
    store.put(str(root), "shared-key", "first repository")
    store.put(str(other_root), "shared-key", "second repository")

    deleted = store.delete(str(root), "shared-key")

    assert deleted["deleted"] is True
    assert store.get(str(root), "shared-key")["success"] is False
    assert store.get(str(other_root), "shared-key")["value"] == "second repository"


def test_memory_delete_rejects_unknown_scope():
    from local_ai_hub.http_server import Handler, RequestBodyError

    with pytest.raises(RequestBodyError, match="scope is not supported by workspace memo deletion"):
        Handler._validate_payload("/api/memory/delete", {"key": "memo", "scope": "worktree"})


@pytest.mark.parametrize("scope", ["GLOBAL", " Global", "global ", "Tenant"])
def test_memory_delete_rejects_noncanonical_scope(scope):
    from local_ai_hub.http_server import Handler, RequestBodyError

    with pytest.raises(RequestBodyError, match="scope is not supported by workspace memo deletion"):
        Handler._validate_payload("/api/memory/delete", {"key": "memo", "scope": scope})
