"""Post-extraction implementation tests for helper and future route boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub.http_post_repository_analysis import handle_post_repository_analysis
from local_ai_hub.http_route_registry import (
    POST_ROUTE_HANDLER_BOUNDARIES,
    select_http_routes,
    select_post_handler,
)


class Handler:
    def __init__(self):
        self.responses = []

    def _send(self, status, body):
        self.responses.append((status, body))


def _app(*, enabled=True, repo_state=None, services=None):
    calls = []

    def record(name, *args, **kwargs):
        calls.append((name, args, kwargs))
        return {"route": name}

    deterministic = SimpleNamespace(git_status=lambda root: record("git_status", root)) if enabled else None
    service_methods = {
        "git_diff": lambda *args, **kwargs: record("git_diff", *args, **kwargs),
        "git_history_search": lambda *args, **kwargs: record("git_history_search", *args, **kwargs),
        "find_hotspots": lambda *args, **kwargs: record("find_hotspots", *args, **kwargs),
        "test_matrix": lambda *args, **kwargs: record("test_matrix", *args, **kwargs),
    }
    if services:
        service_methods.update(services)
    return SimpleNamespace(
        deterministic=deterministic,
        repo_state=repo_state,
        services=SimpleNamespace(**service_methods),
    ), calls


@pytest.mark.parametrize(("path", "expected_id"), [
    ("/api/git/status", "post_git_status_1"),
    ("/api/repo/state", "post_repo_state_1"),
    ("/api/git/diff", "post_git_diff_1"),
    ("/api/git/history_search", "post_git_history_search_1"),
    ("/api/repo/hotspots", "post_hotspots_1"),
    ("/api/test_matrix", "post_test_matrix_1"),
])
def test_canonical_routes_keep_exact_single_route_id(path, expected_id):
    assert select_http_routes("POST", path) == (expected_id,)


@pytest.mark.parametrize("path", ["/api/repo_state", "/api/hotspots"])
def test_retired_route_aliases_do_not_select_a_handler(path):
    assert select_http_routes("POST", path) == ()


def test_all_six_route_ids_resolve_to_one_named_handler():
    route_ids = (
        "post_git_status_1",
        "post_repo_state_1",
        "post_git_diff_1",
        "post_git_history_search_1",
        "post_hotspots_1",
        "post_test_matrix_1",
    )
    assert {route_id: POST_ROUTE_HANDLER_BOUNDARIES[route_id] for route_id in route_ids} == {
        route_id: "_handle_post_repository_analysis" for route_id in route_ids
    }
    assert select_post_handler(("post_git_status_1", "post_test_matrix_1")) == "_handle_post_repository_analysis"


@pytest.mark.parametrize(("route_id", "payload", "expected_call"), [
    ("post_git_status_1", {"root": "r"}, ("git_status", ("r",), {})),
    ("post_git_diff_1", {"root": "r", "path": "a.py", "staged": False, "max_lines": 8},
     ("git_diff", ("r",), {"path": "a.py", "staged": False, "max_lines": 8})),
    ("post_git_history_search_1", {
        "root": "r", "query": "needle", "max_commits": 3,
        "author": "Ada", "since": "2026-01-01", "until": "2026-01-31T23:00:00Z",
        "path": "src/a.py",
    }, ("git_history_search", ("r", "needle"), {
        "max_commits": 3, "author": "Ada", "since": "2026-01-01",
        "until": "2026-01-31T23:00:00Z", "path": "src/a.py",
    })),
    ("post_hotspots_1", {"root": "r", "days": 5, "limit": 2},
     ("find_hotspots", ("r",), {"days": 5, "limit": 2})),
    ("post_test_matrix_1", {"root": "r"}, ("test_matrix", ("r",), {})),
])
def test_deterministic_routes_preserve_arguments_and_response(route_id, payload, expected_call):
    app, calls = _app()
    handler = Handler()
    assert handle_post_repository_analysis(handler, payload, (route_id,), app) is True
    assert calls == [expected_call]
    assert handler.responses == [(200, {"route": expected_call[0]})]


def test_disabled_engine_returns_explicit_failure_body():
    app, calls = _app(enabled=False)
    handler = Handler()
    handled = handle_post_repository_analysis(handler, {}, ("post_git_diff_1",), app)
    assert handled is True
    assert calls == []
    assert handler.responses == [(200, {"success": False, "error": "deterministic engine disabled"})]


@pytest.mark.parametrize(("field", "value"), [
    ("days", True), ("days", "5"), ("days", 0), ("days", 3651),
    ("limit", True), ("limit", "2"), ("limit", 0), ("limit", 51),
])
def test_hotspot_route_rejects_noncanonical_bounds_before_service(field, value):
    app, calls = _app()
    handler = Handler()
    assert handle_post_repository_analysis(
        handler, {"root": "r", field: value}, ("post_hotspots_1",), app,
    ) is True
    assert calls == []
    status, body = handler.responses[0]
    assert status == 400
    assert body["success"] is False
    assert field in body["error"]
    assert body["terminal"] is True
    assert body["retryable"] is False


@pytest.mark.parametrize("payload", [
    {"root": "r", "query": 7},
    {"root": "r", "query": "needle", "max_commits": True},
    {"root": "r", "query": "needle", "since": "yesterday"},
])
def test_history_route_rejects_noncanonical_filters_before_service(payload):
    app, calls = _app()
    handler = Handler()
    assert handle_post_repository_analysis(handler, payload, ("post_git_history_search_1",), app) is True
    assert calls == []
    assert handler.responses[0][0] == 400


def test_repo_state_fallback_error_and_missing_tracker_bodies():
    class BrokenTracker:
        def fingerprint(self, root):
            raise RuntimeError("hidden by legacy route")

    for tracker, expected in [
        (BrokenTracker(), {"success": False, "error": "repo state unavailable", "error_code": "repo_state_unavailable"}),
        (None, {"success": False, "error": "repo_state tracker unavailable"}),
    ]:
        app, _ = _app(repo_state=tracker)
        handler = Handler()
        assert handle_post_repository_analysis(handler, {"root": "r"}, ("post_repo_state_1",), app)
        assert handler.responses == [(200, expected)]


def test_conversion_errors_escape_to_do_post_central_error_translation():
    app, calls = _app()
    handler = Handler()
    with pytest.raises(ValueError):
        handle_post_repository_analysis(handler, {"max_lines": "bad"}, ("post_git_diff_1",), app)
    assert calls == []
    assert handler.responses == []


def test_unrelated_route_is_not_consumed_and_family_priority_is_stable():
    app, calls = _app()
    handler = Handler()
    assert not handle_post_repository_analysis(handler, {}, ("post_config_update_1",), app)
    assert handle_post_repository_analysis(
        handler, {}, ("post_test_matrix_1", "post_git_status_1"), app
    )
    assert calls == [("git_status", ("." ,), {})]
    assert handler.responses == [(200, {"route": "git_status"})]
