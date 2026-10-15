from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import project_config
from local_ai_hub.code_index import CodeIndex
from local_ai_hub import http_server
from local_ai_hub import mcp_server
from local_ai_hub.project_config import PathHint, ProjectSettings
from local_ai_hub.projection import AgentProjector
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW


def _service_for_repo_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, entry_point: str | None = None,
) -> tuple[Path, LocalAIServices, SimpleNamespace]:
    root = tmp_path / "repo"
    root.mkdir()
    settings = ProjectSettings(entry_points=(entry_point,) if entry_point else ())
    context = SimpleNamespace(
        resolution=SimpleNamespace(error_codes=()),
        settings=settings,
        config_digest="test-config",
        path_hints=lambda **_kwargs: [],
        prioritize_paths=lambda paths, **_kwargs: SimpleNamespace(
            paths=tuple(paths), hint_used=False, fallback_used=False,
        ),
    )
    monkeypatch.setattr(project_config, "resolve_project_context", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(
        project_config,
        "validate_path_hint",
        lambda base, hint, **_kwargs: Path(base) / hint.path,
    )
    monkeypatch.setattr(project_config, "path_is_allowed", lambda *_args, **_kwargs: True)

    def prioritize(base, paths, hints, **_kwargs):
        preferred = {hint.path for hint in hints}
        ordered = [path for path in paths if path in preferred]
        ordered.extend(path for path in paths if path not in preferred)
        return SimpleNamespace(paths=tuple(ordered), hint_used=bool(preferred), fallback_used=False)

    monkeypatch.setattr(project_config, "prioritize_paths_with_hints", prioritize)
    repo_tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    service.repo_tools = repo_tools
    service.deterministic = None
    service.code_index = None
    service.preprocessor = None
    service.learner = None
    service.evidence_store = None
    service._repo_cache_state = lambda _root: {"fingerprint": "revision-1"}
    service._repo_cached = lambda _operation, _root, _params, compute: compute()
    return root, service, context


def test_service_exact_count_pages_late_request_hint_after_candidate_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service, _context = _service_for_repo_search(
        tmp_path, monkeypatch, entry_point="yyy-config-hint.py",
    )
    for index in range(350):
        (root / f"file-{index:03}.py").write_text("needle match\n", encoding="utf-8")
    (root / "zzz-request-hint.py").write_text("needle match\n", encoding="utf-8")
    (root / "yyy-config-hint.py").write_text("needle match\n", encoding="utf-8")
    request_hint = [{"path": "zzz-request-hint.py", "purpose": "repository_search", "scope": "repo_search"}]

    first = service.repo_search(str(root), "needle", limit=20, offset=0, path_hints=request_hint)
    second = service.repo_search(str(root), "needle", limit=20, offset=20, path_hints=request_hint)
    late = service.repo_search(str(root), "needle", limit=20, offset=330, path_hints=request_hint)

    assert [hit["path"] for hit in first["results"][:2]] == [
        "zzz-request-hint.py", "yyy-config-hint.py",
    ]
    assert first["total_matches"] == second["total_matches"] == late["total_matches"] == 352
    assert all(type(page["total_matches"]) is int for page in (first, second, late))
    assert all(type(page["has_more"]) is bool for page in (first, second, late))
    assert first["has_more"] is True and second["has_more"] is True and late["has_more"] is True
    assert not ({item["path"] for item in first["results"]} & {item["path"] for item in second["results"]})
    assert late["results"][0]["path"] == "file-328.py"


def test_service_repo_search_cache_identity_includes_page_hints_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service, context = _service_for_repo_search(tmp_path, monkeypatch)
    (root / "a.py").write_text("needle\n", encoding="utf-8")
    (root / "hint.py").write_text("needle\n", encoding="utf-8")
    cache_params: list[dict[str, object]] = []

    def run_cached(_operation, _root, params, compute):
        cache_params.append(dict(params))
        return compute()

    service._repo_cached = run_cached
    hint = [{"path": "hint.py", "purpose": "repository_search", "scope": "repo_search"}]
    service.repo_search(str(root), "needle", limit=10, offset=0)
    service.repo_search(str(root), "needle", limit=10, offset=10)
    service.repo_search(str(root), "needle", limit=10, offset=10, path_hints=hint)
    context.config_digest = "changed-config"
    service.repo_search(str(root), "needle", limit=10, offset=10, path_hints=hint)

    assert cache_params[0] != cache_params[1]
    assert cache_params[1] != cache_params[2]
    assert cache_params[2] != cache_params[3]
    assert cache_params[0]["offset"] == 0 and cache_params[1]["offset"] == 10


@pytest.mark.parametrize(("task_kind", "page_key"), [("search", "results"), ("code_index", "symbols")])
def test_mcp_compaction_returns_413_when_budget_omits_requested_page_rows(
    monkeypatch: pytest.MonkeyPatch, task_kind: str, page_key: str,
) -> None:
    page = [{"path": f"{index:03}.py", "name": f"symbol_{index:03}"} for index in range(40)]
    value = {
        "success": True, "root": ".", page_key: page, "limit": 40,
        "offset": 40, "total_matches": 100, "has_more": True,
    }

    def omit_page_rows(compacted, **_kwargs):
        result = dict(compacted)
        result[page_key] = []
        return result

    monkeypatch.setattr(mcp_server, "_response_budget", lambda *_args: (128, "compact", "", True))
    monkeypatch.setattr(mcp_server, "budget_response", omit_page_rows)
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({"tool": "local_ai_repo", "max_response_tokens": 128})
    try:
        result = mcp_server._compact(value, task_kind=task_kind)
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["success"] is False
    assert result["status_code"] == 413
    assert result["offset"] == 40
    assert result["limit"] == 40
    assert result["total_matches"] == 100
    assert result["has_more"] is True
    assert result[page_key] == []


def test_code_index_compaction_keeps_largest_whole_symbol_prefix_with_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = [
        {
            "path": f"src/{index:03}.py", "name": f"symbol_{index:03}",
            "kind": "function", "line": index + 1,
            "signature": f"def symbol_{index:03}(value: str) -> str",
            "matched_terms": ["symbol"] if index % 2 else ["function"],
        }
        for index in range(40)
    ]
    value = {
        "success": True, "root": ".", "symbols": page, "limit": 40,
        "offset": 40, "total_matches": 100, "returned_count": 40,
        "matches_count": 40, "has_more": True,
    }

    def omit_page_rows(compacted, **_kwargs):
        result = dict(compacted)
        result["symbols"] = []
        return result

    monkeypatch.setattr(mcp_server, "_response_budget", lambda *_args: (1800, "compact", "", True))
    monkeypatch.setattr(mcp_server, "budget_response", omit_page_rows)
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({"tool": "local_ai_repo", "max_response_tokens": 1800})
    try:
        result = mcp_server._compact(value, task_kind="code_index")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["success"] is True
    assert 0 < len(result["symbols"]) < len(page)
    assert result["symbols"] == page[:len(result["symbols"])]
    assert result["returned_count"] == result["matches_count"] == result["returned_limit"] == len(result["symbols"])
    assert result["offset"] == 40
    assert result["limit"] == 40
    assert result["total_matches"] == 100
    assert result["has_more"] is True
    assert result["next_offset"] == 40 + len(result["symbols"])


def test_registered_code_index_wire_keeps_prefix_and_final_wire_accounting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from local_ai_hub.token_accounting import json_tokens

    page = [
        {
            "path": f"src/{index:03}.py", "name": f"symbol_{index:03}",
            "kind": "function", "line": index + 1,
            "signature": f"def symbol_{index:03}(value: str) -> str",
            "matched_terms": ["symbol"] if index % 2 else ["function"],
        }
        for index in range(40)
    ]
    raw = {
        "success": True, "root": str(tmp_path), "symbols": page, "limit": 40,
        "offset": 40, "total_matches": 100, "returned_count": 40,
        "matches_count": 40, "has_more": True, "terms": ["symbol", "function"],
        "observed_match_count": 100, "truncated": True, "stale": False,
        "confidence": 0.05,
        "confidence_basis": "returned_query_term_coverage_result_support_and_candidate_freshness",
        "coverage": {
            "query_term_count": 2, "matched_term_count": 2,
            "matched_terms": ["function", "symbol"], "query_term_coverage": 1.0,
            "candidate_match_count": 100, "returned_symbol_count": 40,
            "complete": False, "scope": "indexed_symbol_candidates",
        },
        "freshness": {
            "status": "not_checked", "scope": "returned_symbol_candidates",
            "checked_paths": 0, "stale_paths": [],
            "unknown_paths": [symbol["path"] for symbol in page], "complete": False,
        },
        "truncation": {
            "result_limit": 40, "returned_count": 40,
            "observed_match_count": 100, "candidate_cap": 256,
            "candidate_cap_reached": False,
        },
        "parse_outcomes": {"scope": "returned_symbol_candidates", "files_examined": 40},
    }

    class DummyClient:
        def post(self, path, _payload, **_kwargs):
            assert path == "/api/repo/code-index"
            return dict(raw)

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    monkeypatch.setattr(mcp_server, "_workspace", str(tmp_path))
    monkeypatch.setattr(
        mcp_server, "budget_response",
        lambda *_args, **_kwargs: {
            "success": False, "status_code": 413, "terminal": True,
            "retryable": False, "failure_kind": "response_budget_rejected",
            "error": "page clipped", "response_budget": {"rejected": True},
        },
    )
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **kwargs: None)
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *args, **kwargs: mcp_server.OperationalModeSnapshot("active", 0, None),
    )
    requested = 1800
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "code_index", "root": str(tmp_path), "query": "symbol",
        "limit": 40, "offset": 40, "max_response_tokens": requested,
    }))
    contents, structured = result if isinstance(result, tuple) else (result, None)
    payload = json.loads(contents[0].text)
    wire = {
        "content": [{"type": "text", "text": contents[0].text}],
        "structuredContent": structured,
        "isError": False,
    }
    wire_tokens = json_tokens(wire)

    assert structured is not None
    assert 0 < len(payload["symbols"]) < len(page)
    assert payload["symbols"] == page[:len(payload["symbols"])]
    assert payload["success"] is True
    assert not (payload.get("success") is True and payload.get("status_code") == 413)
    assert "failure_kind" not in payload
    assert payload["response_budget"].get("rejected") is not True
    assert payload["returned_count"] == payload["returned_limit"] == len(payload["symbols"])
    assert payload["total_matches"] == 100
    prefix_terms = sorted({term for symbol in payload["symbols"] for term in symbol["matched_terms"]})
    assert payload["coverage"]["matched_terms"] == prefix_terms
    assert payload["coverage"]["matched_term_count"] == len(prefix_terms)
    assert payload["coverage"]["returned_symbol_count"] == len(payload["symbols"])
    assert payload["coverage"]["candidate_match_count"] == 100
    assert payload["freshness"]["unknown_paths"] == [symbol["path"] for symbol in payload["symbols"]]
    assert "stale" not in payload or isinstance(payload["stale"], bool)
    assert payload["confidence"] <= raw["confidence"]
    from local_ai_hub.operation_contracts import validate_operation_output
    assert validate_operation_output("local_ai_repo", "code_index", payload) is None
    assert "parse_outcomes" not in payload
    assert "parse_outcomes" in payload["omitted_fields"]
    assert payload["truncation"]["returned_count"] == len(payload["symbols"])
    assert payload["truncation"]["observed_match_count"] == 100
    assert payload["truncation"]["candidate_cap"] == 256
    assert payload["observed_match_count"] == 100
    assert payload["has_more"] is True
    assert payload["next_offset"] == 40 + len(payload["symbols"])
    assert wire_tokens <= requested
    assert payload["response_budget"]["returned_tokens"] == wire_tokens
    assert structured["response_budget"]["returned_tokens"] == wire_tokens


