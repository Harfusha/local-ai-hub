from __future__ import annotations

from typing import Any


def probe_hub_status(client: Any, *, timeout: float = 15.0) -> dict[str, Any]:
    """Keep a healthy hub distinct from an unavailable diagnostic status payload."""
    try:
        reachable = bool(client._online())
    except Exception:
        reachable = False
    try:
        response = client.get("/v1/live/status?light=1", timeout=timeout)
    except Exception:
        response = {}
    status = dict(response) if isinstance(response, dict) else {}
    return {
        "hub_online": reachable or bool(status.get("hub_online", False)),
        "status_available": bool(status.get("hub_online", False)),
        "status": status,
    }
