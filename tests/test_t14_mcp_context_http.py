from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from local_ai_hub import app as app_module, http_server, mcp_server, project_config, retrieval, services, task_context
from local_ai_hub.budget import estimate_tokens
from local_ai_hub.operation_contracts import (
    _ACTION_SCOPED_FIELDS,
    operation_parameters_schema,
    operation_tool_output_schema,
    validate_operation_arguments,
)


def test_registered_mcp_context_hints_reach_root_http_route(tmp_path, monkeypatch):
    overlay_root = Path(__file__).resolve().parents[1]
    assert Path(app_module.__file__).resolve() == overlay_root / "src/local_ai_hub/app.py"
    assert Path(mcp_server.__file__).resolve() == overlay_root / "src/local_ai_hub/mcp_server.py"
    assert Path(http_server.__file__).resolve() == overlay_root / "src/local_ai_hub/http_server.py"
    for module in (project_config, retrieval, services, task_context):
        assert Path(module.__file__).resolve().parent == overlay_root / "src/local_ai_hub"

    tool = mcp_server.mcp._tool_manager._tools["local_ai_repo"]
    properties = tool.parameters["properties"]
    assert {"path_hints", "directory_hints", "exclude_paths", "force_include_paths"} <= set(properties)
    assert "project_config_digest" not in properties
    generated_output = operation_tool_output_schema("local_ai_repo", mcp_server.FEATURES)
    registered_output = tool.fn_metadata.output_schema
    assert generated_output == registered_output == tool.output_schema
    assert registered_output["additionalProperties"] is True
    assert {"success", "status", "status_code", "error", "warning", "terminal", "retryable"} <= set(
        registered_output["properties"]
    )
    assert "anyOf" not in registered_output
    t03_scopes = _ACTION_SCOPED_FIELDS["local_ai_repo"]
    assert t03_scopes["path_hints"] == frozenset({"search", "context"})
    for field in ("directory_hints", "exclude_paths", "force_include_paths"):
        assert t03_scopes[field] == frozenset({"context"})
    assert validate_operation_arguments(
        "local_ai_repo", "context", {
            "root": "C:/repo", "query": "context", "mode": "adaptive",
            "path_hints": [{"path": "/src", "purpose": "context candidate", "scope": "preferred"}],
        }, features=mcp_server.FEATURES,
    ) is None

    repo = tmp_path / "repo"
    source = repo / "src" / "app.py"
    entry = repo / "src" / "main.py"
    pinned = repo / "docs" / "pinned.md"
    forced = repo / "docs" / "forced.py"
    unhinted = repo / "docs" / "unhinted.py"
    excluded = repo / "vendor" / "private.py"
    source.parent.mkdir(parents=True)
    entry.parent.mkdir(parents=True, exist_ok=True)
    pinned.parent.mkdir(parents=True, exist_ok=True)
    excluded.parent.mkdir(parents=True)
    source.write_text("class AdaptiveContextMarker: pass\n", encoding="utf-8")
    entry.write_text("class AdaptiveContextMarker: pass\n", encoding="utf-8")
    pinned.write_text("AdaptiveContextMarker PINNED_CONTEXT_MARKER\n", encoding="utf-8")
    forced.write_text("AdaptiveContextMarker FORCE_INCLUDE_MARKER\n", encoding="utf-8")
    unhinted.write_text("AdaptiveContextMarker UNHINTED_RECALL_MARKER\n", encoding="utf-8")
    excluded.write_text("AdaptiveContextMarker EXCLUDED_VENDOR_MARKER\n", encoding="utf-8")
    (repo / ".local-ai.toml").write_text(
        'pinned_context = ["docs/pinned.md", "vendor/private.py"]\n'
        'entry_points = ["src/main.py"]\n'
        'retrieval_weights = { lexical = 0.25 }\n',
        encoding="utf-8",
    )

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\nauto_start_ollama = false\n'
        '\n[security]\napi_token = "overlay-test-token"\n'
        '\n[hardware]\nprofile = "cpu"\nauto_tune = false\n'
        '\n[prewarm]\nenabled = false\n'
        '\n[preprocessing]\nenabled = false\n'
        '\n[code_intelligence]\nenabled = false\n'
        '\n[agent_state]\nenabled = false\n',
        encoding="utf-8",
    )
    app = app_module.LocalAIApp(str(cfg_path))
    assert type(app.services) is services.LocalAIServices
    resolved_projects = []
    original_resolve = project_config.resolve_project_context

    def record_project_config(root, state_dir=None):
        resolved = original_resolve(root, state_dir)
        resolved_projects.append((
            str(root), resolved.settings.pinned_context, resolved.settings.entry_points,
            resolved.config_digest, dict(resolved.settings.retrieval_weights),
        ))
        return resolved

    monkeypatch.setattr(project_config, "resolve_project_context", record_project_config)
    previous_app = http_server.APP
    previous_client = mcp_server.CLIENT
    hybrid_calls = []
    original_uncached = app.services._hybrid_context_uncached
    repo_cache_calls = []
    original_repo_cache = app.services._repo_cached
    memory_state = {"revision": "memory-1"}
    app.services.consistency_guard = type("Guard", (), {
        "memory_store": type("MemoryStore", (), {
            "revision": staticmethod(lambda _root: memory_state["revision"]),
        })(),
    })()
    lexical_calls = []
    original_pack_paths = app.services.repo_tools.context_pack_paths

    def record_uncached(*args, **kwargs):
        hybrid_calls.append(dict(kwargs))
        return original_uncached(*args, **kwargs)

    def record_pack_paths(root, query, paths, **kwargs):
        lexical_calls.append((tuple(paths), dict(kwargs)))
        return original_pack_paths(root, query, paths, **kwargs)

    def record_repo_cache(operation, root, params, compute):
        if operation == "hybrid-context":
            repo_cache_calls.append(dict(params))
        return original_repo_cache(operation, root, params, compute)

    app.services._hybrid_context_uncached = record_uncached
    app.services.repo_tools.context_pack_paths = record_pack_paths
    app.services._repo_cached = record_repo_cache
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport_calls = []
    accounting_observed = threading.Event()
    accounting_reporter = mcp_server._ProtocolAccountingReporter()
    monkeypatch.setattr(mcp_server, "_ACCOUNTING_REPORTER", accounting_reporter)

    def post_actual_route(path, payload, timeout=None):
        transport_calls.append((path, dict(payload)))
        if path == "/api/telemetry/tool-accounting":
            accounting_observed.set()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-LocalAI-Token": "overlay-test-token"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return json.loads(error.read().decode("utf-8"))

    def context_pack_calls():
        return [call for call in transport_calls if call[0] == "/api/context/pack"]

    monkeypatch.setattr(mcp_server.CLIENT, "post", post_actual_route)
    try:
        negative_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
            "action": "context", "root": str(repo), "query": "AdaptiveContextMarker",
            "mode": "adaptive", "max_tokens": -1,
        }))
        negative_content = negative_wire[0][0] if isinstance(negative_wire, tuple) else negative_wire[0]
        negative = json.loads(negative_content.text)
        assert negative["status_code"] == 400 and negative["terminal"] is True
        assert context_pack_calls() == []
        assert accounting_observed.wait(5), "asynchronous tool accounting was not observed"
        assert any(path == "/api/telemetry/tool-accounting" for path, _payload in transport_calls)

        request_arguments = {
            "action": "context", "root": str(repo), "query": "AdaptiveContextMarker",
            "mode": "adaptive", "max_tokens": 512,
            "path_hints": [{"path": "/src", "purpose": "context candidate", "scope": "preferred"}],
            "directory_hints": ["src"], "exclude_paths": ["vendor"],
            "force_include_paths": ["docs/forced.py"],
        }
        request_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", request_arguments))
        content = request_wire[0][0] if isinstance(request_wire, tuple) else request_wire[0]
        result = json.loads(content.text)

        assert result["success"] is True, result
        assert result["delivery_mode"] == "adaptive"
        assert resolved_projects and resolved_projects[-1][1:3] == (("docs/pinned.md", "vendor/private.py"), ("src/main.py",)), resolved_projects
        context_calls = context_pack_calls()
        assert context_calls
        forwarded = context_calls[0][1]
        assert forwarded["mode"] == "adaptive" and forwarded["max_tokens"] == 512
        assert forwarded["path_hints"] == [{"path": "/src", "purpose": "context candidate", "scope": "preferred"}]
        assert forwarded["directory_hints"] == ["src"]
        assert forwarded["exclude_paths"] == ["vendor"]
        assert forwarded["force_include_paths"] == ["docs/forced.py"]
        assert hybrid_calls and hybrid_calls[0]["quality_first"] is True
        actual_hints = hybrid_calls[0]["path_hints"]
        assert any(item.get("provenance") == "project_config:pinned_context" and item["path"] == "docs/pinned.md" for item in actual_hints), actual_hints
        assert any(item.get("provenance") == "project_config:entry_point" and item["path"] == "src/main.py" for item in actual_hints)
        assert any(item.get("purpose") == "context candidate" and item["path"] == "src" for item in actual_hints)
        assert hybrid_calls[0]["directory_hints"] == ("src",)
        assert hybrid_calls[0]["exclude_paths"] == ("vendor",)
        assert hybrid_calls[0]["force_include_paths"] == ("docs/forced.py",)
        assert hybrid_calls[0]["retrieval_weights"] == {"lexical": 0.25}
        candidates, pack_kwargs = lexical_calls[0]
        assert "docs/pinned.md" in candidates and "src/main.py" in candidates
        assert "docs/forced.py" in candidates and "vendor/private.py" not in candidates
        assert "docs/unhinted.py" in candidates, candidates
        assert pack_kwargs["max_tokens"] <= 512
        assert estimate_tokens(result["context"]) <= 512
        assert "AdaptiveContextMarker" in result["context"]
        assert "PINNED_CONTEXT_MARKER" in result["context"]
        assert "FORCE_INCLUDE_MARKER" in result["context"]
        assert "EXCLUDED_VENDOR_MARKER" not in result["context"]
        assert "UNHINTED_RECALL_MARKER" in result["context"]
        assert all(item.get("path") != "vendor/private.py" for item in result.get("evidence", []))

        memory_state["revision"] = "memory-2"
        second_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", request_arguments))
        second_content = second_wire[0][0] if isinstance(second_wire, tuple) else second_wire[0]
        second = json.loads(second_content.text)
        assert second["success"] is True, second

        (repo / ".local-ai.toml").write_text(
            'pinned_context = ["docs/pinned.md", "vendor/private.py"]\n'
            'entry_points = ["src/main.py"]\n'
            'retrieval_weights = { lexical = 0.75 }\n',
            encoding="utf-8",
        )
        third_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", request_arguments))
        third_content = third_wire[0][0] if isinstance(third_wire, tuple) else third_wire[0]
        third = json.loads(third_content.text)
        assert third["success"] is True, third
        context_calls = context_pack_calls()
        assert len(context_calls) == 3 and all(call[0] == "/api/context/pack" for call in context_calls)
        assert len(repo_cache_calls) == 3 and len(lexical_calls) == 3
        first_identity, second_identity, third_identity = (
            call["context_identity"] for call in repo_cache_calls
        )
        assert first_identity["memory_revision"] == "memory-1"
        assert second_identity["memory_revision"] == "memory-2"
        assert first_identity["project_config_digest"] == second_identity["project_config_digest"]
        assert third_identity["project_config_digest"] != second_identity["project_config_digest"]
        assert first_identity != second_identity and second_identity != third_identity
        assert [call["retrieval_weights"] for call in repo_cache_calls] == [
            {"lexical": 0.25}, {"lexical": 0.25}, {"lexical": 0.75},
        ]
        assert {tuple(sorted(resolved[4].items())) for resolved in resolved_projects} == {
            (("lexical", 0.25),), (("lexical", 0.75),),
        }

        memory_state["revision"] = "memory-3"
        app.services._external_context_candidates = lambda *_args, **_kwargs: (
            {}, ["serena unavailable"], {"serena": "degraded"}
        )
        degraded_wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", request_arguments))
        degraded_content = degraded_wire[0][0] if isinstance(degraded_wire, tuple) else degraded_wire[0]
        degraded = json.loads(degraded_content.text)
        assert degraded["success"] is True, degraded
        assert degraded["degraded"] is True, degraded
        assert "UNHINTED_RECALL_MARKER" in degraded["context"]
        assert len(context_pack_calls()) == 4 and len(repo_cache_calls) == 4
    finally:
        accounting_reporter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        mcp_server.CLIENT = previous_client
        app.close()


