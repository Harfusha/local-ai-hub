import asyncio
from contextlib import closing
from pathlib import Path

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.mcp_server import (
    _normalize_deterministic, _relation_page_with_prefix, _relation_prefix_fitting,
    json_tokens, local_ai_repo,
)
from local_ai_hub.token_accounting import account_projection
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub import mcp_server


def _use_active_operational_mode(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)


def _repo_tools(tmp_path: Path) -> RepositoryTools:
    return RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}, "search": {"prefer_git_files": False}})


def test_index_relations_are_stable_pages_with_truthful_totals(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "calls.py").write_text(
        "def target():\n    pass\n\ndef alpha():\n    target()\n    helper()\n\ndef beta():\n    target()\n",
        encoding="utf-8",
    )
    tools = _repo_tools(tmp_path)
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=tools)
    assert index.update_file(str(root), "calls.py")["success"]

    callers_first = index.find_callers(str(root), "target", limit=1, offset=0)
    callers_second = index.find_callers(str(root), "target", limit=1, offset=1)
    callees = index.find_callees(str(root), "alpha", limit=1, offset=1)

    assert callers_first["callers"][0]["caller"].endswith("alpha")
    assert callers_second["callers"][0]["caller"].endswith("beta")
    assert callers_second["total_matches"] == 2
    assert callers_second["has_more"] is False
    assert callees["callees"][0]["callee"] == "helper"
    assert callees["offset"] == 1


def test_implementation_relations_are_stable_pages(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=_repo_tools(tmp_path))
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root, src, dst, src_name, dst_name, kind, path, line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (str(root.resolve()), "Beta", "Base", "Beta", "Base", "implements", "z.py", 3),
                (str(root.resolve()), "Alpha", "Base", "Alpha", "Base", "inherits", "a.py", 2),
            ],
        )
        con.commit()

    first = index.find_implementations(str(root), "Base", limit=1)
    second = index.find_implementations(str(root), "Base", limit=1, offset=1)

    assert first["implementations"][0]["implementer"] == "Alpha"
    assert first["has_more"] is True
    assert second["implementations"][0]["implementer"] == "Beta"
    assert second["total_matches"] == 2


def test_deterministic_fallback_keeps_caller_and_callee_directions_and_offsets(tmp_path):
    root = tmp_path / "fallback"
    root.mkdir()
    (root / "a.py").write_text(
        "def target():\n    pass\n\ndef alpha():\n    target()\n    helper()\n\ndef beta():\n    target()\n",
        encoding="utf-8",
    )
    tools = _repo_tools(tmp_path)
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=tools)

    callers = engine.find_callers(str(root), "target", limit=1, offset=1)
    callees = engine.find_callees(str(root), "alpha", limit=1, offset=1)

    assert callers["callers"][0]["caller"] == "beta"
    assert callees["callees"][0]["callee"] == "helper"
    assert callers["coverage"]["scope"] == "python_ast"
    assert callers["offset"] == callees["offset"] == 1


def test_deterministic_fallback_marks_parse_failures_incomplete(tmp_path):
    root = tmp_path / "fallback"
    root.mkdir()
    (root / "valid.py").write_text("def caller():\n    target()\n", encoding="utf-8")
    (root / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
    engine = DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=_repo_tools(tmp_path),
    )

    result = engine.find_callers(str(root), "target")

    assert result["success"] is True
    assert result["coverage"]["scan_complete"] is False
    assert result["coverage"]["skipped_files"] == 1
    assert "total_matches" not in result
    assert "has_more" not in result


def test_deterministic_fallback_skips_archived_source_copies(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    archived = root / "docs" / "integration" / "archive"
    archived.mkdir(parents=True)
    (root / "src" / "actual.py").write_text(
        "def target():\n    pass\n\ndef actual_caller():\n    target()\n", encoding="utf-8",
    )
    (archived / "old_copy.py").write_text(
        "def old_caller():\n    target()\n", encoding="utf-8",
    )
    engine = DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=_repo_tools(tmp_path),
    )

    result = engine.find_callers(str(root), "target")

    assert [item["caller"] for item in result["callers"]] == ["src::actual_caller"]
    assert result["coverage"]["scan_complete"] is True


def test_relation_services_reject_nonstring_symbols_before_fallback():
    service = object.__new__(LocalAIServices)
    service.code_index = None
    service.deterministic = object()

    assert service.callers("/repo", None)["status_code"] == 400
    assert service.callees("/repo", 42)["status_code"] == 400


def test_service_keeps_known_empty_index_result_without_syntactic_fallback():
    class Index:
        def find_callers(self, *_args):
            return {"success": True, "callers": [], "count": 0, "index_available": True, "coverage": {"complete": True, "scope": "indexed_edges"}}

    class Fallback:
        def find_callers(self, *_args):
            raise AssertionError("known indexed empty relations must not trigger syntactic fallback")

    service = object.__new__(LocalAIServices)
    service.code_index = Index()
    service.deterministic = Fallback()

    assert service.callers("/repo", "missing")["count"] == 0


def test_service_uses_python_fallback_when_root_has_no_indexed_files():
    class Index:
        def find_callees(self, *_args):
            return {"success": True, "callees": [], "count": 0, "index_available": False, "coverage": {"complete": True, "scope": "indexed_edges"}}

    class Fallback:
        def find_callees(self, _root, _symbol, limit, offset):
            return {"success": True, "callees": [{"callee": "helper"}], "count": 1, "limit": limit, "offset": offset}

    service = object.__new__(LocalAIServices)
    service.code_index = Index()
    service.deterministic = Fallback()
    service.deterministic_operation = lambda _op, _root, _params, compute: compute()

    page = service.callees("/repo", "caller", limit=1, offset=0)
    assert page["callees"][0]["callee"] == "helper"


