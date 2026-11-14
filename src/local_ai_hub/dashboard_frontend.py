"""Offline static dashboard shell and its allow-listed assets."""

from __future__ import annotations

from importlib.resources import files
from types import MappingProxyType


_ASSETS = MappingProxyType({
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
})

LEGACY_PAGES = (
    ("overview", "Overview", "overview"),
    ("projects", "Projects", "projects"),
    ("commands", "Commands", "agents"),
    ("work", "Requests", "tasks"),
    ("agentos", "Tasks", "tasks"),
    ("coordination", "Coordination", "tasks"),
    ("performance", "Models & search", "models"),
    ("reliability", "Service health", "diagnostics"),
    ("config", "Settings", "settings"),
    ("bundles", "Transfers", "projects"),
    ("events", "Activity", "diagnostics"),
)


def _asset_bytes(name: str) -> bytes:
    return files("local_ai_hub").joinpath("ui_static", name).read_bytes()


def dashboard_frontend_html() -> str:
    return _asset_bytes("index.html").decode("utf-8")


def dashboard_frontend_asset(name: str) -> tuple[str, bytes] | None:
    """Return a packaged frontend asset only for an exact allow-listed name."""
    content_type = _ASSETS.get(name)
    if content_type is None:
        return None
    return content_type, _asset_bytes(name)
