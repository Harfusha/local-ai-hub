from __future__ import annotations

import math
import pytest
from local_ai_hub import json_utils


def test_loads_handles_utf8_bom_in_bytes_and_str(monkeypatch):
    bom_bytes = b"\xef\xbb\xbf{\"status\": \"ok\"}"
    bom_str = "\ufeff{\"status\": \"ok\"}"

    # Test with current active backend
    assert json_utils.loads(bom_bytes) == {"status": "ok"}
    assert json_utils.loads(bom_str) == {"status": "ok"}

    # Test with orjson specifically (if present) to verify orjson BOM crash is avoided
    if json_utils._orjson is not None:
        monkeypatch.setattr(json_utils, "_msgspec", None)
        assert json_utils.loads(bom_bytes) == {"status": "ok"}

    # Test with stdlib fallback
    monkeypatch.setattr(json_utils, "_orjson", None)
    monkeypatch.setattr(json_utils, "_msgspec", None)
    assert json_utils.loads(bom_bytes) == {"status": "ok"}
    assert json_utils.loads(bom_str) == {"status": "ok"}


def test_loads_handles_memoryview(monkeypatch):
    raw = b'{"items": [1, 2, 3]}'
    view = memoryview(raw)

    assert json_utils.loads(view) == {"items": [1, 2, 3]}

    # Test stdlib fallback specifically (which natively rejects memoryview with TypeError)
    monkeypatch.setattr(json_utils, "_orjson", None)
    monkeypatch.setattr(json_utils, "_msgspec", None)
    assert json_utils.loads(view) == {"items": [1, 2, 3]}


def test_safe_floats_sanitizes_nan_and_infinity_in_dumps_and_dumps_bytes(monkeypatch):
    data = {
        "val_nan": float("nan"),
        "val_inf": float("inf"),
        "val_neginf": float("-inf"),
        "normal": 42.5,
    }

    # Under stdlib fallback, safe_floats=True must produce valid JSON nulls
    monkeypatch.setattr(json_utils, "_orjson", None)
    monkeypatch.setattr(json_utils, "_msgspec", None)

    dumped_str = json_utils.dumps(data, safe_floats=True)
    assert dumped_str == '{"val_nan":null,"val_inf":null,"val_neginf":null,"normal":42.5}'
    # verify it round-trips strictly without non-standard NaN tokens
    assert "NaN" not in dumped_str
    assert "Infinity" not in dumped_str

    dumped_bytes = json_utils.dumps_bytes(data, safe_floats=True)
    assert dumped_bytes == b'{"val_nan":null,"val_inf":null,"val_neginf":null,"normal":42.5}'


def test_sanitize_value_detects_and_guards_circular_references():
    cyclic_list: list = [1, 2]
    cyclic_list.append(cyclic_list)

    sanitized_list = json_utils.sanitize_value(cyclic_list)
    assert sanitized_list == [1, 2, "[Circular]"]

    cyclic_dict: dict = {"name": "node"}
    cyclic_dict["self"] = cyclic_dict

    sanitized_dict = json_utils.sanitize_value(cyclic_dict)
    assert sanitized_dict == {"name": "node", "self": "[Circular]"}


def test_sanitize_value_max_depth_guard():
    nested: dict = {"depth": 0}
    current = nested
    for i in range(1, 10):
        current["child"] = {"depth": i}
        current = current["child"]

    # Limit max depth to 3
    shallow = json_utils.sanitize_value(nested, max_depth=3)
    assert shallow["child"]["child"]["child"] == "[MaxDepthExceeded]"


def test_dumps_with_safe_floats_and_cycles():
    cyclic_dict: dict = {"nan": float("nan")}
    cyclic_dict["loop"] = cyclic_dict

    res_str = json_utils.dumps(cyclic_dict, safe_floats=True, handle_cycles=True)
    assert res_str == '{"nan":null,"loop":"[Circular]"}'

    res_bytes = json_utils.dumps_bytes(cyclic_dict, safe_floats=True, handle_cycles=True)
    assert res_bytes == b'{"nan":null,"loop":"[Circular]"}'
