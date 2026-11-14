"""Thread-safe event and output buffering for concurrent command streams."""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import re
import threading
import time
from typing import Any, Callable


@dataclass(frozen=True)
class MultiplexEvent:
    source_id: str
    stream_name: str
    text: str
    timestamp: float
    sequence: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "stream_name": self.stream_name,
            "text": self.text,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
        }


class StreamMultiplexer:
    """Thread-safe stream multiplexer that coordinates concurrent output streams

    from parallel workers/tests, preventing line-tearing, interleaving lines,
    and tagging each line with its source and stream identity.
    """

    def __init__(self, *, clock_fn: Callable[[], float] | None = None) -> None:
        self._lock = threading.Lock()
        self._events: list[MultiplexEvent] = []
        self._buffers: dict[tuple[str, str], list[str]] = {}
        self._outputs: dict[str, dict[str, list[str]]] = {}
        self._sequence = 0
        self._clock_fn = clock_fn or time.monotonic
        self._subscribers: list[Callable[[MultiplexEvent], None]] = []

    def write(self, source_id: str, stream_name: str, chunk: str) -> list[MultiplexEvent]:
        """Atomically buffer and emit complete lines for a source stream."""
        if not chunk:
            return []
        emitted: list[MultiplexEvent] = []
        key = (source_id, stream_name)
        with self._lock:
            buf = self._buffers.setdefault(key, [])
            buf.append(chunk)
            full_text = "".join(buf)
            lines = full_text.splitlines(keepends=True)
            if not lines:
                return []
            if not lines[-1].endswith(("\n", "\r")):
                self._buffers[key] = [lines.pop()]
            else:
                self._buffers[key] = []

            for line in lines:
                stripped_line = line.rstrip("\r\n")
                self._sequence += 1
                ev = MultiplexEvent(
                    source_id=source_id,
                    stream_name=stream_name,
                    text=stripped_line,
                    timestamp=self._clock_fn(),
                    sequence=self._sequence,
                )
                self._events.append(ev)
                source_streams = self._outputs.setdefault(source_id, {})
                source_streams.setdefault(stream_name, []).append(stripped_line)
                emitted.append(ev)

        for ev in emitted:
            for sub in self._subscribers:
                try:
                    sub(ev)
                except Exception:
                    pass
        return emitted

    def flush(self, source_id: str | None = None) -> list[MultiplexEvent]:
        """Flush any pending partial lines for a specific source or all sources."""
        emitted: list[MultiplexEvent] = []
        with self._lock:
            keys = [k for k in list(self._buffers.keys()) if source_id is None or k[0] == source_id]
            for key in keys:
                pending = "".join(self._buffers.get(key, []))
                self._buffers[key] = []
                if pending:
                    for line in pending.splitlines():
                        if not line:
                            continue
                        self._sequence += 1
                        ev = MultiplexEvent(
                            source_id=key[0],
                            stream_name=key[1],
                            text=line,
                            timestamp=self._clock_fn(),
                            sequence=self._sequence,
                        )
                        self._events.append(ev)
                        source_streams = self._outputs.setdefault(key[0], {})
                        source_streams.setdefault(key[1], []).append(line)
                        emitted.append(ev)

        for ev in emitted:
            for sub in self._subscribers:
                try:
                    sub(ev)
                except Exception:
                    pass
        return emitted

    def get_source_output(self, source_id: str, stream_name: str | None = None) -> str:
        with self._lock:
            streams = self._outputs.get(source_id, {})
            if stream_name is not None:
                return "\n".join(streams.get(stream_name, []))
            lines: list[str] = []
            for ev in self._events:
                if ev.source_id == source_id:
                    lines.append(ev.text)
            return "\n".join(lines)

    def get_events(self, source_id: str | None = None) -> list[MultiplexEvent]:
        with self._lock:
            if source_id is None:
                return list(self._events)
            return [ev for ev in self._events if ev.source_id == source_id]

    def format_unified(self, *, tag_prefix: bool = True) -> str:
        with self._lock:
            events = list(self._events)
        if not tag_prefix:
            return "\n".join(ev.text for ev in events)
        return "\n".join(f"[{ev.source_id}:{ev.stream_name}] {ev.text}" for ev in events)

    def subscribe(self, callback: Callable[[MultiplexEvent], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+"),
    re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{16,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(aws_secret_access_key\s*=\s*)([^\s]+)"),
]

def _redact_secrets(text: str) -> str:
    if not text:
        return ""
    res = text
    for pat in _SECRET_PATTERNS:
        if pat.groups == 2:
            res = pat.sub(r"\1***", res)
        elif pat.groups == 1:
            res = pat.sub(r"\1***", res)
        else:
            res = pat.sub("***REDACTED_SECRET***", res)
    return res


class _BoundedStreamBuffer:
    """Bounded rolling buffer that retains recent output within character and byte limits."""

    def __init__(self, max_chars: int, max_bytes: int = 8_000_000, redact: bool = True):
        self.max_chars = max(1024, int(max_chars))
        self.max_bytes = max(1024, int(max_bytes))
        self.chunks: deque[str] = deque()
        self.total_chars = 0
        self.total_bytes = 0
        self.total_lines = 0
        self.discarded_chars = 0
        self.discarded_bytes = 0
        self.lock = threading.Lock()
        self.redact = redact

    @staticmethod
    def _encoded_size(text: str) -> int:
        return len(text.encode("utf-8", errors="replace"))

    @classmethod
    def _drop_prefix_bytes(cls, text: str, byte_limit: int) -> tuple[str, int, int]:
        """Return suffix fitting byte_limit, plus removed chars and bytes."""
        size = cls._encoded_size(text)
        if size <= byte_limit:
            return text, 0, 0
        low, high = 0, len(text)
        while low < high:
            middle = (low + high) // 2
            if cls._encoded_size(text[middle:]) <= byte_limit:
                high = middle
            else:
                low = middle + 1
        removed = text[:low]
        return text[low:], low, cls._encoded_size(removed)

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        cleaned = _redact_secrets(chunk) if self.redact else chunk
        discarded_chars = 0
        discarded_bytes = 0
        if len(cleaned) > self.max_chars:
            discarded_chars += len(cleaned) - self.max_chars
            discarded_bytes += self._encoded_size(cleaned[: len(cleaned) - self.max_chars])
            cleaned = cleaned[-self.max_chars:]
        cleaned, removed_chars, removed_bytes = self._drop_prefix_bytes(cleaned, self.max_bytes)
        discarded_chars += removed_chars
        discarded_bytes += removed_bytes
        with self.lock:
            self.total_lines += 1
            self.total_chars += len(cleaned)
            self.total_bytes += self._encoded_size(cleaned)
            self.chunks.append(cleaned)
            while self.chunks and (self.total_chars > self.max_chars or self.total_bytes > self.max_bytes):
                first = self.chunks[0]
                char_excess = max(0, self.total_chars - self.max_chars)
                byte_excess = max(0, self.total_bytes - self.max_bytes)
                first_bytes = self._encoded_size(first)
                if len(first) <= char_excess or first_bytes <= byte_excess:
                    self.chunks.popleft()
                    self.total_chars -= len(first)
                    self.total_bytes -= first_bytes
                    discarded_chars += len(first)
                    discarded_bytes += first_bytes
                else:
                    if char_excess:
                        removed = first[:char_excess]
                        kept = first[char_excess:]
                        removed_bytes = self._encoded_size(removed)
                    else:
                        kept, removed_chars, removed_bytes = self._drop_prefix_bytes(first, max(0, first_bytes - byte_excess))
                        removed = first[:removed_chars]
                    self.chunks[0] = kept
                    self.total_chars -= len(removed)
                    self.total_bytes -= removed_bytes
                    discarded_chars += len(removed)
                    discarded_bytes += removed_bytes
            self.discarded_chars += discarded_chars
            self.discarded_bytes += discarded_bytes

    def getvalue(self) -> str:
        with self.lock:
            return "".join(self.chunks)[-self.max_chars:]

    def write(self, chunk: str) -> None:
        self.append(chunk)

    def peek(self, chars: int = 500) -> str:
        if chars <= 0:
            return ""
        with self.lock:
            if not self.chunks:
                return ""
            collected: list[str] = []
            collected_len = 0
            for chunk in reversed(self.chunks):
                collected.append(chunk)
                collected_len += len(chunk)
                if collected_len >= chars:
                    break
            joined = "".join(reversed(collected))
            return joined[-chars:]
