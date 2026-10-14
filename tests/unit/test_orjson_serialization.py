import json

from local_ai_hub import json_utils
from local_ai_hub import http_server
from local_ai_hub import mcp_server


def test_http_bytes_use_bytes_serializer_without_string_round_trip(monkeypatch):
    expected = b'{"count":1}'

    def serialize(value):
        assert value == {"count": 1}
        return expected

    monkeypatch.setattr(http_server, "json_dumps_bytes", serialize)
    monkeypatch.setattr(
        http_server,
        "json_dumps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("string path used")),
    )

    assert http_server._json_bytes({"count": 1}) is expected


def test_orjson_compact_paths_enable_non_string_mapping_keys(monkeypatch):
    observed = []

    class FakeOrjson:
        OPT_SORT_KEYS = 1
        OPT_NON_STR_KEYS = 2

        @staticmethod
        def dumps(value, *, option, **_kwargs):
            observed.append(option)
            return json.dumps(
                value,
                sort_keys=bool(option & FakeOrjson.OPT_SORT_KEYS),
                separators=(",", ":"),
            ).encode()

    monkeypatch.setattr(json_utils, "_orjson", FakeOrjson)
    monkeypatch.setattr(json_utils, "_msgspec", None)

    assert json_utils.dumps({1: "one"}) == '{"1":"one"}'
    assert json_utils.dumps_bytes({1: "one"}) == b'{"1":"one"}'
    assert json_utils.dumps({1: "one"}, sort_keys=True) == '{"1":"one"}'
    assert json_utils.dumps_bytes({1: "one"}, sort_keys=True) == b'{"1":"one"}'
    assert json_utils.dumps({"a": 1}, sort_keys=True) == '{"a":1}'
    assert json_utils.dumps_bytes({"a": 1}, sort_keys=True) == b'{"a":1}'
    assert observed == [
        FakeOrjson.OPT_NON_STR_KEYS,
        FakeOrjson.OPT_NON_STR_KEYS,
        FakeOrjson.OPT_NON_STR_KEYS | FakeOrjson.OPT_SORT_KEYS,
        FakeOrjson.OPT_NON_STR_KEYS | FakeOrjson.OPT_SORT_KEYS,
    ]


def test_stdlib_fallback_preserves_sorted_canonical_json(monkeypatch):
    monkeypatch.setattr(json_utils, "_orjson", None)
    monkeypatch.setattr(json_utils, "_msgspec", None)

    assert json_utils.dumps({"b": 2, "a": 1}, sort_keys=True) == '{"a":1,"b":2}'
    assert json_utils.dumps_bytes({"b": 2, "a": 1}, sort_keys=True) == b'{"a":1,"b":2}'


def test_sorted_non_string_keys_keep_stdlib_ordering():
    assert json_utils.dumps_bytes({2: "two", 10: "ten"}, sort_keys=True) == b'{"2":"two","10":"ten"}'


def test_non_string_key_coercion_preserves_duplicate_key_order():
    value = {1: "integer", "1": "string"}

    assert json_utils.dumps_bytes(value) == b'{"1":"integer","1":"string"}'


def test_mcp_wire_view_keeps_json_text_as_string():
    wire = mcp_server._mcp_wire_view({"ok": True}, structured=False)

    assert wire["content"][0]["type"] == "text"
    assert wire["content"][0]["text"] == '{"ok":true}'
    assert isinstance(wire["content"][0]["text"], str)