@pytest.mark.parametrize("limit,offset", [(MAX_PAGE_SIZE + 1, 0), (24, MAX_PAGE_WINDOW)])
def test_service_code_query_rejects_values_above_http_bounds(
    tmp_path: Path, limit: int, offset: int,
) -> None:
    service = object.__new__(LocalAIServices)
    result = service.code_query(str(tmp_path), "symbol", limit=limit, offset=offset)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["symbols"] == []


def test_search_projection_preserves_requested_page_larger_than_24() -> None:
    source = {
        "success": True,
        "results": [{"path": f"{index:03}.py", "start_line": 1} for index in range(40)],
        "limit": 40,
        "offset": 40,
        "total_matches": 100,
        "has_more": True,
    }

    projected = AgentProjector().project(source, task_kind="search")

    assert len(projected["results"]) == 40
    assert projected["limit"] == 40
    assert projected["offset"] == 40
    assert projected["total_matches"] == 100
    assert projected["has_more"] is True


def test_code_index_projection_preserves_requested_page_larger_than_24() -> None:
    source = {
        "success": True,
        "symbols": [{"name": f"symbol_{index:03}"} for index in range(40)],
        "limit": 40,
        "offset": 40,
        "total_matches": 100,
        "has_more": True,
    }

    projected = AgentProjector().project(source, task_kind="code_index")

    assert len(projected["symbols"]) == 40
    assert projected["limit"] == 40
    assert projected["offset"] == 40
    assert projected["total_matches"] == 100
    assert projected["has_more"] is True


