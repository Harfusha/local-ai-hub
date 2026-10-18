from types import SimpleNamespace

import pytest

from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize(
    "alias_payload",
    [
        {"query": "search", "text": "source", "task": "retired"},
        {"query": "search", "text": "source", "context": "retired"},
    ],
)
def test_route_context_rejects_task_and_context_aliases_before_routing(alias_payload):
    calls = []
    router = SimpleNamespace(
        route_text=lambda *args, **kwargs: calls.append((args, kwargs)),
        route_file=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    services = SimpleNamespace(token_router=router)

    result = LocalAIServices.route_context(services, alias_payload)

    assert result["success"] is False
    assert "not aliases" in result["error"]
    assert calls == []


@pytest.mark.parametrize("field", ["query", "text", "path", "label", "root"])
def test_route_context_rejects_non_string_canonical_values(field):
    calls = []
    router = SimpleNamespace(
        route_text=lambda *args, **kwargs: calls.append((args, kwargs)),
        route_file=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    services = SimpleNamespace(token_router=router)
    payload = {"query": "search", "text": "source", field: True}
    if field == "root":
        payload["path"] = "src/a.py"

    result = LocalAIServices.route_context(services, payload)

    assert result["success"] is False
    assert field in result["error"]
    assert calls == []


def test_route_context_forwards_canonical_text_query_without_coercion():
    calls = []
    expected = {"success": True, "answer": "routed"}
    router = SimpleNamespace(
        route_text=lambda *args, **kwargs: (calls.append((args, kwargs)) or expected),
        route_file=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    services = SimpleNamespace(token_router=router)

    result = LocalAIServices.route_context(
        services,
        {"query": "find symbol", "text": "source body", "label": "src/a.py"},
    )

    assert result is expected
    assert calls == [(("source body", "find symbol"), {"path": "src/a.py"})]
