from local_ai_hub.http_event_cursor import (
    MAX_EVENT_SEQUENCE,
    encode_agent_event_cursor,
    parse_agent_event_cursor,
)
from local_ai_hub.http_server import (
    MAX_EVENT_SEQUENCE as HTTP_MAX_EVENT_SEQUENCE,
    _encode_agent_event_cursor,
    _parse_agent_event_cursor,
)


def test_http_server_keeps_cursor_compatibility_names_and_constant():
    assert HTTP_MAX_EVENT_SEQUENCE == MAX_EVENT_SEQUENCE
    assert _encode_agent_event_cursor("task/with space", 5) == encode_agent_event_cursor(
        "task/with space", 5
    )
    assert _parse_agent_event_cursor("task%2Fwith%20space:5") == (
        "task/with space",
        5,
    )


def test_cursor_encoder_clamps_sequence_bounds():
    assert parse_agent_event_cursor(encode_agent_event_cursor("stream", -1)) == (
        "stream",
        0,
    )
    assert parse_agent_event_cursor(
        encode_agent_event_cursor("stream", MAX_EVENT_SEQUENCE + 1)
    ) == ("stream", MAX_EVENT_SEQUENCE)


def test_cursor_parser_rejects_malformed_or_out_of_range_values():
    for value in ("", "stream", ":1", "stream:", "stream:+1", "stream:١", "stream:1\n"):
        assert parse_agent_event_cursor(value) is None
    assert parse_agent_event_cursor(f"stream:{MAX_EVENT_SEQUENCE + 1}") is None
