"""Bounded OpenAI-compatible SSE terminal marker validation for a future bridge."""
from __future__ import annotations

import json


class CompletionStreamGuard:
    def __init__(self, *, max_line_bytes: int = 1_048_576, max_event_bytes: int = 2_097_152) -> None:
        if type(max_line_bytes) is not int or type(max_event_bytes) is not int or max_line_bytes < 1 or max_event_bytes < 1:
            raise ValueError("stream limits must be positive integers")
        self._max_line = max_line_bytes
        self._max_event = max_event_bytes
        self._buffer = bytearray()
        self._data: list[str] = []
        self._event_bytes = 0
        self._event_type = ""
        self._invalid = False
        self._done = False

    def feed(self, chunk: bytes) -> None:
        if not isinstance(chunk, bytes):
            raise TypeError("stream chunks must be bytes")
        if self._invalid:
            return
        if len(chunk) > self._max_event:
            self._invalid = True
            return
        self._buffer.extend(chunk)
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                if len(self._buffer) > self._max_line:
                    self._invalid = True
                return
            if end > self._max_line:
                self._invalid = True
                return
            raw = bytes(self._buffer[:end]).removesuffix(b"\r")
            del self._buffer[:end + 1]
            try:
                line = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                self._invalid = True
                return
            if not line:
                self._finish_event()
            elif line.startswith(":"):
                continue
            else:
                if self._done:
                    self._invalid = True
                    return
                field, sep, value = line.partition(":")
                if sep and value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    self._event_type = value
                elif field == "data":
                    self._event_bytes += len(raw)
                    if self._event_bytes > self._max_event:
                        self._invalid = True
                        return
                    self._data.append(value)

    def _finish_event(self) -> None:
        if self._event_type == "error" or (self._done and (self._data or self._event_type)):
            self._invalid = True
        elif self._data:
            payload = "\n".join(self._data)
            if payload == "[DONE]" and self._event_type in ("", "message"):
                self._done = True
            else:
                try:
                    parsed = json.loads(payload)
                    if not isinstance(parsed, dict) or "error" in parsed:
                        self._invalid = True
                except (ValueError, TypeError):
                    self._invalid = True
        self._data.clear()
        self._event_type = ""
        self._event_bytes = 0

    def complete(self) -> bool:
        """Call after upstream EOF; a later chunk can still invalidate the result."""
        return self._done and not self._invalid and not self._buffer and not self._data and not self._event_type
