"""Encoding and validation for HTTP agent-event cursors."""

from __future__ import annotations

from urllib.parse import quote, unquote


MAX_EVENT_SEQUENCE = (1 << 63) - 1


def encode_agent_event_cursor(stream_id: str, seq: int) -> str:
    return f"{quote(str(stream_id), safe='')}:{max(0, min(int(seq), MAX_EVENT_SEQUENCE))}"


def parse_agent_event_cursor(value: object) -> tuple[str, int] | None:
    raw = str(value or "")
    if not raw or len(raw) > 2048 or "\r" in raw or "\n" in raw:
        return None
    encoded_stream, separator, encoded_seq = raw.rpartition(":")
    if (
        not separator
        or not encoded_stream
        or not encoded_seq.isascii()
        or not encoded_seq.isdecimal()
    ):
        return None
    try:
        stream_id = unquote(encoded_stream)
        seq = int(encoded_seq)
    except (TypeError, ValueError, OverflowError):
        return None
    if not stream_id or seq < 0 or seq > MAX_EVENT_SEQUENCE:
        return None
    return stream_id, seq
