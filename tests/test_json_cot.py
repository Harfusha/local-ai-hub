"""Tests for Chain-of-Thought extraction in generated JSON."""

from src.local_ai_hub.json_utils import loads_generated_json


def test_loads_generated_json_with_cot_thought():
    raw = '<thought>Architectural backbone for model routing.</thought>\n{"purpose": "router", "symbols": ["predict"]}'
    res = loads_generated_json(raw)
    assert res["purpose"] == "router"
    assert res["architectural_reasoning"] == "Architectural backbone for model routing."


def test_loads_generated_json_plain_json():
    raw = '{"purpose": "service", "symbols": []}'
    res = loads_generated_json(raw)
    assert res["purpose"] == "service"
    assert "architectural_reasoning" not in res
