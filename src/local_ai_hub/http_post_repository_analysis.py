"""Candidate extracted POST handlers for repository-analysis routes.

Behavior is copied from Handler.do_POST. Keep request gates, parsing, recovery,
tracing, and exception translation in do_POST; this helper owns route bodies.
"""
from __future__ import annotations

from typing import Any, Iterable


_ROUTE_PRIORITY = (
    "post_git_status_1",
    "post_repo_state_1",
    "post_git_diff_1",
    "post_git_history_search_1",
    "post_hotspots_1",
    "post_test_matrix_1",
)


def handle_post_repository_analysis(
    handler: Any,
    payload: dict[str, Any],
    route_ids: Iterable[str],
    app: Any,
) -> bool:
    """Handle one extracted route; return False when route family does not match.

    ``route_ids`` comes from ``select_http_routes``. Branch priority follows the
    matching legacy do_POST chain. Conversion and service exceptions intentionally
    escape so do_POST retains its central error and telemetry behavior.
    """
    matched = set(route_ids)
    route_id = next((candidate for candidate in _ROUTE_PRIORITY if candidate in matched), None)
    if route_id is None:
        return False

    root = str(payload.get("root", "."))
    if route_id == "post_git_status_1":
        if app.deterministic is not None:
            handler._send(200, app.deterministic.git_status(root))
        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    if route_id == "post_repo_state_1":
        tracker = getattr(app, "repo_state", None) or (
            getattr(app.services, "repo_state", None) if getattr(app, "services", None) else None
        )
        if tracker is not None:
            try:
                handler._send(200, tracker.fingerprint(root))
            except Exception:
                handler._send(200, {
                    "success": False,
                    "error": "repo state unavailable",
                    "error_code": "repo_state_unavailable",
                })
        else:
            handler._send(200, {"success": False, "error": "repo_state tracker unavailable"})
        return True

    if route_id == "post_git_diff_1":
        path = payload.get("path")
        staged = bool(payload.get("staged", False))
        max_lines = int(payload.get("max_lines", 1000))
        if app.deterministic is not None:
            revisions = {key: payload[key] for key in ("rev1", "rev2") if key in payload}
            handler._send(200, app.services.git_diff(root, path=path, staged=staged, max_lines=max_lines, **revisions))
        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    if route_id == "post_git_history_search_1":
        query = str(payload.get("query", ""))
        max_commits = int(payload.get("max_commits", 20))
        if app.deterministic is not None:
            handler._send(200, app.services.git_history_search(root, query, max_commits=max_commits))
        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    if route_id == "post_hotspots_1":
        days = int(payload.get("days", 30))
        limit = int(payload.get("limit", 20))
        if app.deterministic is not None:
            handler._send(200, app.services.find_hotspots(root, days=days, limit=limit))
        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    if route_id == "post_test_matrix_1":
        if app.deterministic is not None:
            handler._send(200, app.services.test_matrix(root))
        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    return False
