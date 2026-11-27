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


def test_partition_manifest_is_disjoint_complete_and_detects_outside_changes(tmp_path: Path):
    for name in ("a.py", "b.py", "c.py", "d.py", "e.py"):
        (tmp_path / name).write_text("pass", encoding="utf-8")
    resources = []
    configurations = []
    for index in range(3):
        contract = _contract()
        contract["slo_profile"]["verified_execution"]["inventory"]["partition"] = {"index": index, "size": 2}
        created = GoalContract.from_dict(compile_repository_contract(contract, str(tmp_path)))
        config = created.slo_profile["verified_execution"]
        inventory = config["inventory"]
        assert inventory["partition"]["total"] == 3
        assert inventory["partition"]["resource_count"] == 5
        assert check_repository_scope(config, str(tmp_path))["complete"]
        resources.extend(inventory["resources"])
        configurations.append(config)
    assert resources == ["a.py", "b.py", "c.py", "d.py", "e.py"]
    assert len({config["inventory"]["partition"]["manifest_sha256"] for config in configurations}) == 1
    (tmp_path / "z.py").write_text("pass", encoding="utf-8")
    assert check_repository_scope(configurations[0], str(tmp_path))["status"] == "partition_manifest_changed"


def test_partition_rejects_forged_manifest(tmp_path: Path):
    (tmp_path / "a.py").write_text("pass", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"]["partition"] = {
        "index": 0, "size": 1, "total": 3,
    }
    with pytest.raises(ValueError, match="manifest changed"):
        compile_repository_contract(contract, str(tmp_path))


def test_change_inventory_includes_deleted_staged_and_untracked(tmp_path: Path):
    import subprocess

    from local_ai_hub.execution_inventory import change_resources

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    (tmp_path / "deleted.py").write_text("pass", encoding="utf-8")
    (tmp_path / "unchanged.py").write_text("pass", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    base = git("rev-parse", "HEAD")
    (tmp_path / "deleted.py").unlink()
    (tmp_path / "staged.py").write_text("pass", encoding="utf-8")
    git("add", "staged.py")
    (tmp_path / "untracked.py").write_text("pass", encoding="utf-8")
    assert change_resources(str(tmp_path), base) == ["deleted.py", "staged.py", "untracked.py"]
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"].update(scope="changes", base_revision=base)
    created = GoalContract.from_dict(compile_repository_contract(contract, str(tmp_path)))
    config = created.slo_profile["verified_execution"]
    assert check_repository_scope(config, str(tmp_path))["complete"]
    (tmp_path / "extra.py").write_text("pass", encoding="utf-8")
    assert check_repository_scope(config, str(tmp_path))["added_preview"] == ["extra.py"]
    with pytest.raises(ValueError, match="full lowercase"):
        change_resources(str(tmp_path), "HEAD")
