from __future__ import annotations

import sys
import types

# Keep module globals patchable while handler methods live in route mixins.
# ruff: noqa: F401

from http.server import BaseHTTPRequestHandler
from typing import Any

from . import __version__
from .http_admin_modes import HTTPAdminModesMixin
from .http_admin import HTTPAdminMixin
from .http_routes_post import HTTPPostRoutesMixin


from . import http_api_request as _http_api_request
from .http_api_request import HttpRequestMixin
from . import http_api_identity as _http_api_identity
from .http_api_identity import HttpIdentityMixin
from . import http_api_auth as _http_api_auth
from .http_api_auth import HttpAuthorizationMixin
from . import http_api_post as _http_api_post
from .http_api_post import HttpPostHelpersMixin
from . import http_api_stream as _http_api_stream
from .http_api_stream import HttpStreamMixin
from . import http_api_get as _http_api_get
from .http_api_get import HttpGetMixin

class Handler(HttpRequestMixin, HttpIdentityMixin, HttpAuthorizationMixin, HttpPostHelpersMixin, HttpStreamMixin, HttpGetMixin, HTTPPostRoutesMixin, HTTPAdminModesMixin, HTTPAdminMixin, BaseHTTPRequestHandler):
    _ADMIN_ACTIONS = {
        "db.query": ({"GET", "POST"}, "/api/db/query", None),
        "debug_traces.list": ({"GET"}, "/api/debug-traces", None),
        "debug_traces.detail": ({"GET"}, "/api/debug-traces/", None),
        "config.read": ({"GET"}, "/api/config", None),
        "config.update": ({"POST"}, "/api/config/update", "update"),
        "config.reset": ({"POST"}, "/api/config/update", "reset"),
        "maintenance.optimize_db": ({"POST"}, "/api/maintenance/optimize_db", None),
        "maintenance.purge_cache": ({"POST"}, "/api/maintenance/purge_cache", None),
        "maintenance.resolve_errors": ({"POST"}, "/api/maintenance/resolve_errors", None),
        "models.list": ({"GET", "POST"}, "/api/models/manage", "list"),
        "models.pull": ({"POST"}, "/api/models/manage", "pull"),
        "models.delete": ({"POST"}, "/api/models/manage", "delete"),
        "bundle.import": ({"POST"}, "/api/bundle/import", None),
    }
    protocol_version = "HTTP/1.1"







    server_version = f"LocalAIHub/{__version__}"





















































































class _HttpRoutesApiModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (_http_api_request, _http_api_identity, _http_api_auth, _http_api_post, _http_api_stream, _http_api_get):
            if hasattr(module, name):
                setattr(module, name, value)

sys.modules[__name__].__class__ = _HttpRoutesApiModuleProxy
