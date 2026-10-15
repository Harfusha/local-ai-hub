import pytest

from local_ai_hub.agent_blackboard import BlackboardSection, merge_sections


def test_different_sections_never_merge():
    first = BlackboardSection("a", "first", "agent", {"agent": 1}, 1.0, 1)
    second = BlackboardSection("b", "second", "agent", {"agent": 2}, 2.0, 2)
    with pytest.raises(ValueError, match="different names"):
        merge_sections(first, second)
