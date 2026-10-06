from __future__ import annotations

from types import MappingProxyType


POST_ROUTE_REGISTRY: tuple[tuple[str, frozenset[str]], ...] = (
    ("post_telemetry_timeline_1", frozenset(("/api/telemetry/timeline",))),
)

POST_ROUTE_HANDLER_BOUNDARIES = MappingProxyType({
    "post_telemetry_timeline_1": "_handle_post_telemetry_timeline",
})

GET_ROUTE_HANDLER_BOUNDARIES = MappingProxyType({
    "/api/live": "_handle_get_live",
    "/api/live/status": "_handle_get_live_status",
})

def select_get_handler(path: str) -> str | None:
    return GET_ROUTE_HANDLER_BOUNDARIES.get(str(path))


def select_http_routes(method: str, path: str) -> tuple[str, ...]:
    if str(method).upper() != "POST":
        return ()
    normalized_path = str(path)
    return tuple(route_id for route_id, paths in POST_ROUTE_REGISTRY if normalized_path in paths)


def select_post_handler(route_ids: tuple[str, ...]) -> str | None:
    for route_id in route_ids:
        handler_name = POST_ROUTE_HANDLER_BOUNDARIES.get(route_id)
        if handler_name is not None:
            return handler_name
    return None
