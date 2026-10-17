from __future__ import annotations

import inspect

import pytest

from local_ai_hub import client as client_module, http_server, mcp_server, services
from local_ai_hub.agent_consistency import ConsistencyRequest
from local_ai_hub.operation_contracts import validate_operation_call


@pytest.mark.parametrize(
    ("mode", "expected_mode"),
    ((None, "adaptive"), ("adaptive", "adaptive"), ("fast", "fast"), ("full", "full")),
)
def test_context_routes_default_and_explicit_canonical_modes(
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


@pytest.mark.parametrize("mode", ["legacy-fast", "Adaptive"])
def test_context_rejects_retired_or_noncanonical_mode_before_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    mode: str,
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
        mode=mode,
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["error"] == "context mode must be adaptive, full or fast"
    assert calls == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    (({}, "adaptive"), ({"mode": "adaptive"}, "adaptive"),
     ({"mode": "fast"}, "fast"), ({"mode": "full"}, "full"),
     ({"mode": "legacy-fast"}, None), ({"mode": "Adaptive"}, None), ({"mode": None}, None)),
)
def test_http_context_mode_resolver_defaults_adaptive_and_rejects_invalid(
    payload: dict[str, object], expected: str | None
) -> None:
    assert http_server.Handler._context_retrieval_mode(payload) == expected


@pytest.mark.parametrize("mode", ["legacy-fast", "Adaptive"])
def test_service_context_mode_defaults_adaptive_and_rejects_before_context_work(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    assert inspect.signature(services.LocalAIServices.adaptive_context_pack).parameters["mode"].default == "adaptive"
    service = object.__new__(services.LocalAIServices)
    request = object.__new__(ConsistencyRequest)
    monkeypatch.setattr(
        service,
        "_adaptive_memory_revision",
        lambda _request: pytest.fail("invalid mode must be rejected before context work"),
    )

    result = service.adaptive_context_pack(request, mode=mode)

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["error"] == "context mode must be adaptive, full or fast"


def test_client_context_pack_routes_canonical_modes_and_rejects_invalid_before_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object.__new__(client_module.HubClient)
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        client,
        "post",
        lambda endpoint, payload: calls.append((endpoint, payload)) or {"success": True},
    )

    client.context_pack("C:/repo", "find symbols")
    client.context_pack("C:/repo", "find symbols", mode="fast")
    client.context_pack("C:/repo", "find symbols", mode="full")
    invalid = client.context_pack("C:/repo", "find symbols", mode="legacy-fast")

    assert calls == [
        ("/api/context/pack", {"root": "C:/repo", "query": "find symbols", "max_tokens": 4200, "mode": "adaptive"}),
        ("/api/context/pack", {"root": "C:/repo", "query": "find symbols", "max_tokens": 4200, "mode": "fast"}),
        ("/api/context/pack", {"root": "C:/repo", "query": "find symbols", "max_tokens": 4200, "mode": "full"}),
    ]
    assert invalid["success"] is False
    assert invalid["terminal"] is True
    assert invalid["retryable"] is False
    assert invalid["error"] == "context mode must be adaptive, full or fast"


@pytest.mark.parametrize("mode", ["adaptive", "fast", "full"])
def test_context_operation_contract_preserves_canonical_query(mode: str) -> None:
    assert validate_operation_call(
        "local_ai_repo", {"action": "context", "query": "grounded task", "mode": mode}
    ) is None


def test_context_operation_contract_rejects_query_alias_and_nonadaptive_path_controls() -> None:
    alias_error = validate_operation_call(
        "local_ai_repo", {"action": "context", "description": "grounded task"}
    )
    assert alias_error is not None
    assert "description" in alias_error[1]

    path_control_error = validate_operation_call(
        "local_ai_repo",
        {"action": "context", "query": "grounded task", "mode": "fast", "path_hints": ["src"]},
    )
    assert path_control_error is not None
    assert "requires mode='adaptive'" in path_control_error[1]
