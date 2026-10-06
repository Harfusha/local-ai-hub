from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
import pytest

from local_ai_hub import mcp_server as local_ai_mcp
from local_ai_hub.artifacts import ArtifactStore
import mcp.types as t
from local_ai_hub.token_accounting import json_tokens


def test_fallback_used_is_protected_reliability_metadata() -> None:
    assert "fallback_used" in local_ai_mcp._RELIABILITY_PROTECTED_KEYS


def test_python_direct_invocation_returns_dict() -> None:
    res = local_ai_mcp.local_ai_status()
    assert isinstance(res, dict)
    assert "success" in res


def test_mcp_call_tool_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    # Call via FastMCP call_tool (the MCP protocol entrypoint)
    result = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_status", {"detail": "brief"}))

    if isinstance(result, tuple):
        content = result[0][0]
    else:
        assert isinstance(result, list)
        assert len(result) >= 1
        content = result[0]
    assert isinstance(content, t.TextContent)
    assert content.type == "text"

    # Text must be compact (no newline formatting, no spacing around separators)
    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert isinstance(parsed, dict)
    assert parsed["success"] is True


def test_lowlevel_request_handler_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    req = t.CallToolRequest(method="tools/call", params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "brief"}))
    server_res = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](req))

    assert hasattr(server_res, "root")
    tool_res = server_res.root
    assert isinstance(tool_res, t.CallToolResult)
    assert len(tool_res.content) >= 1
    content = tool_res.content[0]
    assert isinstance(content, t.TextContent)

    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert parsed["success"] is True


def _capture_client(monkeypatch, response, *, capture_path_hints=False):
    client = local_ai_mcp.HubClient(tenant="test", auto_start=False)
    calls = []

    def post(path, payload, timeout=None, *, path_hints=None):
        call = (path, payload, timeout)
        calls.append((*call, path_hints) if capture_path_hints else call)
        return response

    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "post", post)
    return calls


def test_local_ai_repo_context_forwards_guarded_pack_fields(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "evidence_ids": ["e1"]})

    result = local_ai_mcp.local_ai_repo(
        action="context",
        root="C:/repo",
        query="find route",
        workspace="ws",
        mode="full",
        task_id="task-1",
        phase="implementation",
        focus=["reuse", "contract"],
        preload_profile="default",
        changed_paths=["src/app.py"],
        base="main",
        staged=True,
        guarded=True,
        since_hash="rev-1",
        approval=True,
        override_reason="approved test scope",
        token_budget=777,
        clone_id="clone-1",
        worktree_id="worktree-1",
        branch="feature/context",
        repository_id="repo-1",
        repository_revision="revision-1",
        include_diagnostics=True,
    )

    assert result["success"] is True
    assert len(calls) == 2
    path, payload, _ = calls[0]
    assert path == "/api/context/pack"
    assert payload == {
        "root": str(Path("C:/repo")),
        "query": "find route",
        "workspace": "ws",
        "max_tokens": 777,
        "mode": "full",
        "guarded": True,
        "task_id": "task-1",
        "phase": "implementation",
        "focus": ["reuse", "contract"],
        "preload_profile": "default",
        "changed_paths": ["src/app.py"],
        "base": "main",
        "staged": True,
        "since_hash": "rev-1",
        "approval": True,
        "override_reason": "approved test scope",
        "token_budget": 777,
        "clone_id": "clone-1",
        "worktree_id": "worktree-1",
        "branch": "feature/context",
        "repository_id": "repo-1",
        "repository_revision": "revision-1",
        "include_diagnostics": True,
    }
    accounting_path, accounting_payload, accounting_timeout = calls[1]
    assert accounting_path == "/api/telemetry/tool-accounting"
    assert isinstance(accounting_payload["batch_id"], str)
    assert accounting_payload["events"] == []
    assert accounting_timeout == 0.25
def test_local_ai_repo_context_preserves_legacy_fast_full_payload(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "context": "legacy"})

    local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="legacy", mode="full", max_tokens=512,
    )

    assert calls == [(
        "/api/context/pack",
        {"root": str(Path("C:/repo")), "query": "legacy", "workspace": None, "max_tokens": 512, "mode": "full"},
        600.0,
    )]


