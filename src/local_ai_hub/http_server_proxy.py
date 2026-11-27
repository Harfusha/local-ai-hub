from __future__ import annotations

from importlib import import_module
from typing import Any


class _HttpServerProxy:
    def __getattr__(self, name: str) -> Any:
        server = import_module(".http_server", __package__)
        return getattr(server, name)

    def __setattr__(self, name: str, value: Any) -> None:
        server = import_module(".http_server", __package__)
        setattr(server, name, value)


services_module = _HttpServerProxy()