def test_http_code_index_route_returns_bounded_400_for_upper_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_calls: list[tuple[object, object]] = []

    def code_query(_root, _query, limit, _include_code, offset):
        service_calls.append((limit, offset))
        return {
            "success": False, "status_code": 400, "limit": None,
            "offset": offset, "total_matches": 0, "has_more": False,
            "symbols": [], "error": "limit must be 1..100000",
        }

    app = SimpleNamespace(
        recovery=None,
        services=SimpleNamespace(code_query=code_query),
        debug_traces=None,
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(http_server, "select_http_routes", lambda *_args: {"post_repo_code_index_1"})
    monkeypatch.setattr(http_server, "select_post_handler", lambda _route_ids: None)

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/repo/code-index"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: {"root": ".", "query": "symbol", "limit": MAX_PAGE_SIZE + 1, "offset": 0}
    handler._validate_payload = lambda _path, _payload: None
    handler._tenant = lambda: "test"
    handler._claim_recovery = lambda *_args: True
    responses: list[tuple[int, dict[str, object]]] = []
    handler._send = lambda status, body: responses.append((status, body))
    handler._finish_debug_trace = lambda *_args, **_kwargs: None
    handler._close_trace_context = lambda: None

    handler.do_POST()

    assert service_calls == [(MAX_PAGE_SIZE + 1, 0)]
    assert responses[0][0] == 400
    assert responses[0][1]["success"] is False
    assert responses[0][1]["total_matches"] == 0
    assert responses[0][1]["has_more"] is False


def test_http_search_route_maps_service_503_to_transport_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SimpleNamespace(
        recovery=None,
        services=SimpleNamespace(repo_search=lambda *_args, **_kwargs: {
            "success": False, "status_code": 503, "error": "exact scan incomplete",
            "results": [], "total_matches": 0, "has_more": False,
        }),
        debug_traces=None,
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(http_server, "select_http_routes", lambda *_args: {"post_search_1"})
    monkeypatch.setattr(http_server, "select_post_handler", lambda _route_ids: None)

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/search"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: {"root": ".", "query": "needle"}
    handler._validate_payload = lambda _path, _payload: None
    handler._tenant = lambda: "test"
    handler._claim_recovery = lambda *_args: True
    responses: list[tuple[int, dict[str, object]]] = []
    handler._send = lambda status, body: responses.append((status, body))
    handler._finish_debug_trace = lambda *_args, **_kwargs: None
    handler._close_trace_context = lambda: None

    handler.do_POST()

    assert responses[0][0] == 503
    assert responses[0][1]["success"] is False
    assert responses[0][1]["total_matches"] == 0
    assert responses[0][1]["has_more"] is False