def test_local_ai_repo_non_context_actions_ignore_guard_fields(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "items": []}, capture_path_hints=True)

    local_ai_mcp.local_ai_repo(
        action="search",
        root="C:/repo",
        query="route",
        task_id="task-1",
        phase="review",
        guarded=True,
        changed_paths=["src/app.py"],
        token_budget=777,
        approval=True,
        path_hints=[{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}],
    )

    assert calls == [(
        "/api/search",
        {"root": str(Path("C:/repo")), "query": "route", "top_k": 12, "enrich": False},
        120.0,
        [{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}],
    )]


def test_local_ai_repo_context_returns_bounded_deterministic_projection(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "x" * 20000,
        "evidence": [{"evidence_id": f"e{i}", "content": "y" * 1000} for i in range(40)],
        "evidence_ids": ["deterministic-1"],
        "warnings": [{"code": "scope_drift", "message": "warning"}],
        "repo_revision": "revision-1",
        "changed_paths": ["src/app.py"],
        "degraded": True,
        "fallback_used": True,
        "adaptive_context_pack": {
            "evidence": [{"evidence_id": "deterministic-pack"}],
            "warnings": [{"code": "pack-warning", "message": "pack warning"}],
            "repo_revision": "revision-pack",
            "changed_paths": ["pack.py"],
        },
        "postprocess": {"evidence_ids": ["model-claim"], "changed_paths": ["model.py"]},
    }
    calls = _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=500,
    )

    assert len(json.dumps(result, separators=(",", ":"))) <= 8000
    assert result["evidence_ids"] == ["deterministic-pack"]
    assert result["changed_paths"] == ["pack.py"]
    assert result["repo_revision"] == "revision-pack"
    assert result["warnings"][0]["code"] == "pack-warning"
    assert result["degraded"] is True
    assert result["fallback_used"] is True
    assert calls[0][1]["guarded"] is True


def test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "safe deterministic context",
        "adaptive_context_pack": {
            "context_id": "ctx-safe",
            "evidence": [{"evidence_id": "e1", "path": "src/app.py"}],
            "model_debug": {
                "prompt": "private prompt should not escape",
                "raw_model_output": "private raw model output should not escape",
            },
            "relevance": {
                "claims": [{"output": "nested raw equivalent"}],
                "debug_trace": "private trace",
            },
        },
        "postprocess": {
            "prompt": "private postprocess prompt",
            "raw_model_output": "private postprocess output",
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=500,
    )

    encoded = json.dumps(result, separators=(",", ":"))
    for secret in (
        "model_debug", "raw_model_output", "private prompt should not escape",
        "private raw model output should not escape", "debug_trace", "nested raw equivalent",
    ):
        assert secret not in encoded
    assert result["context_id"] == "ctx-safe"


