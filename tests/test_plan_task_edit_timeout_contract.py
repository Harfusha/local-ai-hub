from local_ai_hub.http_post_repository_analysis import handle_post_plan


class _Handler:
    def __init__(self):
        self.responses = []

    def _send(self, status, body):
        self.responses.append((status, body))


class _Services:
    def plan_task_edit(self, **_kwargs):
        raise TimeoutError("file update lock timed out")


class _App:
    services = _Services()


def test_plan_task_edit_storage_lock_timeout_is_retryable_service_unavailable(tmp_path):
    handler = _Handler()
    payload = {
        "root": str(tmp_path),
        "plan_id": "plan_timeout_test",
        "task_id": "task_timeout_test",
        "task_data": {"title": "Timeout test"},
        "expected_revision": "a" * 64,
    }

    handled = handle_post_plan(handler, payload, "/api/coord/plan_task_edit", _App())

    assert handled is True
    assert len(handler.responses) == 1
    status, body = handler.responses[0]
    assert status == 503
    assert body["success"] is False
    assert body["retryable"] is True
    assert body["terminal"] is True
    assert body["mutation_applied"] is False
