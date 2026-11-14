"""Pure path-label heuristics for repository topology summaries."""

from __future__ import annotations


def classify_topology_layer(relative_path: str, filename: str) -> str:
    """Return the first matching heuristic layer, preserving existing precedence."""
    lowered = relative_path.lower()
    name = filename.lower()
    if name in {"main.py", "app.py", "cli.py", "__main__.py"}:
        return "entrypoints"
    if any(token in lowered for token in ("route", "controller", "view", "endpoint", "http_", "mcp_", "api/", "api_")):
        return "presentation"
    if any(token in lowered for token in ("service", "orchestrat", "planner", "pipeline", "handler", "manager", "engine", "core")):
        return "core_services"
    if any(token in lowered for token in ("model", "schema", "entity", "types", "event", "state")):
        return "domain_models"
    if any(token in lowered for token in ("db", "storage", "repo", "dao", "client", "cache", "telemetry", "hardware", "sqlite")):
        return "infrastructure"
    return "utilities"
