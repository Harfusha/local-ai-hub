import json

from local_ai_hub.json_utils import dumps


def test_dumps_is_compact_and_round_trips_unicode():
    value = {"message": "žluťoučký", "items": [1, {"ok": True}]}

    encoded = dumps(value)

    assert encoded == '{"message":"žluťoučký","items":[1,{"ok":true}]}'
    assert json.loads(encoded) == value


def test_dumps_preserves_explicit_sorting_and_default():
    encoded = dumps({"b": object(), "a": 1}, sort_keys=True, default=str)

    assert encoded.startswith('{"a":1,"b":"<object object at ')
    assert " :" not in encoded
    assert ", " not in encoded
