"""Deferred source regressions for the canonical JSON etag fast path."""

import json

from local_ai_hub import agent_context


def _compiled_context(*, provenance=None):
    element = agent_context.ContextElement(
        element_id="element-1",
        source_kind="repository",
        content="x" * 768,
        estimated_tokens=192,
        reason="test",
        provenance=provenance or {},
    )
    return agent_context.CompiledContext(
        elements=[element], estimated_tokens=192, token_budget=256
    )


def test_canonical_orjson_etag_uses_fast_serializer_without_default(monkeypatch):
    compiled = _compiled_context()
    real_json_bytes = json.dumps
    calls = []

    def fast_serializer(value, **kwargs):
        calls.append(kwargs)
        assert "default" not in kwargs
        return real_json_bytes(value, **kwargs).encode("utf-8")

    monkeypatch.setattr(agent_context, "json_backend_name", lambda: "orjson")
    monkeypatch.setattr(agent_context, "json_dumps_bytes", fast_serializer)
    fast_etag = compiled.etag()

    monkeypatch.setattr(agent_context, "json_backend_name", lambda: "stdlib")
    stdlib_etag = compiled.etag()

    assert calls == [
        {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")}
    ]
    assert fast_etag == stdlib_etag


def test_unsupported_value_uses_stdlib_default_string_fallback(monkeypatch):
    class Unsupported:
        def __str__(self):
            return "stable-unsupported-value"

    compiled = _compiled_context(provenance={"extra": Unsupported()})
    fast_calls = []

    def fast_serializer(value, **kwargs):
        fast_calls.append(kwargs)
        raise AssertionError("noncanonical value must bypass fast serializer")

    monkeypatch.setattr(agent_context, "json_backend_name", lambda: "orjson")
    monkeypatch.setattr(agent_context, "json_dumps_bytes", fast_serializer)
    fallback_etag = compiled.etag()

    monkeypatch.setattr(agent_context, "json_backend_name", lambda: "stdlib")
    stdlib_etag = compiled.etag()

    assert fast_calls == []
    assert fallback_etag == stdlib_etag
