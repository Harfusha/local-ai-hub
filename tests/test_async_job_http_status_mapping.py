from __future__ import annotations

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_server import _async_job_http_status


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"success": False, "status_code": 423, "retryable": True}, 423),
        ({"success": False, "state": "rejected", "retryable": True}, 429),
        ({"success": False, "state": "conflict", "conflict": True}, 409),
        ({"success": False, "state": "expired"}, 410),
        ({"success": False, "error": "async job not found", "terminal": True, "retryable": False}, 404),
        ({"success": True, "state": "queued"}, 200),
        ({"success": False, "status_code": True}, 200),
    ],
)
def test_async_job_http_status_preserves_contract(response, expected):
    assert _async_job_http_status(response) == expected


def test_async_job_http_status_defaults_for_non_mapping_result():
    assert _async_job_http_status(["not", "a", "mapping"]) == 200


def test_async_submit_emits_explicit_admission_status(monkeypatch):
    response = {
        "success": False,
        "state": "rejected",
        "status_code": 423,
        "retryable": True,
        "error": "accelerator release is still in progress",
    }

    class Jobs:
        ACTIONS = {"reason"}

        @staticmethod
        def submit(_action, _payload):
            return dict(response)

    class App:
        async_jobs = Jobs()

    monkeypatch.setattr(http_server, "APP", App())
    handler = object.__new__(http_server.Handler)
    handler.headers = {}
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))

    http_server.Handler._handle_post_async_jobs(
        handler, {"action": "submit", "job_action": "reason"}
    )

    assert handler.responses == [(423, {**response, "status_code": 423})]
