"""Test Compare-And-Swap (CAS) optimistic concurrency on agent blackboard and memory."""
import pytest
from local_ai_hub.agent_blackboard import BlackboardStore


def test_blackboard_cas_conflict_with_expected_version(tmp_path):
    board = BlackboardStore(tmp_path / "test.sqlite")
    board.update("b1", "sec1", {"val": 1}, author="agent1")
    current = board.get("b1", "sec1")
    assert current.get("success") is True
    sec = current["section"]
    v1 = sec["version"]

    # Another agent updates the section, advancing version to v2
    board.update("b1", "sec1", {"val": 2}, author="agent2")

    # Original agent tries to update expecting v1 -> must fail with conflict
    res = board.update("b1", "sec1", {"val": 3}, author="agent1", expected_version=v1)
    assert res.get("success") is False
    assert res.get("conflict") is True
    assert res.get("version_conflict") is True
    assert res.get("current_version") == 2
    assert res.get("expected_version") == v1


def test_blackboard_retired_expected_etag_rejected():
    board = object.__new__(BlackboardStore)
    with pytest.raises(TypeError, match="expected_etag"):
        board.update("b1", "sec1", {}, author="agent1", expected_etag="v1")


@pytest.mark.parametrize("value", [True, False, "1", 1.0, -1])
def test_invalid_expected_version_rejects_before_store_access(value):
    board = object.__new__(BlackboardStore)
    with pytest.raises(ValueError, match="expected_version"):
        board.update("b1", "sec1", {}, author="agent1", expected_version=value)


def test_blackboard_cas_success_when_version_matches(tmp_path):
    board = BlackboardStore(tmp_path / "test.sqlite")
    board.update("b1", "sec1", {"val": "A"}, author="agent1")
    current = board.get("b1", "sec1")
    assert current.get("success") is True
    sec = current["section"]

    res = board.update("b1", "sec1", {"val": "B"}, author="agent1", expected_version=sec["version"])
    assert res.get("success") is True
    updated = board.get("b1", "sec1")["section"]
    assert updated["version"] == sec["version"] + 1
    assert updated["content"] == {"val": "B"}