def test_project_retrieval_weights_change_rank_without_removing_authoritative_candidates():
    groups = {
        "deterministic": ["src/authority.py"],
        "code_index": ["src/indexed.py"],
        "lexical": ["docs/only-lexical.md", "src/authority.py"],
        "serena": ["src/routes.py", "docs/only-lexical.md"],
    }
    baseline = dict(retrieval.fuse_ranked_paths(groups, limit=8))
    tuned = dict(retrieval.fuse_ranked_paths(
        groups, limit=8,
        source_weights={"lexical": 0.25, "deterministic": 0.0, "code_index": 0.0},
    ))
    assert tuned["src/authority.py"] >= 1.25 / 61
    assert tuned["src/indexed.py"] >= round(1.20 / 61, 6)
    assert tuned["docs/only-lexical.md"] < baseline["docs/only-lexical.md"]
    assert set(tuned) == set(baseline)


def test_slow_serena_deadline_keeps_adaptive_http_content_and_coalesces_backend(tmp_path, monkeypatch):
    class SlowExternalTools:
        def __init__(self):
            self.lock = threading.Lock()
            self.started = 0
            self.started_event = threading.Event()
            self.duplicate_started_event = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()

        def query(self, _root, _query, **_kwargs):
            with self.lock:
                self.started += 1
                if self.started > 1:
                    self.duplicate_started_event.set()
            self.started_event.set()
            self.release.wait(8)
            self.finished.set()
            return {"success": True, "result": []}

    overlay_root = Path(__file__).resolve().parents[1]
    assert Path(services.__file__).resolve() == overlay_root / "src/local_ai_hub/services.py"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "indexed.py").write_text(
        "class SlowBackendMarker: pass  # useful indexed context\n", encoding="utf-8"
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\nauto_start_ollama = false\n'
        '\n[security]\napi_token = "slow-backend-test-token"\n'
        '\n[hardware]\nprofile = "cpu"\nauto_tune = false\n'
        '\n[features]\nrag = false\nreranker = false\ncode_intelligence = false\npreprocessing = false\n'
        'install_local_nlp_dependencies = false\ninstall_openvino_dependencies = false\npull_models_during_setup = false\n'
        '\n[prewarm]\nenabled = false\n'
        '\n[preprocessing]\nenabled = false\n'
        '\n[code_intelligence]\nenabled = false\n'
        '\n[agent_state]\nenabled = false\n'
        '\n[debug_traces]\nenabled = true\n'
        '\n[search]\ncontext_backend_timeout_seconds = 0.1\n',
        encoding="utf-8",
    )
    app = app_module.LocalAIApp(str(cfg_path))
    slow_backend = SlowExternalTools()
    app.services.external_tools = slow_backend
    monkeypatch.setattr(
        app.services, "_adaptive_relevance",
        lambda *_args, **_kwargs: {
            "success": False, "degraded": True,
            "degraded_reason": "model_unavailable", "warnings": [],
        },
    )
    monkeypatch.setattr(
        app.services.repo_state, "fingerprint",
        lambda *_args, **_kwargs: {"fingerprint": "test-revision", "degraded": False, "stale": False},
    )
    monkeypatch.setattr(
        app.services.repo_tools, "git_snapshot",
        lambda _root: type("Snapshot", (), {"revision": "test-revision", "changed_paths": ()})(),
    )
    monkeypatch.setattr(
        app.services.repo_tools, "git_diff",
        lambda *_args, **_kwargs: {"success": True, "diff": ""},
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    serena_threads_before = sum(
        thread.is_alive() and thread.name.startswith("context-serena")
        for thread in threading.enumerate()
    )

    def post(query):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/context/pack",
            data=json.dumps({
                "root": str(repo), "query": query, "mode": "adaptive", "max_tokens": 256,
                "guarded": True, "phase": "edit", "focus": ["SlowBackendMarker"],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-LocalAI-Token": "slow-backend-test-token"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        started_at = time.perf_counter()
        first = post("SlowBackendMarker")
        first_elapsed = time.perf_counter() - started_at
        assert first["success"] is True, first
        assert first_elapsed < 8.0, first_elapsed
        assert slow_backend.started_event.wait(0.2)
        assert first["retrieval"]["backend_states"]["serena"] == "degraded"
        assert "serena timeout" in first["retrieval"]["warnings"]
        assert first["retrieval"]["backend_states"]["lexical"] == "used"
        assert "SlowBackendMarker" in first["context"]
        assert estimate_tokens(first["context"]) <= 256

        started_at = time.perf_counter()
        second = post("SlowBackendMarker second-query")
        second_elapsed = time.perf_counter() - started_at
        assert second["success"] is True, second
        assert second["cache_hit"] is False, second
        assert second_elapsed < 8.0, second_elapsed
        assert second["retrieval"]["backend_states"]["serena"] == "degraded"
        assert "serena timeout" in second["retrieval"]["warnings"]
        assert "SlowBackendMarker" in second["context"]
        assert slow_backend.started == 1
    finally:
        slow_backend.release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        slow_backend.finished.wait(1)
        http_server.APP = previous_app
        app.close()

    assert slow_backend.finished.is_set()
    assert not slow_backend.duplicate_started_event.wait(0.2)
    assert slow_backend.started == 1
    assert not server_thread.is_alive()
    assert sum(
        thread.is_alive() and thread.name.startswith("context-serena")
        for thread in threading.enumerate()
    ) <= max(1, serena_threads_before)
