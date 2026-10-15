import pytest

from local_ai_hub.http_server import Handler, RequestBodyError, _agent_action_selector


@pytest.mark.parametrize(
    "action",
    [None, 7, True, "Record", " record", "record ", "record-action", "record__item", "_record"],
)
def test_agent_state_post_rejects_noncanonical_action_selectors(action):
    with pytest.raises(RequestBodyError, match="canonical lowercase underscore"):
        Handler._validate_payload("/api/agent-state/memory", {"action": action})


@pytest.mark.parametrize(
    ("path", "action"),
    [
        ("/api/agent-state/memory", "record"),
        ("/api/agent-state/tasks", "create"),
        ("/api/agent-state/verification", "receipt"),
        ("/api/agent-state/events/delta", "export"),
        ("/api/agent-state/blackboard", "update"),
        ("/api/agent-state/incidents", "decision"),
        ("/api/agent-state/swarm/cancel", "cancel"),
    ],
)
def test_agent_state_post_accepts_canonical_action_grammar(path, action):
    Handler._validate_payload(path, {"action": action})


@pytest.mark.parametrize(
    ("path", "default"),
    [
        ("/api/agent-state/events/delta", "export"),
        ("/api/agent-state/blackboard", "get"),
    ],
)
def test_agent_state_post_allows_missing_action_defaults(path, default):
    assert Handler._validate_payload(path, {}) is None
    assert _agent_action_selector({}, default) == default


@pytest.mark.parametrize(
    "action",
    ["cleanup_worktree", "reap_expired", "curate_dataset"],
)
def test_agent_task_post_accepts_current_producer_actions(action):
    assert Handler._validate_payload("/api/agent-state/tasks", {"action": action}) is None


@pytest.mark.parametrize(
    "action",
    ["task_cleanup_worktree", "reap", "zombie_reap", "recover_zombie_tasks", "curate_training_dataset"],
)
def test_agent_task_post_rejects_unadvertised_semantic_aliases(action):
    with pytest.raises(RequestBodyError, match="unknown task action"):
        Handler._validate_payload("/api/agent-state/tasks", {"action": action})


def test_agent_task_post_keeps_unknown_canonical_action_as_domain_error():
    with pytest.raises(RequestBodyError, match="unknown task action"):
        Handler._validate_payload("/api/agent-state/tasks", {"action": "future_action"})


def test_agent_verification_post_uses_http_export_selector():
    Handler._validate_payload("/api/agent-state/verification", {"action": "export"})
    with pytest.raises(RequestBodyError, match="unknown verification action"):
        Handler._validate_payload("/api/agent-state/verification", {"action": "verify_export"})


def test_memory_payload_helper_rejects_malformed_action_without_coercion():
    handler = object.__new__(Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    assert handler._bind_memory_payload({"action": ["record"]}) is False
    assert responses[0][0] == 400
    assert "canonical lowercase underscore" in responses[0][1]["error"]


@pytest.mark.parametrize("binder_name", ["_bind_memory_payload", "_bind_task_event_payload", "_bind_task_board_payload"])
def test_agent_state_bind_helpers_reject_non_string_actions(binder_name):
    handler = object.__new__(Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    assert getattr(handler, binder_name)({"action": ["get"]}) is False
    assert responses[0][0] == 400


def test_blackboard_payload_helper_keeps_unknown_canonical_action_as_domain_error():
    handler = object.__new__(Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    assert handler._bind_task_board_payload({"action": "future_action"}) is False
    assert responses[0][0] == 400
    assert responses[0][1]["error"] == "unknown blackboard action"


@pytest.mark.parametrize("action", ["put", "read", "remove", "blackboard_update"])
def test_blackboard_payload_helper_rejects_unadvertised_semantic_aliases(action):
    handler = object.__new__(Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    assert handler._bind_task_board_payload({"action": action}) is False
    assert responses[0][0] == 400
    assert responses[0][1]["error"] == "unknown blackboard action"
