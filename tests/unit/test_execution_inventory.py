from pathlib import Path

import pytest

from local_ai_hub.agent_task_models import GoalContract
from local_ai_hub.execution_inventory import (
    check_repository_scope, compile_repository_contract, repository_resources,
)


def _contract():
    return {"goal": "review", "slo_profile": {"verified_execution": {
        "inventory": {"scope": "repository", "checks": [{"name": "review"}]},
    }}}


def test_server_compiles_all_in_scope_resources_and_detects_drift(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2", encoding="utf-8")
    contract = GoalContract.from_dict(compile_repository_contract(_contract(), str(tmp_path)))
    assert contract.acceptance_criteria == ("review: a.py", "review: b.py")
    config = contract.slo_profile["verified_execution"]
    assert check_repository_scope(config, str(tmp_path))["complete"]
    (tmp_path / "c.py").write_text("z = 3", encoding="utf-8")
    result = check_repository_scope(config, str(tmp_path))
    assert not result["complete"]
    assert result["added_preview"] == ["c.py"]
    (tmp_path / "b.py").unlink()
    assert check_repository_scope(config, str(tmp_path))["removed_preview"] == ["b.py"]


def test_reject_incomplete_declared_repository_scope(tmp_path: Path):
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "b.py").write_text("b", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"]["resources"] = ["a.py"]
    with pytest.raises(ValueError, match="differ"):
        compile_repository_contract(contract, str(tmp_path))


def test_repository_inventory_refuses_incomplete_inventory(tmp_path: Path):
    (tmp_path / "large.txt").write_bytes(b"x" * 2_000_001)
    with pytest.raises(ValueError, match="incomplete"):
        repository_resources(str(tmp_path))
