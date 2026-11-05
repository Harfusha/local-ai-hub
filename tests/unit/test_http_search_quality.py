from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def test_http_search_preserves_literal_query_and_returns_current_source(tmp_path, monkeypatch):
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
    handler._read_json = lambda: {"root": str(root), "query": "C++", "limit": 10}
    handler._validate_payload = lambda _path, _payload: None
    handler._bind_repository_root_payload = lambda _payload: True
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses[0][0] == 200
    assert responses[0][1]["search_mode"] == "hybrid"
    assert [hit["path"] for hit in responses[0][1]["results"]] == ["bridge.py"]


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

    result = service.repo_search(str(root), "needle", limit=10)

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

    full = service.repo_search(str(root), "needle", limit=10)
    first = service.repo_search(str(root), "needle", limit=2, offset=0)
    second = service.repo_search(str(root), "needle", limit=2, offset=2)

    assert full["count_exact"] is first["count_exact"] is second["count_exact"] is True
    assert first["results"] + second["results"] == full["results"]
