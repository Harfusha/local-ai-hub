from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server, mcp_server
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.http_route_registry import select_http_routes
from local_ai_hub.operation_contracts import operation_parameters_schema, validate_operation_arguments


def _non_accounting_posts(posts):
    artifact_fields = {"artifact_id", "offset", "max_chars", "section", "binary", "slices"}
    for path, payload in posts:
        if path == "/api/telemetry/tool-accounting":
            assert artifact_fields.isdisjoint(payload)
    return [post for post in posts if post[0] != "/api/telemetry/tool-accounting"]


@pytest.mark.parametrize(
    "payload",
    [
        {"artifact_id": "a", "offset": "1"},
        {"artifact_id": "a", "offset": True},
        {"artifact_id": "a", "max_chars": 0},
        {"artifact_id": "a", "max_chars": 50_001},
        {"artifact_id": "a", "max_chars": 1.5},
        {"artifact_id": "a", "section": None},
        {"artifact_id": "a", "binary": 1},
        {"artifact_id": "a", "surprise": True},
        {"artifact_id": "a", "slices": None},
        {"artifact_id": "a", "slices": []},
        {"artifact_id": "a", "slices": [{"offset": True, "max_chars": 1}]},
        {"artifact_id": "a", "slices": [{"offset": 0, "max_chars": 1, "ignored": 0}]},
    ],
)
def test_http_get_rejects_noncanonical_wire_inputs(tmp_path, monkeypatch, payload) -> None:
    store = ArtifactStore(tmp_path)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(artifacts=store))
    response = {}
    handler = object.__new__(http_server.Handler)
    handler._send = lambda status, body: response.update(status=status, body=body)

    handler._handle_post_artifact_get(payload)

    assert "post_artifact_get_1" in select_http_routes("POST", "/api/artifact/get")
    assert response["status"] == 400
    assert response["body"]["success"] is False


def test_http_get_forwards_canonical_small_page_unchanged(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("small page", kind="text")
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(artifacts=store))
    response = {}
    handler = object.__new__(http_server.Handler)
    handler._send = lambda status, body: response.update(status=status, body=body)

    handler._handle_post_artifact_get(
        {"artifact_id": artifact_id, "offset": 2, "max_chars": 1, "section": "", "binary": False},
    )

    assert response["status"] == 200
    assert response["body"]["text"] == "a"
    assert response["body"]["offset"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        {"offset": "1"},
        {"offset": True},
        {"max_chars": 0},
        {"max_chars": 1.5},
        {"section": None},
        {"binary": 1},
        {"section": "x" * 513},
    ],
)
def test_mcp_get_rejects_noncanonical_arguments_before_post(monkeypatch, arguments) -> None:
    posts = []
    monkeypatch.setattr(mcp_server, "MAX_TEXT", 6000)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: posts.append(args))

    result = mcp_server.local_ai_artifact(action="get", artifact_id="artifact-1", **arguments)

    assert result["success"] is False
    assert _non_accounting_posts(posts) == []


def test_mcp_get_forwards_small_page_exactly_and_schema_keeps_source_bounds(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("small page", kind="text")
    posts = []
    monkeypatch.setattr(mcp_server, "MAX_TEXT", 6000)

    def post(path, payload, **_kwargs):
        posts.append((path, payload))
        if path == "/api/telemetry/tool-accounting":
            return {"success": True}
        return store.get(
            payload["artifact_id"], offset=payload["offset"],
            max_chars=payload["max_chars"], section=payload["section"],
        )

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_artifact(
        action="get", artifact_id=artifact_id, offset=2, max_chars=1, section="",
    )
    assert result["success"] is True
    assert result["text"] == "a"
    assert _non_accounting_posts(posts) == [(
        "/api/artifact/get",
        {"artifact_id": artifact_id, "offset": 2, "max_chars": 1, "section": "", "binary": False},
    )]

    schema = operation_parameters_schema("local_ai_artifact")
    assert schema["properties"]["max_chars"]["minimum"] == 1
    assert schema["properties"]["max_chars"]["maximum"] == 50_000
    source_bounds = [
        item["then"]["properties"]["max_chars"]
        for item in schema["allOf"]
        if item.get("if", {}).get("properties", {}).get("action", {}).get("const") == "source"
    ]
    assert source_bounds == [{"minimum": 512, "maximum": 12000}]


def test_mcp_rejects_pages_above_configured_response_text_limit(monkeypatch) -> None:
    posts = []
    monkeypatch.setattr(mcp_server, "MAX_TEXT", 100)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: posts.append(args))

    result = mcp_server.local_ai_artifact(
        action="get", artifact_id="artifact-1", max_chars=101,
    )

    assert result["success"] is False
    assert "MCP text limit of 100" in result["error"]
    assert _non_accounting_posts(posts) == []


def test_mcp_rejects_slice_mixed_with_single_page_arguments(monkeypatch) -> None:
    posts = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: posts.append(args))
    result = mcp_server.local_ai_artifact(
        action="slice", artifact_id="artifact-1", slices=[{"offset": 0, "max_chars": 1}], offset=1,
    )
    assert result["success"] is False
    assert _non_accounting_posts(posts) == []


@pytest.mark.parametrize("size, valid", [(511, False), (512, True), (12_000, True), (12_001, False)])
def test_source_action_keeps_its_existing_exact_size_bounds(size, valid) -> None:
    error = validate_operation_arguments(
        "local_ai_artifact", "source", {"path": "src/file.py", "max_chars": size},
    )
    assert (error is None) is valid
