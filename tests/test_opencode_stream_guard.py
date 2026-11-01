import pytest

from local_ai_hub.opencode_stream_guard import CompletionStreamGuard


def test_stream_confirms_only_complete_done_event_across_arbitrary_chunks():
    guard = CompletionStreamGuard()
    for chunk in (b'data: {"text":"[DONE]"}\r\n\r\n', b'da', b'ta: [DO', b'NE]\r', b'\n\r\n'):
        guard.feed(chunk)
    assert guard.complete()


@pytest.mark.parametrize("payload", [
    b'data: {"text":"[DONE]"}\n\n',
    b'data: [DONE]',
    b'data: [DONE]\n',
    b'event: error\ndata: [DONE]\n\n',
    b'data: [DONE]\n\ndata: extra\n\n',
])
def test_ambiguous_or_malformed_stream_cannot_confirm_completion(payload):
    guard = CompletionStreamGuard()
    guard.feed(payload)
    assert not guard.complete()


def test_bounded_stream_parser_fails_closed_on_oversized_or_invalid_data():
    guard = CompletionStreamGuard(max_line_bytes=32)
    guard.feed(b'x' * 33)
    guard.feed(b'\n\ndata: [DONE]\n\n')
    assert not guard.complete()
    with pytest.raises(TypeError):
        CompletionStreamGuard().feed("not bytes")
