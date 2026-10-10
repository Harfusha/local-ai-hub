from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from local_ai_hub import http_server


def _run_work_order_post(monkeypatch, request_id: str, payload: dict[str, Any], *, authorized: bool = True):
    journal_calls: list[tuple[str, tuple[Any, ...]]] = []
    submitted: list[dict[str, Any]] = []
    responses: list[tuple[int, dict[str, Any]]] = []
    payload_reads: list[bool] = []

    class _Journal:
        def lookup(self, *args: Any, **_kwargs: Any) -> None:
            journal_calls.append(("lookup", args))
            return None

        def begin(self, *args: Any, **_kwargs: Any) -> dict[str, bool]:
            journal_calls.append(("begin", args))
            return {"claimed": True}

    app = SimpleNamespace(
        config={},
        recovery=_Journal(),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda _tenant, value: submitted.append(dict(value)) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(
        http_server.Handler,
        "_begin_trace",
        lambda self, _path: setattr(self, "_trace_request_id", self.headers.get("X-LocalAI-Request-ID", "")),
    )
    def require_authorized(self) -> bool:
        if not authorized:
            self._send(401, {"success": False, "error": "unauthorized"})
        return authorized

    monkeypatch.setattr(http_server.Handler, "_require_authorized", require_authorized)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda _self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda _self: "tenant")

    def read_json(_self):
        payload_reads.append(True)
        return dict(payload)

    monkeypatch.setattr(http_server.Handler, "_read_json", read_json)
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda _self, _path, _payload: None)
    monkeypatch.setattr(http_server.Handler, "_send", lambda _self, status, data: responses.append((status, data)))
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json", "X-LocalAI-Request-ID": request_id}

    http_server.Handler.do_POST(handler)
    return journal_calls, submitted, responses, payload_reads


@pytest.mark.parametrize("request_id", ["bad id", "x" * 129])
def test_invalid_request_id_is_rejected_before_journal_or_dispatch(monkeypatch, request_id: str) -> None:
    journal, submitted, responses, payload_reads = _run_work_order_post(
        monkeypatch,
        request_id,
        {"action": "submit", "work_id": "work-1", "request_id": "valid-body-id"},
    )

    assert responses[0][0] == 400
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["retryable"] is False
    assert journal == []
    assert submitted == []
    assert payload_reads == []


def test_invalid_request_id_does_not_bypass_authorization(monkeypatch) -> None:
    journal, submitted, responses, _payload_reads = _run_work_order_post(
        monkeypatch,
        "bad id",
        {"action": "submit", "work_id": "work-1"},
        authorized=False,
    )

    assert responses[0][0] == 401
    assert journal == []
    assert submitted == []


def test_request_id_header_wins_over_conflicting_body_request_id(monkeypatch) -> None:
    journal, submitted, responses, _payload_reads = _run_work_order_post(
        monkeypatch,
        "header-request-id",
        {"action": "submit", "work_id": "work-1", "request_id": "body-request-id"},
    )

    assert responses[0][0] == 200
    assert [call[1][0] for call in journal] == ["header-request-id"]
    assert submitted == [{"action": "submit", "work_id": "work-1", "request_id": "body-request-id"}]
