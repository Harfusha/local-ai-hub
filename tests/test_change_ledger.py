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
