import pytest
import os
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.opencode_boundary import path_allowed, payload_allowed, generation_scope


def test_local_repository_reads_do_not_reprioritize_preprocessing(tmp_path):
    from local_ai_hub.services import LocalAIServices

    touches = []
    service = LocalAIServices.__new__(LocalAIServices)
    service.preprocessor = SimpleNamespace(touch_if_registered=lambda root: touches.append(root))
    service._repo_cache_state = lambda _root: {}
    with generation_scope("opencode-local"):
        assert service._repo_cached("test", str(tmp_path), {}, lambda: {"success": True})["success"]
    assert touches == []
    with generation_scope("codex"):
        assert service._repo_cached("test", str(tmp_path), {}, lambda: {"success": True})["success"]
    assert touches == [str(tmp_path)]


def test_stale_index_does_not_enqueue_preprocessing_for_opencode(tmp_path, monkeypatch):
    from local_ai_hub.code_index import CodeIndex
    from local_ai_hub.repo_tools import RepositoryTools
    from local_ai_hub.services import LocalAIServices

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "alpha.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "rag": {"extensions": [".py"]}}
    index = CodeIndex(config, RepositoryTools(config))
    monkeypatch.setattr(index, "_parse_file_content", lambda *_args, **_kwargs: ([{
        "name": "alpha", "kind": "function", "line": 1, "end_line": 2,
        "name_path": "alpha", "container": "",
    }], [], []))
    queued = []
    index.set_reindex_callback(lambda path: queued.append(path) or True)
    try:
        assert index.update_file(str(root), "alpha.py")["success"]
        before = source.stat()
        source.write_text("def alpha():\n    return 2\n", encoding="utf-8")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        with generation_scope("opencode-local"):
            result = index.query(str(root), "alpha")
        assert result["stale"] is True
        assert result["freshness"]["reindex_notifications_queued"] == 0
        assert queued == []
        class Cache:
            def __init__(self):
                self.values = {}
            def get_or_compute(self, key, compute):
                hit = key in self.values
                if not hit:
                    self.values[key] = compute()
                return self.values[key], hit, False
        service = LocalAIServices.__new__(LocalAIServices)
        service.code_index, service.learner, service.repo_tools, service.repo_flight = index, None, RepositoryTools(config), Cache()
        service._touch_project = lambda _: None
        service._repo_cache_state = lambda _: {"fingerprint": "fixed"}
        service._refresh_changed_intelligence = lambda _: None
        app = SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}, recovery=None, services=service)
        monkeypatch.setattr(http_server, "APP", app)
        def dispatch(actor):
            handler = http_server.Handler.__new__(http_server.Handler)
            handler.path, handler.headers, handler._authorization_root = "/api/repo/code-index", {"X-LocalAI-Agent": actor}, str(root)
            handler._begin_trace = lambda _path: None
            handler._require_authorized = lambda: True
            handler._read_json = lambda: {"root": str(root), "query": "alpha"}
            handler._validate_payload = lambda _path, _payload: None
            handler._bind_repository_root_payload = lambda _payload: True
            responses = []
            handler._send = lambda status, body: responses.append((status, body))
            handler.do_POST()
            assert responses[0][0] == 200, responses
            return responses[0][1]
        assert dispatch("opencode-local")["freshness"]["reindex_notifications_queued"] == 0
        unrestricted = dispatch("codex")
        assert unrestricted["freshness"]["reindex_notifications_queued"] == 1
        assert queued == [str(source)]
    finally:
        index.close()


@pytest.mark.parametrize("path", ["/api/delegate", "/api/benchmark", "/api/async-jobs", "/api/new-generation-route"])
def test_opencode_profile_denies_generative_and_unclassified_routes(path):
    assert path_allowed("opencode-local", "POST", path) is False
    assert path_allowed("codex", "POST", path) is True


@pytest.mark.parametrize("path", ["/api/repo/code-index", "/api/search", "/api/artifact/get", "/api/agent-state/tasks", "/api/agent-state/verification"])
def test_opencode_profile_accepts_only_explicitly_classified_routes(path):
    assert path_allowed("opencode-local", "POST", path) is True


def test_unknown_actions_are_denied_and_other_clients_are_unchanged():
    path = "/api/agent-state/tasks"
    assert payload_allowed("opencode-local", path, {"action": "create"}) is True
    for action in ("future_model_action", "curate_dataset", "CREATE", "", None, []):
        assert payload_allowed("opencode-local", path, {"action": action}) is False
        assert payload_allowed("codex", path, {"action": action}) is True
    assert payload_allowed("opencode-local", "/api/agent-state/verification", {"action": "completion"}) is True
    assert payload_allowed("opencode-local", "/api/agent-state/verification", {"action": "unknown"}) is False
    assert path_allowed("opencode-local", "POST", "/api/agent-state/memory") is True
    assert payload_allowed("opencode-local", "/api/agent-state/memory", {"action": "record"}) is True
    assert payload_allowed("opencode-local", "/api/agent-state/memory", {"action": "find"}) is True
    assert payload_allowed("opencode-local", "/api/agent-state/memory", {"action": "future_generation"}) is False


