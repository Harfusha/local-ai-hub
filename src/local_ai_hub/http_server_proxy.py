from __future__ import annotations

from importlib import import_module
from typing import Any


class _HttpServerProxy:
    def __getattr__(self, name: str) -> Any:
        server = import_module(".http_server", __package__)
        return getattr(server, name)


services_module = _HttpServerProxy()
