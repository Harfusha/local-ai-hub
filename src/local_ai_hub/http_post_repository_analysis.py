"""Candidate extracted POST handlers for repository-analysis routes.

Behavior is copied from Handler.do_POST. Keep request gates, parsing, recovery,
tracing, and exception translation in do_POST; this helper owns route bodies.
"""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from .deterministic import _git_history_timestamp


def handle_post_plan(handler: Any, payload: dict[str, Any], path: str, app: Any) -> bool:
    """Dispatch canonical repository planner requests without scalar coercion."""
    if not path.startswith("/api/coord/plan_"):
        return False
    from .operation_contracts import operation_contract, validate_operation_arguments
    from .repo_plan.schema_validation import RepoPlanConflictError, RepoPlanNotFoundError

    action = path.removeprefix("/api/coord/")
    actions = operation_contract("local_ai_coord")["actions"]
    if action not in actions:
        handler._send(404, {"success": False, "error": "unknown plan operation",
                            "terminal": True, "retryable": False})
        return True
    # Older MCP transports attach active task paths to every coordination
    # request. They are unrelated task context and must not invalidate the
    # strict file-backed plan contract.
    plan_payload = dict(payload)
    plan_payload.pop("changed_paths", None)
    error = validate_operation_arguments("local_ai_coord", action, plan_payload)
    if error:
        handler._send(400, {"success": False, "error": error, "terminal": True, "retryable": False})
        return True
    arguments = {name: value for name, value in plan_payload.items() if name in actions[action]["allowed"]}
    try:
        result = getattr(app.services, action)(**arguments)
    except RepoPlanConflictError as exc:
        handler._send(409, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
    except RepoPlanNotFoundError as exc:
        handler._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
    except ValueError as exc:
        handler._send(getattr(exc, "status_code", 400), {
            "success": False, "error": str(exc), "terminal": True, "retryable": False})
    else:
        handler._send(200, result)
    return True


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
            revisions = {key: payload[key] for key in ("rev1", "rev2", "base") if key in payload}
            handler._send(200, app.services.git_diff(root, path=path, staged=staged, max_lines=max_lines, **revisions))

        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    if route_id == "post_git_history_search_1":
        query = payload.get("query", "")
        max_commits = payload.get("max_commits", 20)
        filters = {name: payload.get(name) for name in ("author", "since", "until", "path")}
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 512
            or any(ord(char) < 32 or ord(char) == 127 for char in query)
        ):
            handler._send(400, {"success": False, "error": "query must be a bounded literal string", "terminal": True, "retryable": False})
            return True
        if isinstance(max_commits, bool) or not isinstance(max_commits, int) or not 1 <= max_commits <= 100:
            handler._send(400, {"success": False, "error": "max_commits must be an integer from 1 to 100", "terminal": True, "retryable": False})
            return True
        for name, value in filters.items():
            maximum = 256 if name == "author" else 64 if name in {"since", "until"} else 4096
            if value is not None and (
                not isinstance(value, str)
                or len(value) > maximum
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                handler._send(400, {"success": False, "error": f"{name} must be a bounded string", "terminal": True, "retryable": False})
                return True
        try:
            since_epoch, _since = _git_history_timestamp(filters["since"], "since", upper_bound=False)
            until_epoch, _until = _git_history_timestamp(filters["until"], "until", upper_bound=True)
        except (TypeError, ValueError, OverflowError):
            handler._send(400, {"success": False, "error": "since and until must be ISO dates or RFC3339 timestamps", "terminal": True, "retryable": False})
            return True
        if since_epoch is not None and until_epoch is not None and since_epoch > until_epoch:
            handler._send(400, {"success": False, "error": "since must be earlier than or equal to until", "terminal": True, "retryable": False})
            return True
        raw_path = filters["path"]
        if raw_path:
            normalized_path = raw_path.replace("\\", "/")
            path_parts = PurePosixPath(normalized_path).parts
            if (
                normalized_path.startswith("/")
                or PureWindowsPath(raw_path).drive
                or PureWindowsPath(raw_path).is_absolute()
                or any(part in {"..", ""} for part in path_parts)
                or any(ord(char) < 32 or ord(char) == 127 for char in normalized_path)
            ):
                handler._send(400, {"success": False, "error": "path must be a repository-relative literal path", "terminal": True, "retryable": False})
                return True
        if app.deterministic is not None:
            result = app.services.git_history_search(
                root,
                query,
                max_commits=max_commits,
                author=filters["author"],
                since=filters["since"],
                until=filters["until"],
                path=filters["path"],
            )
            result_status = result.get("status_code") if isinstance(result, dict) else None
            status = (
                result_status
                if isinstance(result_status, int) and not isinstance(result_status, bool)
                and 400 <= result_status <= 599
                else 200
            )
            handler._send(status, result)
        else:
            handler._send(200, {"success": False, "error": "deterministic engine disabled"})
        return True

    if route_id == "post_hotspots_1":
        days = payload.get("days", 30)
        limit = payload.get("limit", 20)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
            handler._send(400, {"success": False, "error": "days must be an integer from 1 to 3650", "terminal": True, "retryable": False})
            return True
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            handler._send(400, {"success": False, "error": "limit must be an integer from 1 to 50", "terminal": True, "retryable": False})
            return True
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
