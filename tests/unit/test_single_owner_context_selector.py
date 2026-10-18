import pytest
from local_ai_hub.agent_context import ContextRequest
from local_ai_hub.http_server import Handler, RequestBodyError


@pytest.mark.parametrize("value", [None, False, "", "agent"])
@pytest.mark.parametrize("path", ["/api/context/pack", "/api/agent-state/context"])
def test_context_rejects_retired_generic_identity(path, value):
    with pytest.raises(RequestBodyError, match="identity was removed"):
        Handler._validate_payload(path, {"identity": value})


def test_context_has_explicit_real_scope_fields():
    request = ContextRequest("task", root="/repo", session_id="session", repository_id="project", clone_id="clone", worktree_id="tree", branch="feature")
    assert (request.root, request.task_id, request.session_id) == ("/repo", "task", "session")
    assert (request.repository_id, request.clone_id, request.worktree_id, request.branch) == ("project", "clone", "tree", "feature")
