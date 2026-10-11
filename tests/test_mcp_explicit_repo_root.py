from pathlib import Path

import pytest

from local_ai_hub import mcp_server


@pytest.mark.parametrize("root", ["", "."])
def test_repo_scoped_mcp_action_rejects_implicit_workspace_root(monkeypatch, root: str) -> None:
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    result = mcp_server.local_ai_repo(action="profile", root=root)

    assert result["success"] is False
    assert "explicit absolute project root" in result["error"]
    assert all(args and args[0] == "/api/telemetry/tool-accounting" for args, _kwargs in calls)


def test_repo_scoped_mcp_action_keeps_explicit_root(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    # A queued accounting batch may share this transport with the repository call.
    mcp_server.CLIENT.post("/api/telemetry/tool-accounting", {"events": []}, timeout=0.25)
    result = mcp_server.local_ai_repo(action="profile", root=str(tmp_path.resolve()))

    assert result["success"] is True
    business_calls = [
        (args, kwargs) for args, kwargs in calls
        if args and args[0] != "/api/telemetry/tool-accounting"
    ]
    assert len(business_calls) == 1
    assert business_calls[0][0][0] == "/api/repo/profile"
    assert business_calls[0][0][1]["root"] == str(tmp_path.resolve())


def test_skeletonize_does_not_require_a_repository_root(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    result = mcp_server.local_ai_repo(action="skeletonize", query="def example(): return 1")

    assert result["success"] is True
    business_calls = [
        (args, kwargs) for args, kwargs in calls
        if args and args[0] != "/api/telemetry/tool-accounting"
    ]
    assert len(business_calls) == 1
    assert business_calls[0][0][1]["code"] == "def example(): return 1"
    assert "root" not in business_calls[0][0][1]


@pytest.mark.parametrize("root", ["", "."])
def test_rag_action_rejects_implicit_workspace_root(monkeypatch, root: str) -> None:
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    result = mcp_server.local_ai_rag(action="index", root=root)

    assert result["success"] is False
    assert "explicit absolute project root" in result["error"]
    assert all(args and args[0] == "/api/telemetry/tool-accounting" for args, _kwargs in calls)


def test_rag_action_keeps_explicit_root(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    result = mcp_server.local_ai_rag(action="index", root=str(tmp_path.resolve()))

    assert result["success"] is True
    rag_calls = [call for call in calls if call[0][0] == "/api/rag/index"]
    assert len(rag_calls) == 1
    assert rag_calls[0][0][1]["root"] == str(tmp_path.resolve())