def test_local_ai_repo_context_bounds_oversized_authoritative_fields(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "context",
        "adaptive_context_pack": {
            "warnings": [{"code": "scope_drift", "message": "w" * 10000} for _ in range(24)],
            "evidence": [{"evidence_id": f"evidence-{i}-" + ("e" * 10000)} for i in range(24)],
            "repo_revision": "revision-" + ("r" * 10000),
            "changed_paths": ["src/" + ("p" * 10000) for _ in range(24)],
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=220,
    )

    assert json_tokens(result) <= 220
    assert result["response_budget"]["requested_tokens"] == 220


def test_local_ai_repo_context_low_budget_preserves_authoritative_envelope(monkeypatch) -> None:
    response = {
        "success": True,
        "adaptive_context_pack": {
            "context_id": "ctx-123",
            "repo_revision": "revision-1",
            "stale": True,
            "warnings": [{"code": "scope_drift", "message": "warning"}],
            "evidence": [{"evidence_id": "evidence-1"}],
            "delta_from": "ctx-previous",
            "since_hash": "hash-1",
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context",
        root="C:/repo",
        query="guarded",
        task_id="task-1",
        phase="review",
        guarded=True,
        max_response_tokens=128,
    )

    assert json_tokens(result) <= 128
    assert result["context_id"] == "ctx-123"
    assert result["repo_revision"] == "revision-1"
    assert result["stale"] is True
    assert result["warnings"] == [{"code": "scope_drift", "message": "warning"}]
    assert result["delta_from"] == "ctx-previous"
    assert result["since_hash"] == "hash-1"
    assert result["evidence_ids"] == ["evidence-1"]


def test_local_ai_repo_context_propagates_bounded_http_error(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {
        "success": False, "status_code": 400, "terminal": True, "retryable": False,
        "error": "focus must be a list",
    })

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="bad", guarded=True, task_id="task-1",
    )

    assert result == {
        "success": False,
        "status_code": 400,
        "terminal": True,
        "retryable": False,
        "error": "focus must be a list",
    }
    assert calls[0][0] == "/api/context/pack"


def test_local_ai_repo_context_rejects_non_object_route_response(monkeypatch) -> None:
    _capture_client(monkeypatch, "not-json-object")

    result = local_ai_mcp.local_ai_repo(action="context", root="C:/repo", query="bad")

    assert result == {
        "success": False,
        "status_code": 502,
        "terminal": True,
        "retryable": True,
        "error": "context pack response must be a JSON object",
    }


def test_local_ai_repo_context_rejects_malformed_guard_input_before_http(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", guarded="yes", task_id="task-1",
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert "guarded must be boolean" in result["error"]
    assert calls == []


def test_local_ai_repo_context_enforces_pack_budget_and_identity_types(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    below_minimum = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", task_id="task-1", phase="review", max_tokens=127,
    )
    mismatched = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", task_id="task-1", phase="review",
        max_tokens=256, token_budget=512,
    )
    malformed_identity = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", task_id="task-1", phase="review", branch=42,
    )
    invalid_mode = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", mode="unsafe",
    )

    assert "128" in below_minimum["error"]
    assert "must match" in mismatched["error"]
    assert "branch must be string" in malformed_identity["error"]
    assert "context mode must be adaptive" in invalid_mode["error"]
    assert len(calls) == 3
    for accounting_path, accounting_payload, accounting_timeout in calls:
        assert accounting_path == "/api/telemetry/tool-accounting"
        assert isinstance(accounting_payload["batch_id"], str)
        assert accounting_payload["events"] == []
        assert accounting_timeout == 0.25

def test_local_ai_repo_context_rejects_guard_fields_without_guard_trigger(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", changed_paths=["src/app.py"],
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "require guarded=true" in result["error"]
    assert calls == []


def test_context_compile_compatibility_stays_on_agent_state_route(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "task_id": "task-1"})

    local_ai_mcp.local_ai_repo(action="context_compile", root="C:/repo", task_id="task-1", max_tokens=900)

    assert calls[0][0] == "/api/agent-state/context"
    assert calls[0][1]["task_id"] == "task-1"
    assert calls[0][1]["token_budget"] == 900


def test_mcp_artifact_page_rejects_store_slice_larger_than_text_limit(monkeypatch, tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    artifact_id = store.put("small cap payload " * 100, "tenant-a", "text")
    client = local_ai_mcp.HubClient(tenant="tenant-a", auto_start=False)
    artifact_calls = []

    def get_artifact(path, payload, timeout=None):
        artifact_calls.append((path, payload))
        return store.get(
            payload["artifact_id"],
            offset=payload["offset"],
            max_chars=payload["max_chars"] + 1,
            tenant="tenant-a",
        )

    monkeypatch.setattr(local_ai_mcp, "MAX_TEXT", 128)
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "post", get_artifact)
    result = asyncio.run(
        local_ai_mcp.mcp.call_tool(
            "local_ai_artifact",
            {"action": "get", "artifact_id": artifact_id, "offset": 0, "max_chars": 512},
        )
    )
    if isinstance(result, tuple):
        content = result[0][0]
    else:
        assert isinstance(result, list) and result
        content = result[0]
    assert isinstance(content, t.TextContent)
    parsed = json.loads(content.text)
    assert artifact_calls[0][1]["max_chars"] == 128
    assert parsed["success"] is False
    assert parsed["error"] == (
        "Artifact page exceeds configured MCP text limit; "
        "increase compact_max_text_chars and retry."
    )
    assert "text" not in parsed
    assert "next_offset" not in parsed


