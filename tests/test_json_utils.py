import json

from local_ai_hub.json_utils import backend_name, dumps, dumps_bytes, loads


def test_dumps_is_compact_and_round_trips_unicode():
    value = {"message": "žluťoučký", "items": [1, {"ok": True}]}

    encoded = dumps(value)

    assert encoded == '{"message":"žluťoučký","items":[1,{"ok":true}]}'
    assert json.loads(encoded) == value


def test_dumps_preserves_explicit_sorting_and_default():
    value = {"b": object(), "a": 1}
    encoded = dumps(value, sort_keys=True, default=str)

    assert encoded.startswith('{"a":1,"b":"<object object at ')
    assert " :" not in encoded
    assert ", " not in encoded
    assert dumps_bytes(value, sort_keys=True, default=str) == encoded.encode("utf-8")


def test_dumps_bytes_matches_dumps_without_decode_round_trip():
    value = {"z": "雪", "a": [1, True, {"β": "café"}]}

    encoded = dumps_bytes(value, sort_keys=True)

    assert encoded == dumps(value, sort_keys=True).encode("utf-8")


def test_codec_reports_backend_and_loads_bytes():
    encoded = dumps({"ok": True})

    assert loads(encoded.encode("utf-8")) == {"ok": True}
    assert backend_name() in {"stdlib", "orjson", "msgspec"}
