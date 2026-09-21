from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from local_ai_hub.agent_context import CompiledContext, ContextElement
from local_ai_hub.app import LocalAIApp


def test_context_endpoint_composes_agent_and_repository_context(tmp_path: Path, monkeypatch):
    from local_ai_hub import http_server

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    previous = http_server.APP
    seen = {}
    http_server.APP = app

    def compile_context(request):
        seen["request"] = request
        return CompiledContext(
            elements=[ContextElement("goal", "task_goal", "Agent goal", 2, "goal")],
            estimated_tokens=2,
            token_budget=request.token_budget,
            phase=request.phase,
            repo_revision=request.repo_revision,
        )

    def repository_context(request, *, mode, since_hash):
        seen["repository"] = (request, mode, since_hash)
        return {
            "success": True,
            "context": "Indexed evidence",
            "evidence_ids": ["E1"],
            "repo_revision": "rev-1",
            "context_id": "repo-ctx",
        }

    monkeypatch.setattr(app.agent_context, "compile", compile_context)
    monkeypatch.setattr(app.services, "adaptive_context_pack", repository_context)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "action": "compile",
            "task_id": "task-1",
            "root": str(tmp_path),
            "token_budget": 200,
            "phase": "review",
            "focus": ["context"],
            "preload_profile": "review",
            "repository_revision": "rev-1",
            "repo_since_hash": "repo-etag",
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/context",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result["success"] is True
        assert result["complete"] is True
        assert result["task_context"]["source_layers"] == ["agent_state", "repository"]
        assert "Agent goal" in result["text"]
        assert "Indexed evidence" in result["text"]
        assert result["evidence_ids"] == ["E1"]
        assert seen["request"].phase == "review"
        assert seen["request"].focus == ("context",)
        assert seen["repository"][0].query == "context"
        assert seen["repository"][1] == "full"
        assert seen["repository"][2] == "repo-etag"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous
        app.close()
