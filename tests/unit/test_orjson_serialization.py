import json
import pytest
from local_ai_hub import json_utils
from local_ai_hub.http_server import _json_bytes

def test_json_dumps_and_dumps_bytes_with_non_str_keys():
    data = {1: "one", 2: "two", "three": 3}
    serialized_str = json_utils.dumps(data)
    loaded = json.loads(serialized_str)
    assert loaded == {"1": "one", "2": "two", "three": 3}

    serialized_bytes = json_utils.dumps_bytes(data)
    assert isinstance(serialized_bytes, bytes)
    assert json.loads(serialized_bytes.decode("utf-8")) == {"1": "one", "2": "two", "three": 3}

def test_json_dumps_sort_keys():
    data = {"b": 2, "a": 1, "c": 3}
    res = json_utils.dumps(data, sort_keys=True)
    assert res == '{"a":1,"b":2,"c":3}'

    res_bytes = json_utils.dumps_bytes(data, sort_keys=True)
    assert res_bytes == b'{"a":1,"b":2,"c":3}'

def test_json_dumps_default_converter():
    class CustomObj:
        def __init__(self, val):
            self.val = val
    data = {"obj": CustomObj("custom")}
    res = json_utils.dumps(data, default=lambda o: o.val)
    assert json.loads(res) == {"obj": "custom"}

    res_bytes = json_utils.dumps_bytes(data, default=lambda o: o.val)
    assert json.loads(res_bytes.decode("utf-8")) == {"obj": "custom"}

def test_http_server_json_bytes_uses_dumps_bytes():
    payload = {"status": "ok", 123: [1, 2, 3]}
    res = _json_bytes(payload)
    assert isinstance(res, bytes)
    assert json.loads(res.decode("utf-8")) == {"status": "ok", "123": [1, 2, 3]}
