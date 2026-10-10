"""Preserved standalone regressions from fc950005; expectations unchanged."""
from pathlib import Path

import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_memory import AgentScope, MemoryRecord
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract


def test_http_verification_route_rejects_passed_receipt_without_evidence(tmp_path: Path):
    import gc
    import json
    import threading
    import urllib.error
    import urllib.request

    from local_ai_hub import http_server

    principal = "t08-test-principal"
    api_token = "t08-test-token"
    derivation_key = "test-derivation-key-material-32-bytes-min"
    root = str(tmp_path.resolve())
    tenant = http_server._derive_root_tenant(
        principal, str(http_server._strict_root_path(root)), derivation_key
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11502\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        f'\n[security]\napi_token = "{api_token}"\n'
        f'api_token_tenant = "{principal}"\ntenant_derivation_key = "{derivation_key}"\n'
        f'allowed_roots = ["{Path(root).as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    app.agent_tasks.create(
        GoalContract(
            goal="route receipt validation",
            acceptance_criteria=("focused test",),
        ),
        ScopeContext(repository_id=root, task_id="route-task", session_id=tenant),
        task_id="route-task",
        actor=principal,
        repo_root=root,
    )
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "root": root,
            "action": "receipt",
            "receipt": {
                "receipt_id": "route-receipt-no-evidence",
                "task_id": "route-task",
                "criterion": "focused test",
                "passed": True,
            },
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/verification",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Connection": "close",
                "X-LocalAI-Agent": principal,
                "X-LocalAI-Tenant": principal,
                "X-LocalAI-Token": api_token,
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        result = json.loads(error.value.read().decode("utf-8"))
        assert error.value.code == 400, result
        assert result["error"] == "passed verification receipt requires evidence_id"
        assert result["terminal"] is True
        assert result["retryable"] is False
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        gc.collect()
        http_server.APP = previous
        app.close()


def test_http_memory_delete_requires_verified_worktree_scope(tmp_path: Path):
    import gc
    import json
    import threading
    import urllib.error
    import urllib.request

    from local_ai_hub import http_server

    principal = "t08-test-principal"
    api_token = "t08-test-token"
    derivation_key = "test-derivation-key-material-32-bytes-min"
    root = str(tmp_path.resolve())
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        f'\n[security]\napi_token = "{api_token}"\n'
        f'api_token_tenant = "{principal}"\ntenant_derivation_key = "{derivation_key}"\n'
        f'allowed_roots = ["{Path(root).as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    scoped_record = MemoryRecord.create(
        kind="finding",
        scope=AgentScope.WORKTREE,
        scope_id="worktree-one",
        key="private-delete",
        value="preserve me",
    )
    global_record = MemoryRecord.create(
        kind="finding",
        scope=AgentScope.GLOBAL,
        key="global-delete",
        value="delete me",
    )
    app.agent_memory.record(scoped_record, actor="user")
    app.agent_memory.record(global_record, actor="user")
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps({"root": root, **payload}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Connection": "close",
                "X-LocalAI-Agent": principal,
                "X-LocalAI-Tenant": principal,
                "X-LocalAI-Token": api_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            post({
                "action": "delete",
                "record_id": scoped_record.record_id,
                "scope": "worktree",
                "scope_id": "worktree-one",
                "worktree_id": "worktree-one",
            })
        assert denied.value.code == 403
        assert app.agent_memory.get(
            scoped_record.record_id,
            scope=AgentScope.WORKTREE,
            scope_id="worktree-one",
        ).value == "preserve me"
        deleted = post({"root": None, "action": "delete", "record_id": global_record.record_id, "scope": "global"})
        assert deleted["deleted"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        gc.collect()
        http_server.APP = previous
        app.close()
