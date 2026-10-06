from local_ai_hub.http_server import _parse_include_body


def test_parse_include_body_accepts_only_strict_values():
    assert _parse_include_body(False) is False
    assert _parse_include_body(True) is True
    assert _parse_include_body("false") is None
    assert _parse_include_body("true") is None
    assert _parse_include_body(0) is None

    assert _parse_include_body(None, query=True) is False
    assert _parse_include_body("false", query=True) is False
    assert _parse_include_body("true", query=True) is True
    assert _parse_include_body("False", query=True) is None
    assert _parse_include_body("1", query=True) is None