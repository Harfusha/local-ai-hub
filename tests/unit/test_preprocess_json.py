import json

import pytest

from local_ai_hub.json_utils import loads_generated_json as _parse_generated_json


def test_parse_generated_json_accepts_a_complete_json_fence() -> None:
    assert _parse_generated_json('```json\n{"purpose":"ok"}\n```') == {"purpose": "ok"}


def test_parse_generated_json_rejects_unfenced_prose() -> None:
    with pytest.raises(json.JSONDecodeError):
        _parse_generated_json('Here is the result: {"purpose":"ok"}')
