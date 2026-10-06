from types import SimpleNamespace

from local_ai_hub.http_server import Handler


def test_trace_request_id_falls_back_to_valid_client_header():
    handler = SimpleNamespace(headers={"X-LocalAI-Request-ID": "req_2ac7b6cb636c"})

    assert Handler._ensure_trace_request_id(handler) == "req_2ac7b6cb636c"
    assert handler._trace_request_id == "req_2ac7b6cb636c"