def test_in_memory_stdio_handles_eight_concurrent_status_calls(monkeypatch) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    calls = threading.Barrier(8)
    client = local_ai_mcp.HubClient(tenant="concurrent-stdio-test", auto_start=False)

    def get(_path, timeout=None):
        calls.wait(timeout=4)
        return {"hub_online": True, "scheduler": {}, "observability": {}}

    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(local_ai_mcp._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(local_ai_mcp.CONTEXT_LEDGER, "record", lambda **_kwargs: None)

    async def call_eight():
        async with create_connected_server_and_client_session(local_ai_mcp.mcp) as session:
            results = await asyncio.wait_for(
                asyncio.gather(*(
                    session.call_tool("local_ai_status", {"detail": "brief"})
                    for _ in range(8)
                )),
                timeout=6,
            )
        return results

    results = asyncio.run(call_eight())
    assert len(results) == 8
    assert all(not result.isError for result in results)
    payloads = [json.loads(result.content[0].text) for result in results]
    assert all(payload["success"] is True for payload in payloads), payloads

def test_registered_mcp_context_uses_actual_http_context_pack(tmp_path, monkeypatch) -> None:
    import hashlib
    import importlib.util
    import json
    import os
    import sys
    import threading
    import urllib.error
    import urllib.request

    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    # Candidate uses the owner-pinned T21 source. Root uses its real resolver.
    project_config_path = os.environ.get("LOCAL_AI_HUB_T21_PROJECT_CONFIG_SOURCE")
    if project_config_path:
        project_config_source = Path(project_config_path)
        assert hashlib.sha256(project_config_source.read_bytes()).hexdigest().upper() == (
            "088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1"
        )
        spec = importlib.util.spec_from_file_location("local_ai_hub.project_config", project_config_source)
        assert spec is not None and spec.loader is not None
        project_config = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, project_config)
        spec.loader.exec_module(project_config)
    else:
        from local_ai_hub import project_config

    assert callable(project_config.resolve_project_context)

    repo = tmp_path / "repo"
    source = repo / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("class AdaptiveContextMarker: pass\n", encoding="utf-8")
    excluded = repo / "vendor" / "private.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text("class AdaptiveContextMarker: pass\n", encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\nauto_start_ollama = false\n'
        '\n[hardware]\nprofile = "cpu"\nauto_tune = false\n'
        '\n[prewarm]\nenabled = false\n'
        '\n[preprocessing]\nenabled = false\n'
        '\n[code_intelligence]\nenabled = false\n'
        '\n[agent_state]\nenabled = false\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    original_app = http_server.APP
    original_hybrid = app.services._hybrid_context
    hybrid_calls = []

    def record_hybrid(*args, **kwargs):
        hybrid_calls.append(dict(kwargs))
        return original_hybrid(*args, **kwargs)

    app.services._hybrid_context = record_hybrid
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport_calls = []

    def post_actual_route(path, payload, timeout=None):
        transport_calls.append((path, dict(payload)))
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return json.loads(error.read().decode("utf-8"))

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", post_actual_route)
    try:
        wire = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_repo", {
            "action": "context", "root": str(repo), "query": "AdaptiveContextMarker",
            "mode": "adaptive", "max_tokens": 512,
            "max_response_tokens": 512,
            "path_hints": [{"path": "/src", "purpose": "context candidate", "scope": "repository"}],
            "exclude_paths": ["vendor"],
        }))
        content = wire[0][0] if isinstance(wire, tuple) else wire[0]
        result = json.loads(content.text)

        assert result["success"] is True, result
        assert result["success"] is True, result
        assert hybrid_calls and hybrid_calls[0]["quality_first"] is True
        assert hybrid_calls[0]["path_hints"] == ({"path": "src", "purpose": "context candidate", "scope": "repository"},)
        assert hybrid_calls[0]["exclude_paths"] == ("vendor",)
        assert transport_calls[0][0] == "/api/context/pack"
        assert transport_calls[0][1]["mode"] == "adaptive"
        assert transport_calls[0][1]["path_hints"] == [{"path": "/src", "purpose": "context candidate", "scope": "repository"}]
        assert transport_calls[0][1]["exclude_paths"] == ["vendor"]
        assert "AdaptiveContextMarker" in result["context"]
        assert all(item.get("path") != "vendor/private.py" for item in result.get("evidence", []))
        assert result["response_budget"]["returned_tokens"] <= 512
        assert json_tokens(result) <= 512
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = original_app
        app.close()
