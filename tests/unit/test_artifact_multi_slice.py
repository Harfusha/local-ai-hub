from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.operation_contracts import validate_operation_output
from local_ai_hub.artifacts import ArtifactStore


def test_mcp_get_returns_disjoint_slices_in_one_post(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    text = "abcd🙂α\x00" * 60
    artifact_id = store.put(text, tenant="slice-test", kind="log")
    assert store.get(artifact_id, offset=5, max_chars=256, tenant="slice-test")["text"] == text[5:261]
    requested = [
        {"offset": 10, "max_chars": 40},
        {"offset": 200, "max_chars": 50},
    ]
    assert store.get_slices(artifact_id, requested, tenant="wrong-tenant")["success"] is False
    posts: list[tuple[str, dict]] = []
    statements: list[str] = []
    connect = store._connect

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    store._connect = traced_connect

    def post(path: str, payload: dict, **_kwargs):
        posts.append((path, payload))
        return store.get_slices(
            payload["artifact_id"], payload["slices"], tenant="slice-test"
        )

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    actual = mcp_server.local_ai_artifact(
        action="slice", artifact_id=artifact_id, slices=requested
    )

    assert len(posts) == 1
    assert posts[0][0] == "/api/artifact/get"
    assert posts[0][1]["slices"] == requested
    assert actual["slices"] == [
        {"offset": 10, "text": text[10:50]},
        {"offset": 200, "text": text[200:250]},
    ]
    assert actual["total_chars"] == len(text)
    assert actual["truncated"] is False
    assert actual["budget_limited"] is False
    assert validate_operation_output("local_ai_artifact", "slice", actual) is None
    selects = [
        statement.lower()
        for statement in statements
        if statement.lstrip().lower().startswith("select") and "substr(" in statement.lower()
    ]
    assert len(selects) == 1
    assert selects[0].count("substr(") == 4


@pytest.mark.parametrize(
    "slices",
    [
        [{"offset": 0, "max_chars": 5, "ignored": True}],
        [{"offset": -1, "max_chars": 5}],
        [{"offset": 0, "max_chars": 1}] * 17,
        [{"offset": 0, "max_chars": mcp_server.MAX_TEXT}, {"offset": 1, "max_chars": 1}],
    ],
)
def test_invalid_or_oversized_slices_are_rejected_before_post(monkeypatch, slices) -> None:
    posts = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: posts.append(args))

    result = mcp_server.local_ai_artifact(action="slice", artifact_id="artifact-1", slices=slices)

    assert result["success"] is False
    assert not any(path in {"/api/artifact/get", "/api/evidence/get"} for path, _ in posts)


def test_multi_slice_rejects_binary_and_evidence_ids_before_post(monkeypatch) -> None:
    posts = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: posts.append(args))
    slices = [{"offset": 0, "max_chars": 5}]

    binary = mcp_server.local_ai_artifact(action="slice", artifact_id="artifact-1", binary=True, slices=slices)
    evidence = mcp_server.local_ai_artifact(action="slice", artifact_id="E" + "a" * 20, slices=slices)

    assert binary["success"] is False
    assert evidence["success"] is False
    assert not any(path in {"/api/artifact/get", "/api/evidence/get"} for path, _ in posts)


def test_artifact_http_handler_forwards_slices_to_temporary_store(tmp_path, monkeypatch) -> None:
    from local_ai_hub import http_server
    from local_ai_hub.http_route_registry import select_http_routes

    store = ArtifactStore(tmp_path)
    body = "0123456789" * 30
    artifact_id = store.put(body, tenant="http-slice", kind="log")
    response = {}
    handler = object.__new__(http_server.Handler)
    payload = {
        "artifact_id": artifact_id,
        "slices": [{"offset": 10, "max_chars": 20}, {"offset": 150, "max_chars": 30}],
    }
    handler._send = lambda status, payload: response.update(status=status, payload=payload)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(recovery=None, artifacts=store))

    assert "post_artifact_get_1" in select_http_routes("POST", "/api/artifact/get")
    handler._handle_post_artifact_get(payload, "http-slice")

    assert response["status"] == 200
    assert response["payload"]["slices"] == [
        {"offset": 10, "text": body[10:30]},
        {"offset": 150, "text": body[150:180]},
    ]
