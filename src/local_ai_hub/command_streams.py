"""Thread-safe event and output buffering for concurrent command streams."""
from __future__ import annotations

from dataclasses import dataclass
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
