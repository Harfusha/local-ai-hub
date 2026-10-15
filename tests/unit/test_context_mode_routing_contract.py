from __future__ import annotations

import pytest

from local_ai_hub import mcp_server


@pytest.mark.parametrize(
    ("mode", "expected_mode"),
    ((None, "adaptive"), ("adaptive", "adaptive"), ("fast", "fast"), ("full", "full")),
)
def test_context_uses_adaptive_default_and_preserves_explicit_retrieval_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    mode: str | None,
    expected_mode: str,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def post(self, endpoint: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            captured.update(endpoint=endpoint, payload=payload)
            return {"success": True, "context": "grounded context", "evidence": []}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _name: 1)

    kwargs: dict[str, object] = {
        "action": "context",
        "root": str(tmp_path),
        "query": "find the context contract",
    }
    if mode is not None:
        kwargs["mode"] = mode

    mcp_server._local_ai_repo_impl(**kwargs)  # type: ignore[arg-type]

    assert captured["endpoint"] == "/api/context/pack"
    assert captured["payload"]["mode"] == expected_mode  # type: ignore[index]


def test_context_rejects_unknown_retrieval_mode_before_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def post(self, endpoint: str, _payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            calls.append(endpoint)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)

    result = mcp_server._local_ai_repo_impl(
        action="context",
        root=str(tmp_path),
        query="find the context contract",
        mode="legacy-fast",
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["error"] == "context mode must be adaptive, full or fast"
    assert calls == []
