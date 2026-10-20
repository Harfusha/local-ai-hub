"""Socket reads with one absolute deadline across a complete HTTP request head."""
from __future__ import annotations

import io
import time
from typing import Any


class RequestHeadReader(io.RawIOBase):
    def __init__(self, raw: Any, connection: Any):
        super().__init__()
        self.raw = raw
        self.connection = connection
        self.deadline: float | None = None
        self.idle_timeout = 5.0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int | None:
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("HTTP request head deadline expired")
            self.connection.settimeout(min(self.idle_timeout, remaining))
        count = self.raw.readinto(buffer)
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("HTTP request head deadline expired")
        return count

    def close(self) -> None:
        try:
            self.raw.close()
        finally:
            super().close()
