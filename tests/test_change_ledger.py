from local_ai_hub.change_ledger import ChangeLedger


def _plan(root, revision="1" * 64, atom="2" * 64):
    return {"success": True, "root": root, "observed_change_set_id": revision,
            "git_visible_observation_complete": True, "inventory_scope": "git_visible_changes",
            "clusters": [{"changes": [{"path": "a.py", "atoms": [{"atom_id": atom, "scope": "unstaged"}]}]}]}


def test_declared_annotation_stales_and_does_not_cross_roots(tmp_path):
    import pytest

    ledger = ChangeLedger(tmp_path / "state")
    plan = _plan("/repo")
    record = {"atom_ids": ["2" * 64], "actor": "agent", "task_id": "task", "status": "reviewed"}
    assert ledger.annotate(plan, expected_revision="1" * 64, record=record)["success"]
    ledger = ChangeLedger(tmp_path / "state")
    ledger.attach(plan)
    assert plan["local_ledger"]["current_annotation_atoms"] == 1
    assert not plan["local_ledger"]["verification_reuse_authorized"]
    stale = _plan("/repo", revision="3" * 64)
    ledger.attach(stale)
    assert stale["local_ledger"]["current_annotation_atoms"] == 0
    other = _plan("/other")
    ledger.attach(other)
    assert other["local_ledger"]["current_annotation_atoms"] == 0
    with pytest.raises(ValueError, match="changed"):
        ledger.annotate(stale, expected_revision="1" * 64, record=record)


def test_annotation_updates_at_retention_limit(tmp_path, monkeypatch):
    import pytest
    from local_ai_hub import change_ledger

    monkeypatch.setattr(change_ledger, "_MAX_RETAINED", 1)
    ledger = ChangeLedger(tmp_path / "state")
    plan = _plan("/repo")
    record = {"atom_ids": ["2" * 64], "actor": "agent", "task_id": "task", "status": "assigned"}
    ledger.annotate(plan, expected_revision="1" * 64, record=record)
    record["status"] = "reviewed"
    ledger.annotate(plan, expected_revision="1" * 64, record=record)
    ledger.attach(plan)
    atom = plan["clusters"][0]["changes"][0]["atoms"][0]
    assert atom["local_annotations"][0]["status"] == "reviewed"
    with pytest.raises(ValueError, match="retention"):
        ledger.annotate(plan, expected_revision="1" * 64, record={**record, "actor": "other"})


def test_watcher_correlation_is_path_scoped_and_not_authority():
    import time
    from unittest.mock import MagicMock
    from local_ai_hub.change_ledger import attach_watcher_candidates

    plan = _plan("/repo")
    preprocessor = MagicMock()
    preprocessor.recent_change_events.return_value = {
        "a.py": {"event": "modified", "observed_at": time.time()},
        "unrelated.py": {"event": "created", "observed_at": time.time()},
    }
    attach_watcher_candidates(plan, preprocessor)
    preprocessor.recent_change_events.assert_called_once_with("/repo", ["a.py"])
    change = plan["clusters"][0]["changes"][0]
    assert change["watcher_candidate"]["relation"] == "recent_same_path_only"
    assert plan["watcher_context"]["candidate_path_count"] == 1
    assert not plan["watcher_context"]["coverage_complete"]
    assert not plan["watcher_context"]["authorship_proven"]
    assert not plan["watcher_context"]["verification_reuse_authorized"]
    assert not _plan("/other").get("watcher_context")
