from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize("exact_count", [False, True])
def test_http_search_preserves_literal_query_and_returns_current_source(tmp_path, monkeypatch, exact_count):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bridge.py").write_text("# C++ bridge\n", encoding="utf-8")
    (root / "noise.py").write_text("# common content\n", encoding="utf-8")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    service.repo_tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    service._repo_cached = lambda _name, _root, _params, compute, **_kwargs: compute()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=service.config, recovery=None, services=service))

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.headers, handler._authorization_root = "/api/search", {}, str(root)
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"root": str(root), "query": "C++", "limit": 10, "exact_count": exact_count}
    handler._validate_payload = lambda _path, _payload: None
    handler._bind_repository_root_payload = lambda _payload: True
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses[0][0] == 200
    assert responses[0][1]["search_mode"] == "lexical"
    assert responses[0][1]["count_exact"] is exact_count
    assert [hit["path"] for hit in responses[0][1]["results"]] == ["bridge.py"]


def test_http_search_rejects_explicit_null_search_mode(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=service.config, recovery=None, services=service))

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.headers, handler._authorization_root = "/api/search", {}, str(root)
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"root": str(root), "query": "install", "search_mode": None}
    handler._validate_payload = lambda _path, _payload: None
    handler._bind_repository_root_payload = lambda _payload: True
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses[0][0] == 400
    assert responses[0][1]["error"] == "search_mode must be lexical, rag, or hybrid"


@pytest.mark.parametrize("exact_count,expected", [(None, False), (True, True), (False, False)])
def test_http_search_count_mode_is_explicit_and_fast_by_default(tmp_path, monkeypatch, exact_count, expected):
    root = tmp_path / "repo"
    root.mkdir()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    captured = {}

    def repo_search(*_args, **kwargs):
        captured.update(kwargs)
        return {"success": True, "search_mode": kwargs["search_mode"], "results": []}

    service.repo_search = repo_search
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=service.config, recovery=None, services=service))

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.headers, handler._authorization_root = "/api/search", {}, str(root)
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    payload = {"root": str(root), "query": "Local AI Hub installation"}
    if exact_count is not None:
        payload["exact_count"] = exact_count
    handler._read_json = lambda: payload
    handler._validate_payload = lambda _path, _payload: None
    handler._bind_repository_root_payload = lambda _payload: True
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses[0][0] == 200
    assert captured["search_mode"] == "hybrid"
    assert captured["exact_count"] is expected


def test_http_search_rejects_non_boolean_exact_count(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    service.repo_search = lambda *_args, **_kwargs: pytest.fail("invalid request must not search")
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=service.config, recovery=None, services=service))

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.headers, handler._authorization_root = "/api/search", {}, str(root)
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"root": str(root), "query": "install", "exact_count": 1}
    handler._validate_payload = lambda _path, _payload: None
    handler._bind_repository_root_payload = lambda _payload: True
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses[0][0] == 400
    assert responses[0][1]["error"] == "exact_count must be a boolean"


def test_service_keeps_engine_order_when_a_path_has_multiple_hits(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("needle\nneedle\n", encoding="utf-8")
    (root / "b.py").write_text("needle\n", encoding="utf-8")

    class Tools(RepositoryTools):
        def search(self, root, query, **kwargs):
            return {"success": True, "count_exact": True, "total_matches": 3,
                    "results": [{"path": "a.py", "start_line": 1, "score": 10},
                                {"path": "b.py", "start_line": 1, "score": 5},
                                {"path": "a.py", "start_line": 2, "score": 1}]}

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    service.repo_tools = Tools({"rag": {"extensions": [".py"]}})
    service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    service._repo_cached = lambda _name, _root, _params, compute, **_kwargs: compute()

    result = service.repo_search(str(root), "needle", limit=10, search_mode="lexical")

    assert [(hit["path"], hit["start_line"]) for hit in result["results"]] == [
        ("a.py", 1), ("b.py", 1), ("a.py", 2)
    ]


def test_service_pages_match_full_ranked_result(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("needle needle needle\n" + "pass\n" * 20 + "needle\n", encoding="utf-8")
    (root / "b.py").write_text("needle needle\n", encoding="utf-8")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    service.repo_tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    service._repo_cached = lambda _name, _root, _params, compute, **_kwargs: compute()

    full = service.repo_search(str(root), "needle", limit=10, search_mode="lexical")
    first = service.repo_search(str(root), "needle", limit=2, offset=0, search_mode="lexical")
    second = service.repo_search(str(root), "needle", limit=2, offset=2, search_mode="lexical")

    assert full["count_exact"] is first["count_exact"] is second["count_exact"] is True
    assert first["results"] + second["results"] == full["results"]
