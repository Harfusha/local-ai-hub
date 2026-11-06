from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from local_ai_hub import mcp_server


<<<<<<< C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\ours
def test_status_projection_reports_truncated_paths() -> None:
    paths = [f"src/file_{i:03}.py" for i in range(67)]
    result = mcp_server._compact({"success": True, "modified_count": 67, "modified": paths}, "status")
=======
def test_status_projection_reports_omitted_modified_paths() -> None:
    paths = [f"src/file_{i:03}.py" for i in range(67)]
    result = mcp_server._compact(
        {"success": True, "modified_count": len(paths), "modified": paths}, "status"
    )
>>>>>>> C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\theirs
    assert result["modified_count"] == 67
    assert len(result["modified"]) == 50
    assert result["truncated"] is True


<<<<<<< C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\ours
def test_git_status_wire_exposes_truncation(monkeypatch, tmp_path) -> None:
=======
def test_status_projection_omission_count_survives_small_budget() -> None:
    paths = [f"src/long-directory-name/file_{i:03}.py" for i in range(67)]
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({"max_response_tokens": 500, "response_profile": "compact"})
    try:
        result = mcp_server._compact({"success": True, "modified_count": 67, "modified": paths}, "status")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert result["truncated"] is True
    if "modified" in result:
        assert len(result["modified"]) < result["modified_count"]


def test_git_status_wire_exposes_truncated_path_list(monkeypatch, tmp_path) -> None:
>>>>>>> C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\theirs
    paths = [f"src/long-directory-name/file_{i:03}.py" for i in range(67)]
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
        "success": True, "root": str(tmp_path), "modified_count": 67, "modified": paths,
    }))
    raw = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
<<<<<<< C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\ours
        "action": "git_status", "root": str(tmp_path), "max_response_tokens": 500, "response_profile": "compact",
=======
        "action": "git_status", "root": str(tmp_path), "max_response_tokens": 500,
        "response_profile": "compact",
>>>>>>> C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\theirs
    }))
    content = raw[0][0] if isinstance(raw, tuple) else raw[0]
    response = json.loads(content.text)
    assert response["success"] is True
    assert response["truncated"] is True
    assert response["modified_count"] == 67


<<<<<<< C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\ours
def test_git_status_filter_counts_matching_paths(monkeypatch, tmp_path) -> None:
=======
def test_git_status_wire_reports_budget_clipping_below_item_cap(monkeypatch, tmp_path) -> None:
    paths = [f"src/long-directory-name/file_{i:03}.py" for i in range(20)]
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
        "success": True, "root": str(tmp_path), "modified_count": len(paths), "modified": paths,
    }))
    raw = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "git_status", "root": str(tmp_path), "max_response_tokens": 500,
        "response_profile": "compact",
    }))
    content = raw[0][0] if isinstance(raw, tuple) else raw[0]
    response = json.loads(content.text)
    if len(response.get("modified", [])) < len(paths):
        assert response.get("truncated") is True or response.get("response_budget", {}).get("truncated") is True


def test_git_status_path_filter_counts_only_matching_paths(monkeypatch, tmp_path) -> None:
>>>>>>> C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\theirs
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
        "success": True, "root": str(tmp_path), "modified_count": 2,
        "modified": ["src/one.py", "other/two.py"], "staged_count": 0,
        "staged": [], "untracked_count": 0, "untracked": [],
    }))
    result = mcp_server.local_ai_repo(action="git_status", root=str(tmp_path), path="src")
    assert result["modified"] == ["src/one.py"]
    assert result["modified_count"] == 1


<<<<<<< C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\ours
def test_git_status_filter_does_not_call_incomplete_data_clean(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    payloads = [
        {"modified_count": 3, "modified": ["other/one.py"], "truncated": True},
        {"modified_count": 2},
        {"modified_count": 1, "modified": "src/one.py"},
    ]
    for payload in payloads:
        monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
            "success": True, "root": str(tmp_path), **payload,
        }))
        result = mcp_server.local_ai_repo(action="git_status", root=str(tmp_path), path="src")
        assert result.get("clean") is not True
        assert result.get("modified_count") is None
        assert result["truncated"] is True
=======
def test_git_status_path_filter_does_not_call_incomplete_scope_clean(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
        "success": True, "root": str(tmp_path), "modified_count": 3,
        "modified": ["other/one.py"], "truncated": True,
    }))
    result = mcp_server.local_ai_repo(action="git_status", root=str(tmp_path), path="src")
    assert result.get("clean") is not True
    assert result.get("modified_count") is None
    assert result["truncated"] is True


def test_git_status_path_filter_does_not_call_missing_paths_clean(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
        "success": True, "root": str(tmp_path), "modified_count": 2,
    }))
    result = mcp_server.local_ai_repo(action="git_status", root=str(tmp_path), path="src")
    assert result.get("clean") is not True
    assert result.get("modified_count") is None
    assert result["truncated"] is True


def test_git_status_path_filter_rejects_malformed_path_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *args, **kwargs: {
        "success": True, "root": str(tmp_path), "modified_count": 1, "modified": "src/one.py",
    }))
    result = mcp_server.local_ai_repo(action="git_status", root=str(tmp_path), path="src")
    assert result.get("clean") is not True
    assert result.get("modified_count") is None
    assert result["truncated"] is True
>>>>>>> C:\Users\Adam\AppData\Local\Temp\tmpxlih_dqy\theirs


def test_adaptive_context_pack_preserves_decision_metadata_through_full_projection(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    options_token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(
        {
            "max_response_tokens": 220,
            "response_profile": "compact",
            "reuse_key": "test:mcp-nested-context-contract",
            "tool": "local_ai_repo",
        }
    )
    try:
        result = mcp_server._context_pack_projection(
            {
                "success": True,
                "guarded": True,
                "adaptive_context_pack": {
                    "success": True,
                    "terminal": True,
                    "retryable": False,
                    "degraded": True,
                    "stale": True,
                    "evidence": [{"evidence_id": "E-context-contract", "source": "deterministic"}],
                    "evidence_ids": ["E-context-contract"],
                    "context_id": "context-contract",
                },
            }
        )
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(options_token)

    pack = result["adaptive_context_pack"]
    assert pack["success"] is True
    assert pack["terminal"] is True
    assert pack["retryable"] is False
    assert pack["degraded"] is True
    assert pack["stale"] is True
    assert pack["evidence_ids"] == ["E-context-contract"]
    # At this compact budget the evidence pointer is protected; detailed evidence
    # remains available by ID instead of displacing decision/status fields.
    assert result["evidence_ids"] == ["E-context-contract"]