def test_only_explicit_read_endpoints_are_allowed():
    assert path_allowed("opencode-local", "GET", "/health") is True
    assert path_allowed("opencode-local", "GET", "/api/status") is True
    assert path_allowed("opencode-local", "GET", "/api/unknown") is False
    assert path_allowed("opencode-local", "DELETE", "/api/status") is False


def test_scheduler_rejects_restricted_request_before_queue_or_execution():
    from local_ai_hub.scheduler import AffinityScheduler

    scheduler = AffinityScheduler.__new__(AffinityScheduler)
    with generation_scope("opencode-local"):
        result = scheduler.submit("model", source="test", execute=lambda: pytest.fail("executed"))
    assert result["success"] is False
    assert result["error_code"] == "opencode_generation_disabled"

    with generation_scope("codex"), pytest.raises(ValueError, match="invalid_model"):
        scheduler.submit("", source="test", execute=lambda: {})


@pytest.mark.parametrize("path", ["/api/delegate", "/api/new-generation-route"])
def test_http_handler_rejects_model_route_before_reading_body(monkeypatch, tmp_path, path):
    app = SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}, recovery=None)
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    if path == "/api/new-generation-route":
        monkeypatch.setattr(http_server, "select_http_routes", lambda _method, _path: ("future-route",))
    handler.path = path
    handler.headers = {"X-LocalAI-Agent": "opencode-local"}
    handler._require_authorized = lambda: True
    handler._read_json = lambda: pytest.fail("model route body must not be read")
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_POST()

    assert responses[0][0] == 403
    assert responses[0][1]["error_code"] == "opencode_local_route_denied"


def test_http_handler_denies_unclassified_read_route(monkeypatch):
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/future-generation-route"
    handler.headers = {"X-LocalAI-Agent": "opencode-local"}
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    handler.do_GET()
    assert responses[0][0] == 403
    assert responses[0][1]["error_code"] == "opencode_local_route_denied"


def test_scoped_runtime_guard_blocks_ollama_and_llama_without_affecting_other_clients(monkeypatch):
    from local_ai_hub.ollama import OllamaRuntime
    from local_ai_hub.llama_cpp import LlamaCppRouter

    calls = []
    runtime = OllamaRuntime.__new__(OllamaRuntime)
    monkeypatch.setattr(runtime, "_request_stream_impl", lambda *a, **k: (calls.append("ollama") or {"success": True}))
    router = LlamaCppRouter.__new__(LlamaCppRouter)
    monkeypatch.setattr(router, "_entry", lambda _model: (calls.append("llama") or None))
    with generation_scope("opencode-local"):
        assert runtime.request_stream("/api/generate", {"model": "test"}, None)["error_code"] == "opencode_generation_disabled"
        assert router.request_stream("/api/chat", {"model": "test"}, None)["error_code"] == "opencode_generation_disabled"
        with generation_scope("codex"):
            assert runtime.request_stream("/api/generate", {"model": "test"}, None)["error_code"] == "opencode_generation_disabled"
    assert calls == []
    with generation_scope("codex"):
        assert runtime.request_stream("/api/generate", {"model": "test"}, None)["success"] is True
        assert router.request_stream("/api/chat", {"model": "test"}, None) is None
    assert calls == ["ollama", "llama"]


@pytest.mark.parametrize("actor,expected_block", [("opencode-local", True), ("codex", False)])
def test_http_request_propagates_profile_to_model_runtime(monkeypatch, tmp_path, actor, expected_block):
    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime.__new__(OllamaRuntime)
    monkeypatch.setattr(runtime, "_request_stream_impl", lambda *a, **k: {"success": True})
    observed = []
    def code_query(*args, **kwargs):
        observed.append(runtime.request_stream("/api/generate", {"model": "test"}, None))
        return {"success": True, "symbols": []}
    app = SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}, recovery=None, services=SimpleNamespace(code_query=code_query))
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/repo/code-index"
    handler.headers = {"X-LocalAI-Agent": actor}
    handler._authorization_root = str(tmp_path)
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"root": str(tmp_path), "query": "symbol"}
    handler._validate_payload = lambda _path, _payload: None
    handler._bind_repository_root_payload = lambda _payload: True
    responses = []
    handler._send = lambda status, body: responses.append((status, body))
    handler.do_POST()
    assert responses[0][0] == 200, responses
    assert len(observed) == 1
    assert (observed[0].get("error_code") == "opencode_generation_disabled") is expected_block
