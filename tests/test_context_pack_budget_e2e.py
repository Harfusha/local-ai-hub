from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from local_ai_hub import http_server, mcp_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.operational_mode import OperationalModeSnapshot
from local_ai_hub.token_accounting import json_tokens


def test_mcp_adaptive_context_pack_crosses_http_with_bounded_provenance(tmp_path: Path, monkeypatch):
    # MCP module keeps process-global config; isolate its mode gate from the
    # operator's installed Hub mode so this HTTP contract test is deterministic.
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: OperationalModeSnapshot("active", 0, None),
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = false\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    monkeypatch.setattr(http_server, "APP", app)
    calls = []

    def adaptive_context_pack(request, *, mode, since_hash):
        calls.append((request, mode, since_hash))
        evidence = {
            "evidence_id": "E-T14-1",
            "path": "src/routes.py",
            "start_line": 4,
            "end_line": 5,
            "source": "deterministic",
            "content": "private source detail " * 600,
        }
        return {
            "success": True,
            "guarded": True,
            "query": request.query,
            "context": "route context " * 600,
            "context_id": "ctx-t14-e2e",
            "repo_revision": "rev-t14-1",
            "evidence_ids": [evidence["evidence_id"]],
            "evidence": [evidence],
            "contract": {"goal": request.query},
            "context_pack": {
                "context_id": "ctx-t14-e2e",
                "repo_revision": "rev-t14-1",
                "evidence": [evidence],
                "evidence_ids": [evidence["evidence_id"]],
            },
        }

    monkeypatch.setattr(app.services, "adaptive_context_pack", adaptive_context_pack)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    posted = []

    def post_to_http(path: str, payload: dict, timeout: float = 30.0):
        posted.append((path, dict(payload)))
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    monkeypatch.setattr(mcp_server.CLIENT, "post", post_to_http)
    try:
        result = mcp_server.local_ai_repo(
            action="context",
            root=str(tmp_path),
            query="inspect route",
            mode="adaptive",
            guarded=True,
            phase="review",
            focus=["route contract"],
            token_budget=512,
            max_response_tokens=512,
            response_profile="compact",
            reuse_key="t14-context-pack-e2e",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()

    context_posts = [item for item in posted if item[0] == "/api/context/pack"]
    assert len(context_posts) == 1
    path, payload = context_posts[0]
    assert path == "/api/context/pack"
    assert payload["mode"] == "adaptive"
    assert payload["max_tokens"] == payload["token_budget"] == 512
    assert len(calls) == 1
    assert calls[0][1:] == ("adaptive", "")
    assert result["success"] is True
    assert result["context_id"] == "ctx-t14-e2e"
    assert result["repo_revision"] == "rev-t14-1"
    assert result["evidence_ids"] == ["E-T14-1"]
    assert result["provenance"]["status"] == "success"
    assert result["contract"]["goal"] == "inspect route"
    assert result["response_budget"]["requested_tokens"] == 512
    assert result["response_budget"]["original_tokens"] > 512
    assert result["response_budget"]["returned_tokens"] == json_tokens(result) <= 512
    assert "private source detail" not in repr(result)


def test_context_pack_projection_deduplicates_evidence_ids():
    evidence = {
        "evidence_id": "E-T14-duplicate",
        "path": "src/routes.py",
        "start_line": 4,
        "end_line": 5,
        "source": "deterministic",
    }
    result = mcp_server._context_pack_projection({
        "success": True,
        "guarded": True,
        "adaptive_context_pack": {"evidence": [evidence, dict(evidence)]},
    })

    assert result["evidence_ids"] == ["E-T14-duplicate"]
