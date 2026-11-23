"""Persistent In-Memory Shared Buffer Pool for Zero-Copy IPC.

Pre-allocates reusable shared memory slots to avoid repeated Windows kernel
CreateFileMapping/OpenFileMapping syscall overhead during high-frequency IPC
(embeddings exchange, context transfers, telemetry).

Features:
- Fixed-capacity pre-allocated buffer slots.
- Active memoryview reference tracking with explicit release (prevents Windows BufferError).
- Thread-safe acquisition and recycling.
- Graceful cleanup and teardown.
"""

from __future__ import annotations

import logging
import threading
import time
# from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Any

logger = logging.getLogger(__name__)


class PooledBufferSlot:
    """A single reusable memory slot inside PersistentSharedMemoryPool."""

    def __init__(self, slot_id: int, name: str, size: int, shm: shared_memory.SharedMemory) -> None:
        self.slot_id = slot_id
        self.name = name
        self.size = size
        self._shm = shm
        self._in_use = False
        self._active_views: list[memoryview] = []
        self._lock = threading.Lock()

    def write(self, data: bytes | bytearray | memoryview) -> int:
        """Write binary data into slot with 4-byte header length."""
        n = len(data)
        if n + 4 > self.size:
            raise ValueError(f"Data size {n} bytes exceeds slot capacity {self.size - 4} bytes")

        buf = self._shm.buf
        # Write 4-byte length prefix (big-endian)
        buf[0:4] = n.to_bytes(4, byteorder="big")
        # Write payload
        buf[4:4 + n] = data
        return n

    def read_bytes(self) -> bytes:
        """Read active payload as bytes."""
        buf = self._shm.buf
        n = int.from_bytes(buf[0:4], byteorder="big")
        if n > self.size - 4 or n < 0:
            return b""
        return bytes(buf[4:4 + n])

    def get_view(self) -> memoryview:
        """Get tracked zero-copy memoryview of the payload slice."""
        buf = self._shm.buf
        n = int.from_bytes(buf[0:4], byteorder="big")
        if n > self.size - 4 or n < 0:
            n = 0
        v = memoryview(buf)[4:4 + n]
        with self._lock:
            self._active_views.append(v)
        return v

    def release_views(self) -> None:
        """Explicitly release all exported memoryviews before pool recycle/close."""
        with self._lock:
            for v in self._active_views:
                try:
                    v.release()
                except Exception:
                    pass
            self._active_views.clear()

    def close(self) -> None:
        """Cleanly close underlying shared memory segment."""
        self.release_views()
        try:
            self._shm.close()
            self._shm.unlink()
        except Exception as exc:
            logger.debug("Failed closing/unlinking SHM slot %s: %s", self.name, exc)


class PersistentSharedMemoryPool:
    """Thread-safe pool of reusable shared memory slots for zero-copy IPC."""

    def __init__(
        self,
        pool_name: str = "local_ai_shm_pool",
        num_slots: int = 4,
        slot_size_bytes: int = 1024 * 1024,  # 1MB default
    ) -> None:
        self.pool_name = pool_name
        self.num_slots = num_slots
        self.slot_size_bytes = slot_size_bytes
        self._slots: list[PooledBufferSlot] = []
        self._lock = threading.Lock()
        self._closed = False

        self._initialize_slots()

    def _initialize_slots(self) -> None:
        """Pre-allocate all shared memory slots."""
        for i in range(self.num_slots):
            slot_name = f"{self.pool_name}_{i}"
            # Clean up any stale segment from previous runs
            try:
                stale = shared_memory.SharedMemory(name=slot_name)
                stale.close()
                stale.unlink()
            except Exception:
                pass

            shm = shared_memory.SharedMemory(name=slot_name, create=True, size=self.slot_size_bytes)
            slot = PooledBufferSlot(slot_id=i, name=slot_name, size=self.slot_size_bytes, shm=shm)
            self._slots.append(slot)

    def acquire_slot(self, timeout_seconds: float = 2.0) -> PooledBufferSlot:
        """Acquire an available buffer slot from pool with timeout."""
        start_t = time.time()
        while time.time() - start_t < timeout_seconds:
            with self._lock:
                if self._closed:
                    raise RuntimeError("PersistentSharedMemoryPool is closed")
                for slot in self._slots:
                    if not slot._in_use:
                        slot._in_use = True
                        return slot
            time.sleep(0.01)

        raise TimeoutError(f"No free SHM slots available in pool '{self.pool_name}' within {timeout_seconds}s")

    def release_slot(self, slot: PooledBufferSlot) -> None:
        """Recycle slot back to available status after releasing active views."""
        slot.release_views()
        with self._lock:
            slot._in_use = False

    def close(self) -> None:
        """Close and unlink all slots in pool."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for slot in self._slots:
                slot.close()
            self._slots.clear()

    def __enter__(self) -> PersistentSharedMemoryPool:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
