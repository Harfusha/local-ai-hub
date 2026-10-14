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


def test_blackboard_cas_conflict_with_expected_etag(tmp_path):
    board = BlackboardStore(tmp_path / "test.sqlite")
    board.update("b1", "sec1", {"val": "initial"}, author="agent1")
    current = board.get("b1", "sec1")
    assert current.get("success") is True
    etag = current["section"].get("etag")
    assert etag is not None

    # Update section
    board.update("b1", "sec1", {"val": "second"}, author="agent2")

    # Update with stale etag
    res = board.update("b1", "sec1", {"val": "stale"}, author="agent1", expected_etag=etag)
    assert res.get("success") is False
    assert res.get("conflict") is True


def test_blackboard_cas_success_when_version_matches(tmp_path):
    board = BlackboardStore(tmp_path / "test.sqlite")
    board.update("b1", "sec1", {"val": "A"}, author="agent1")
    current = board.get("b1", "sec1")
    assert current.get("success") is True
    sec = current["section"]

    # Update with matching expected_etag
    etag = sec.get("etag")
    res = board.update("b1", "sec1", {"val": "B"}, author="agent1", expected_etag=etag)
    assert res.get("success") is True
    updated = board.get("b1", "sec1")["section"]
    assert updated["version"] == sec["version"] + 1
    assert updated["content"] == {"val": "B"}
