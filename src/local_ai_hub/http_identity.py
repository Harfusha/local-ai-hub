"""Canonical HTTP principal selection shared by server and local clients."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


def request_principal_tenant(config: dict[str, Any], path: str) -> str:
    security = config.get("security", {})
    if not isinstance(security, dict):
        security = {}
    configured = str(
        security.get("api_token_tenant", "")
        or security.get("api_token_principal", "") or ""
    ).strip()
    if configured:
        return configured
    route = urlsplit(path).path
    if security.get("api_token") or route.startswith(("/api/agent-state/", "/api/agent_state/")):
        fallback = "api-token-default"
    else:
        fallback = "http-default"
    if route.startswith("/api/browser/") or route == "/api/vision/review":
        browser = config.get("browser_bridge", {})
        if isinstance(browser, dict):
            return str(browser.get("tenant", fallback) or fallback)
    return fallback
