from __future__ import annotations

from importlib import import_module
from typing import Any


class _HttpServerProxy:
    """Forward reads and writes to the single HTTP server module.

    A temporary assignment to the proxy must not leave a shadow attribute
    behind after restoration (notably APP and security configuration).
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        server = import_module(".http_server", __package__)
        return getattr(server, name)

    def __setattr__(self, name: str, value: Any) -> None:
        server = import_module(".http_server", __package__)
        setattr(server, name, value)

    def __delattr__(self, name: str) -> None:
        server = import_module(".http_server", __package__)
        delattr(server, name)


services_module = _HttpServerProxy()