def test_relation_wire_prefix_keeps_whole_items_and_updates_page_metadata():
    items = [
        {"caller": "alpha", "callee": "target", "snippet": "x" * 400},
        {"caller": "beta", "callee": "target", "snippet": "y" * 400},
    ]
    raw = {
        "success": True, "callers": items, "count": 2, "returned_count": 2,
        "offset": 4, "limit": 3, "total_matches": 9, "has_more": True,
        "truncated": True, "coverage": {"complete": False, "scope": "indexed_edges"},
    }
    one = _normalize_deterministic(account_projection(
        raw, _relation_page_with_prefix(raw, raw, "callers", items, 1),
    ))
    one_wire = {"content": [{"type": "text", "text": mcp_server.json_dumps(one)}], "structuredContent": one, "isError": False}
    fitted = _relation_prefix_fitting(raw, raw, "callers", items, json_tokens(one_wire))

    assert fitted is not None
    assert len(fitted["callers"]) == 1
    assert fitted["returned_count"] == 1
    assert fitted["total_matches"] == 9
    assert fitted["next_offset"] == 5
    assert fitted["coverage"]["complete"] is False


def test_relation_compaction_35_to_5_keeps_exact_continuation_metadata():
    items = [{"caller": f"caller_{index}", "callee": "target", "path": f"src/{index}.py", "line": index + 1}
             for index in range(35)]
    raw = {
        "success": True, "callers": items, "count": 35, "returned_count": 35,
        "offset": 0, "limit": 50, "total_matches": 35, "has_more": False,
        "truncated": False, "coverage": {"complete": True, "scope": "indexed_edges"},
    }
    five = _normalize_deterministic(account_projection(
        raw, _relation_page_with_prefix(raw, raw, "callers", items, 5),
    ))
    five_wire = {"content": [{"type": "text", "text": mcp_server.json_dumps(five)}], "structuredContent": five, "isError": False}

    fitted = _relation_prefix_fitting(raw, raw, "callers", items, json_tokens(five_wire))

    assert fitted is not None
    assert len(fitted["callers"]) == fitted["returned_count"] == 5
    assert fitted["total_matches"] == 35
    assert fitted["has_more"] is True
    assert fitted["next_offset"] == 5
    assert fitted["coverage"]["complete"] is False


def test_mcp_relations_require_canonical_query_limit_offset_and_reject_bool(monkeypatch):
    requests = []
    _use_active_operational_mode(monkeypatch)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "is_rooted_path", lambda _path: True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url != "/api/telemetry/tool-accounting":
                requests.append((url, payload))
            return {"success": True, "callers": [], "count": 0}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    legacy_alias = mcp_server._local_ai_repo_impl(action="callers", root=".", query="", task="target")
    invalid_page = mcp_server._local_ai_repo_impl(action="callers", root=".", query="target", limit=True)
    assert requests == []
    assert legacy_alias["success"] is False
    assert invalid_page["success"] is False

    asyncio.run(local_ai_repo(action="callers", root=".", query="target", limit=2, offset=4))
    assert requests[-1][1]["symbol"] == "target"
    assert requests[-1][1]["limit"] == 2
    assert requests[-1][1]["offset"] == 4

    before_alias = len(requests)
    symbol_alias = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "callers", "root": ".", "symbol": "target",
    }))
    conflicting_alias = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "implementations", "root": ".", "query": "Base", "symbol": "OldBase",
    }))
    assert len(requests) == before_alias
    assert "400" in str(symbol_alias) and "400" in str(conflicting_alias)


def test_registered_mcp_relation_wire_rejects_first_item_over_budget(monkeypatch):
    _use_active_operational_mode(monkeypatch)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "is_rooted_path", lambda _path: True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/telemetry/tool-accounting":
                return {"success": True}
            return {
                "success": True,
                "callers": [{"caller": "large", "callee": "target", "snippet": "x" * 20_000}],
                "count": 1, "returned_count": 1, "offset": 0, "limit": 1,
                "total_matches": 1, "has_more": False, "truncated": False,
                "coverage": {"complete": True, "scope": "indexed_edges"},
            }

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    response = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "callers", "root": ".", "query": "target", "limit": 1,
        "max_response_tokens": 128,
    }))

    assert "413" in str(response)
    assert "first complete" in str(response).lower()


def test_registered_relation_budget_reaches_fixed_point_for_one_long_item(monkeypatch):
    raw = {
        "success": True,
        "callers": [{"caller": "long_name", "callee": "target", "snippet": "x" * 900}],
        "count": 1, "returned_count": 1, "offset": 0, "limit": 1,
        "total_matches": 1, "has_more": False, "truncated": False,
        "coverage": {"complete": True, "scope": "indexed_edges"},
    }
    monkeypatch.setattr(mcp_server, "_agent_output", lambda value, _name, _args: value)
    content, structured = mcp_server._mcp_budget_payload("local_ai_repo", {
        "action": "callers", "max_response_tokens": 512,
    }, raw)

    assert structured is not None
    assert len(structured["callers"]) == 1
    assert structured["response_budget"]["returned_tokens"] == json_tokens(
        mcp_server._mcp_wire_view(structured, structured=True),
    )
    assert len(content) == 1
