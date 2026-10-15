import pytest

from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.http_server import _parse_memory_scope


@pytest.mark.parametrize("value", ["code", "project", "repo", "workspace", "user",
                                  "GLOBAL", " global ", False, 0, [], {}])
def test_http_memory_scope_rejects_noncanonical_values(value):
    with pytest.raises(ValueError):
        _parse_memory_scope(value)


def test_http_memory_scope_preserves_absence_and_canonical_values():
    assert _parse_memory_scope(None) is None
    assert _parse_memory_scope("") is None
    for scope in AgentScope:
        assert _parse_memory_scope(scope.value) is scope
