import json

from local_ai_hub.http_server import _json_bytes


def test_http_json_bytes_are_compact_without_changing_value():
    value = {"items": [{"name": "žluťoučký", "ok": True}], "count": 1}

    encoded = _json_bytes(value).decode("utf-8")

    assert encoded == '{"items":[{"name":"žluťoučký","ok":true}],"count":1}'
    assert json.loads(encoded) == value
