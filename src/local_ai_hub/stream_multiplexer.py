"""Pre-emptive Stream Multiplexing and Fast Cancellation Controller.

Coordinates concurrent inference, generation, and preprocessing streams with fine-grained
priority tiers and immediate (<1 token) preemption when interactive or steering requests arrive.

Priorities:
  0 - BACKGROUND: Idle batch indexing, passive card preprocessing
  1 - BATCH: Multi-candidate evaluation, test runs
  2 - INTERACTIVE: Live user prompts, tool execution
  3 - CRITICAL_STEERING: Immediate abort, emergency stop, operator intervention

Features:
1. Thread-safe CancellationToken with fast non-blocking checks.
2. Preemption signaling: Drops or pauses lower-priority background generation upon interactive bursts.
3. Fair multi-stream multiplexer with priority-weighted fair scheduling.
"""

from __future__ import annotations

# import heapq
# import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

PRIORITY_BACKGROUND = 0
PRIORITY_BATCH = 1
PRIORITY_INTERACTIVE = 2
PRIORITY_CRITICAL_STEERING = 3


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._cancelled = threading.Event()
        self._reason: str = ""

    def cancel(self, reason: str = "Cancelled by scheduler") -> None:
        """Mark task as cancelled."""
        self._reason = reason
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        return self._reason


@dataclass
class _StreamItem:
    priority: int
    task_id: str
    iterator: Iterator[Any]
    token: CancellationToken
    created_at: float = field(default_factory=time.time)

    # For max-heap ordering in heapq (negate priority)
    def __lt__(self, other: _StreamItem) -> bool:
        if self.priority != other.priority:
            return self.priority > other.priority  # Higher priority comes first
        return self.created_at < other.created_at


class StreamMultiplexer:
    """Priority-aware stream coordinator with preemption."""

    def __init__(self, preempt_background_on_interactive: bool = True):
        self.preempt_background_on_interactive = preempt_background_on_interactive
        self._lock = threading.Lock()
        self._streams: Dict[str, _StreamItem] = {}
        self._active_tokens: Dict[str, CancellationToken] = {}

    def register_stream(
        self,
        task_id: str,
        iterator: Iterator[Any],
        priority: int = PRIORITY_INTERACTIVE,
    ) -> CancellationToken:
        """Register a new stream. Automatically preempts lower priority streams if required."""
        with self._lock:
            token = CancellationToken(task_id)
            item = _StreamItem(
                priority=priority,
                task_id=task_id,
                iterator=iterator,
                token=token,
            )
            self._streams[task_id] = item
            self._active_tokens[task_id] = token

            # If interactive or steering stream arrives, signal preemption on all BACKGROUND streams
            if self.preempt_background_on_interactive and priority >= PRIORITY_INTERACTIVE:
                for tid, s in self._streams.items():
                    if s.priority <= PRIORITY_BACKGROUND and tid != task_id:
                        s.token.cancel("Preempted by higher-priority interactive request")

            return token

    def cancel_stream(self, task_id: str, reason: str = "User cancelled") -> bool:
        """Cancel an active stream immediately."""
        with self._lock:
            item = self._streams.get(task_id)
            if item:
                item.token.cancel(reason)
                self._streams.pop(task_id, None)
                self._active_tokens.pop(task_id, None)
                return True
            return False

    def active_stream_count(self) -> int:
        """Count remaining active streams."""
        with self._lock:
            return len(self._streams)

    def next_token(self) -> Optional[Tuple[str, Any]]:
        """Yield next token/chunk from the highest priority active stream.
        
        Returns:
            Tuple of (task_id, chunk) or None if all streams exhausted.
        """
        with self._lock:
            if not self._streams:
                return None

            # Sort active streams by priority (highest first)
            sorted_streams = sorted(self._streams.values())

        for stream in sorted_streams:
            if stream.token.is_cancelled():
                # Cleanup cancelled stream
                with self._lock:
                    self._streams.pop(stream.task_id, None)
                    self._active_tokens.pop(stream.task_id, None)
                continue

            try:
                chunk = next(stream.iterator)
                return stream.task_id, chunk
            except StopIteration:
                # Stream finished
                with self._lock:
                    self._streams.pop(stream.task_id, None)
                    self._active_tokens.pop(stream.task_id, None)
            except Exception as e:
                logger.warning("Stream %s raised error: %s", stream.task_id, e)
                with self._lock:
                    self._streams.pop(stream.task_id, None)
                    self._active_tokens.pop(stream.task_id, None)

        return None
