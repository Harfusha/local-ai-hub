import pytest

from local_ai_hub.http_server import Handler, RequestBodyError


@pytest.mark.parametrize("field", ["key", "value", "approver", "sections", "record"])
def test_blackboard_post_rejects_retired_fields_before_binding(field):
    with pytest.raises(RequestBodyError, match="unsupported blackboard field"):
        Handler._validate_payload("/api/agent-state/blackboard", {"action": "update", field: "legacy"})


@pytest.mark.parametrize(
    ("field", "canonical_field"),
    [("key", "section"), ("value", "content"), ("approver", "author"), ("sections", "remote_sections"), ("record", "remote_sections")],
)
def test_blackboard_post_rejects_retired_fields_even_with_canonical_value(field, canonical_field):
    payload = {"action": "update", canonical_field: "current", field: "legacy"}
    with pytest.raises(RequestBodyError, match="unsupported blackboard field"):
        Handler._validate_payload("/api/agent-state/blackboard", payload)


@pytest.mark.parametrize("field", ["key", "value", "approver", "sections", "record"])
def test_blackboard_binder_rejects_retired_fields_before_task_binding(field):
    handler = object.__new__(Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    # _bind_task_payload is deliberately absent: a retired field must fail first.
    assert handler._bind_task_board_payload({"action": "update", field: "legacy"}) is False
    assert responses[0][0] == 400
    assert "unsupported blackboard field" in responses[0][1]["error"]


def test_blackboard_binder_defaults_omitted_board_id_to_task_scope():
    handler = object.__new__(Handler)
    handler._bind_task_payload = lambda payload: True
    handler._require_scoped_task = lambda task_id: task_id
    handler._task_board_id_allowed = lambda board_id, task_id: board_id == task_id
    payload = {"action": "get", "task_id": "task-123"}

    assert handler._bind_task_board_payload(payload) is True
    assert payload["board_id"] == "task-123"


@pytest.mark.parametrize("content", [0, False, [], {}])
def test_blackboard_post_keeps_falsey_canonical_content_untouched(content):
    payload = {"action": "update", "content": content}

    Handler._validate_payload("/api/agent-state/blackboard", payload)
    assert payload["content"] == content
