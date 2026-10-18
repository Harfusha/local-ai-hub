from __future__ import annotations

from local_ai_hub.dashboard import DASHBOARD_HTML


def test_missing_project_cleanup_uses_long_bounded_request_timeout() -> None:
    start = DASHBOARD_HTML.index("async function confirmCleanMissing()")
    end = DASHBOARD_HTML.index("async function ", start + 1)
    cleanup_handler = DASHBOARD_HTML[start:end]

    assert "post('/api/preprocess',{action:'cleanup_deleted'},{timeoutMs:120000})" in cleanup_handler

    post_start = DASHBOARD_HTML.index("async function post(path,payload")
    post_end = DASHBOARD_HTML.index("\n", post_start)
    post_helper = DASHBOARD_HTML[post_start:post_end]
    assert "apiFetch(path,{...requestOptions,method:'POST'" in post_helper
