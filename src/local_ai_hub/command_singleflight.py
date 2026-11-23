from __future__ import annotations

import threading
from typing import Any


class _CommandSingleflightEvent(threading.Event):
    def __init__(self) -> None:
        super().__init__()
        self.owner_result: dict[str, Any] | None = None
