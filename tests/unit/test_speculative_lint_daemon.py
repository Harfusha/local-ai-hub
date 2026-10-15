"""Deferred protocol regressions; this slice starts no Ruff or child process."""
import io
import json

import pytest

from local_ai_hub.lint_daemon import read_lsp_message


def _frame(message):
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def test_persistent_pipe_reads_multiple_unicode_frames_without_line_assumptions():
    first = {"jsonrpc": "2.0", "id": 1, "result": {"message": "žluťoučký 🚀"}}
    second = {"jsonrpc": "2.0", "id": 2, "result": {"items": []}}
    stream = io.BytesIO(_frame(first) + _frame(second))
    assert read_lsp_message(stream) == first
    assert read_lsp_message(stream) == second
    assert read_lsp_message(stream) is None


@pytest.mark.parametrize("raw", [
    b"Content-Length: 4000001\r\n\r\n",
    b"Content-Length: -1\r\n\r\n",
    b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
    b"Content-Length: 10\r\n\r\n{}",
    b"X" * 2049 + b"\r\n\r\n",
])
def test_invalid_or_oversized_frames_fail_without_unbounded_capture(raw):
    with pytest.raises((ValueError, EOFError)):
        read_lsp_message(io.BytesIO(raw))


def test_partial_pipe_reads_reconstruct_exact_frame():
    class Partial(io.BytesIO):
        def read(self, count=-1):
            return super().read(min(count, 3))
    message = {"id": 9, "result": {"kind": "full", "items": []}}
    assert read_lsp_message(Partial(_frame(message))) == message
