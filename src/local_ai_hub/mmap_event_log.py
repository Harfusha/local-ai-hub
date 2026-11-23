"""Zero-Copy Memory-Mapped Binary Event Log.

High-throughput telemetry and operational audit ring buffer using memory-mapped I/O (mmap),
enabling sub-microsecond logging latency without synchronous disk write syscalls.

Features:
1. Fixed-stride circular ring buffer with monotonic sequence counters.
2. Binary struct packing for timestamps, event types, and payloads.
3. Thread-safe atomic pointer advancement.
4. Clean Windows handle release avoiding locking issues.
"""

from __future__ import annotations

import logging
import mmap
# import os
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

MAGIC = b"MEL1"
# Header: Magic(4s), num_slots(I), slot_size(I), next_seq(Q)
HEADER_FORMAT = "<4sIIQ"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Slot: seq(Q), timestamp(d), event_type(H), payload_len(H)
SLOT_HEADER_FORMAT = "<QdHH"
SLOT_HEADER_SIZE = struct.calcsize(SLOT_HEADER_FORMAT)


@dataclass(frozen=True)
class MmapEvent:
    """Decoded event record from mmap ring buffer."""

    seq: int
    timestamp: float
    event_type: int
    payload: str


class MmapEventLogger:
    """Circular memory-mapped binary event logger."""

    def __init__(self, file_path: str | Path, num_slots: int = 1024, slot_size: int = 256):
        self.path = Path(file_path).resolve()
        self.num_slots = max(16, num_slots)
        self.slot_size = max(SLOT_HEADER_SIZE + 16, slot_size)
        self.max_payload = self.slot_size - SLOT_HEADER_SIZE
        self.total_size = HEADER_SIZE + (self.num_slots * self.slot_size)

        self._lock = threading.Lock()
        self._f = None
        self._mm: Optional[mmap.mmap] = None
        self._init_file()

    def _init_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size < self.total_size:
            with open(self.path, "wb") as f:
                f.write(b"\x00" * self.total_size)

        self._f = open(self.path, "r+b")
        self._mm = mmap.mmap(self._f.fileno(), self.total_size, access=mmap.ACCESS_WRITE)

        # Check or initialize header
        magic, _, _, _ = struct.unpack_from("<4sIIQ", self._mm, 0)
        if magic != MAGIC:
            struct.pack_into(HEADER_FORMAT, self._mm, 0, MAGIC, self.num_slots, self.slot_size, 0)
            self._mm.flush()

    def log_event(self, event_type: int, payload: str | bytes) -> int:
        """Write event directly to mmap slot. Sub-microsecond execution."""
        if isinstance(payload, str):
            p_bytes = payload.encode("utf-8")
        else:
            p_bytes = bytes(payload)

        p_len = min(len(p_bytes), self.max_payload)

        with self._lock:
            if self._mm is None:
                raise ValueError("Logger is closed")

            # Read next sequence
            _, n_slots, s_size, next_seq = struct.unpack_from(HEADER_FORMAT, self._mm, 0)
            curr_seq = next_seq + 1
            slot_idx = next_seq % self.num_slots
            slot_offset = HEADER_SIZE + (slot_idx * self.slot_size)

            now = time.time()
            struct.pack_into(
                SLOT_HEADER_FORMAT,
                self._mm,
                slot_offset,
                curr_seq,
                now,
                int(event_type),
                p_len,
            )
            # Write payload bytes
            self._mm[slot_offset + SLOT_HEADER_SIZE : slot_offset + SLOT_HEADER_SIZE + p_len] = p_bytes[:p_len]

            # Update next_seq in header
            struct.pack_into("<Q", self._mm, 12, curr_seq)

            return curr_seq

    def read_recent(self, limit: int = 10) -> List[MmapEvent]:
        """Read the most recent events from ring buffer."""
        with self._lock:
            if self._mm is None:
                return []

            _, _, _, total_written = struct.unpack_from(HEADER_FORMAT, self._mm, 0)
            if total_written == 0:
                return []

            count = min(limit, min(total_written, self.num_slots))
            events: List[MmapEvent] = []

            for i in range(count):
                seq_to_read = total_written - i
                slot_idx = (seq_to_read - 1) % self.num_slots
                slot_offset = HEADER_SIZE + (slot_idx * self.slot_size)

                seq, ts, ev_type, p_len = struct.unpack_from(SLOT_HEADER_FORMAT, self._mm, slot_offset)
                if seq != seq_to_read:
                    continue
                p_bytes = self._mm[slot_offset + SLOT_HEADER_SIZE : slot_offset + SLOT_HEADER_SIZE + p_len]
                events.append(
                    MmapEvent(
                        seq=seq,
                        timestamp=ts,
                        event_type=ev_type,
                        payload=p_bytes.decode("utf-8", errors="replace"),
                    )
                )

            return events

    def close(self) -> None:
        """Safely close mmap and file descriptors."""
        with self._lock:
            if self._mm:
                try:
                    self._mm.flush()
                    self._mm.close()
                except Exception:
                    pass
                self._mm = None
            if self._f:
                try:
                    self._f.close()
                except Exception:
                    pass
                self._f = None
