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


def test_change_inventory_includes_project_mapped_tests_and_binds_policy(tmp_path: Path):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    (tmp_path / "src.py").write_text("pass", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_src.py").write_text("pass", encoding="utf-8")
    policy = tmp_path / ".local-ai.toml"
    policy.write_text('[affected_tests_mapping]\n"src.py" = ["tests/test_src.py"]\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    (tmp_path / "src.py").write_text("x = 1", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"].update(scope="changes", include_mapped_tests=True)
    created = GoalContract.from_dict(compile_repository_contract(contract, str(tmp_path)))
    config = created.slo_profile["verified_execution"]
    assert config["inventory"]["resources"] == ["src.py", "tests/test_src.py"]
    assert len(config["inventory"]["policy_sha256"]) == 64
    assert check_repository_scope(config, str(tmp_path))["complete"]
    policy.write_text('[affected_tests_mapping]\n"src.py" = ["tests/missing.py"]\n', encoding="utf-8")
    assert not check_repository_scope(config, str(tmp_path))["complete"]
    with pytest.raises(ValueError, match="no allowed inventory match"):
        compile_repository_contract(contract, str(tmp_path))


def test_explicit_exclusions_are_exact_persisted_and_rechecked(tmp_path: Path):
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("pass", encoding="utf-8")
    contract = _contract()
    inventory = contract["slo_profile"]["verified_execution"]["inventory"]
    inventory["exclusions"] = [{"path": "b.py", "reason": "generated fixture"}]
    created = GoalContract.from_dict(compile_repository_contract(contract, str(tmp_path)))
    config = created.slo_profile["verified_execution"]
    assert created.acceptance_criteria == ("review: a.py", "review: c.py")
    assert config["inventory"]["exclusions"] == inventory["exclusions"]
    assert check_repository_scope(config, str(tmp_path))["complete"]
    (tmp_path / "d.py").write_text("pass", encoding="utf-8")
    assert check_repository_scope(config, str(tmp_path))["added_preview"] == ["d.py"]
    (tmp_path / "b.py").unlink()
    assert not check_repository_scope(config, str(tmp_path))["complete"]


@pytest.mark.parametrize("exclusions", [
    [{"path": "*.py", "reason": "wildcard"}],
    [{"path": "../a.py", "reason": "escape"}],
    [{"path": "missing.py", "reason": "typo"}],
    [{"path": "a.py", "reason": ""}],
    [{"path": "a.py", "reason": "one"}, {"path": "a.py", "reason": "two"}],
    [{"path": "a.py", "reason": "all resources"}],
])
def test_invalid_exclusions_fail_closed(tmp_path: Path, exclusions):
    (tmp_path / "a.py").write_text("pass", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"]["exclusions"] = exclusions
    with pytest.raises(ValueError, match="exclusion"):
        compile_repository_contract(contract, str(tmp_path))


def test_exclusions_not_supported_for_declared_inventory():
    contract = _contract()
    inventory = contract["slo_profile"]["verified_execution"]["inventory"]
    inventory.update(scope="declared", resources=["a.py"],
                     exclusions=[{"path": "b.py", "reason": "not in scope"}])
    with pytest.raises(ValueError, match="exclusions require"):
        GoalContract.from_dict(contract)


def test_transitive_mapped_impact_cycles_and_missing_targets(tmp_path: Path):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    for name in ("src.py", "test_consumer.py", "test_downstream.py"):
        (tmp_path / name).write_text("pass", encoding="utf-8")
    policy = tmp_path / ".local-ai.toml"
    policy.write_text(
        '[affected_tests_mapping]\n'
        '"src.py" = ["test_consumer.py"]\n'
        '"test_consumer.py" = ["test_downstream.py"]\n'
        '"test_downstream.py" = ["test_consumer.py"]\n', encoding="utf-8",
    )
    git("add", ".")
    git("commit", "-m", "fixture")
    (tmp_path / "src.py").write_text("x = 1", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"].update(
        scope="changes", include_mapped_tests=True,
    )
    created = GoalContract.from_dict(compile_repository_contract(contract, str(tmp_path)))
    config = created.slo_profile["verified_execution"]
    assert config["inventory"]["resources"] == ["src.py", "test_consumer.py", "test_downstream.py"]
    assert check_repository_scope(config, str(tmp_path))["complete"]
    (tmp_path / "test_downstream.py").unlink()
    assert not check_repository_scope(config, str(tmp_path))["complete"]
    with pytest.raises(ValueError, match="no allowed inventory match"):
        compile_repository_contract(contract, str(tmp_path))


def test_static_python_import_impact_includes_transitive_and_deleted_modules(tmp_path: Path):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    package = tmp_path / "src" / "demo"
    package.mkdir(parents=True)
    for name, source in {
        "__init__.py": "",
        "api.py": "def api(): return 1\n",
        "consumer.py": "from .api import api\n",
        "downstream.py": "from demo.consumer import api\n",
        "unrelated.py": "import os\n",
    }.items():
        (package / name).write_text(source, encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    (package / "api.py").unlink()
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"].update(
        scope="changes", include_python_imports=True,
    )
    created = GoalContract.from_dict(compile_repository_contract(contract, str(tmp_path)))
    config = created.slo_profile["verified_execution"]
    assert config["inventory"]["resources"] == [
        "src/demo/api.py", "src/demo/consumer.py", "src/demo/downstream.py",
    ]
    assert config["inventory"]["include_python_imports"] is True
    assert check_repository_scope(config, str(tmp_path))["complete"]
    (package / "unrelated.py").write_text("from demo.consumer import api\n", encoding="utf-8")
    assert check_repository_scope(config, str(tmp_path))["added_preview"] == ["src/demo/unrelated.py"]


def test_static_python_import_impact_refuses_invalid_source(tmp_path: Path):
    import subprocess

    subprocess.check_call(["git", "-C", str(tmp_path), "init"])
    (tmp_path / "bad.py").write_text("def broken(", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"].update(
        scope="changes", include_python_imports=True,
    )
    with pytest.raises(ValueError, match="could not be parsed"):
        compile_repository_contract(contract, str(tmp_path))


def test_python_import_policy_is_rejected_outside_changes_scope(tmp_path: Path):
    (tmp_path / "a.py").write_text("pass", encoding="utf-8")
    contract = _contract()
    contract["slo_profile"]["verified_execution"]["inventory"]["include_python_imports"] = True
    with pytest.raises(ValueError, match="impact expansion requires"):
        compile_repository_contract(contract, str(tmp_path))
