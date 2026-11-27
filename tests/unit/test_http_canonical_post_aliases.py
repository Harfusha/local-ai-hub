from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_routes_post import services_module


@pytest.mark.parametrize("path", ["/api/command/flaky_detect", "/api/flaky_detect"])
def test_retired_flaky_detect_paths_return_404_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    responses: list[tuple[int, object]] = []
    services = SimpleNamespace(
        test_flaky_detect=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True}
    )
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(services=services, recovery=None, debug_traces=None),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *args, **kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: pytest.fail("retired route reached authorization")
    handler._begin_trace = lambda *_args, **_kwargs: pytest.fail("retired route began execution")
    handler._claim_recovery = lambda *_args, **_kwargs: pytest.fail("retired route claimed a mutation")
    handler._read_json = lambda: pytest.fail("retired route read the request body")
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_POST()

    assert calls == []
    assert len(responses) == 1
    assert responses[0][0] == 404


def _post_split_changes(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object], service) -> list[tuple[int, object]]:
    responses: list[tuple[int, object]] = []
    monkeypatch.setattr(services_module, "select_http_routes", lambda *_args: ["post_repo_split_changes_1"])
    monkeypatch.setattr(services_module, "_http_mode_gate_error", lambda *_args: None)
    monkeypatch.setattr(
        services_module, "APP",
        SimpleNamespace(config={}, recovery=None, services=SimpleNamespace(split_changes=service)),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/repo/split_changes"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    handler._bind_repository_root_payload = lambda _payload: True
    handler._begin_trace = lambda *_args: None
    handler._read_json = lambda: payload
    handler._send = lambda status, body: responses.append((status, body))
    handler.do_POST()
    return responses


@pytest.mark.parametrize("field", ["paths", "changed_files"])
def test_split_changes_rejects_retired_path_fields(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def service(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"success": True}

    responses = _post_split_changes(monkeypatch, {field: ["src/example.py"]}, service)

    assert called is False
    assert responses[0][0] == 400
    assert responses[0][1]["terminal"] is True
    assert "changed_paths" in responses[0][1]["error"]


def test_split_changes_accepts_canonical_changed_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    responses = _post_split_changes(
        monkeypatch,
        {"changed_paths": ["src/example.py"]},
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    assert responses == [(200, {"success": True})]
    assert calls[0][0][1] == ["src/example.py"]
