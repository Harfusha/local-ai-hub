from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_impact_honors_explicit_dependent_limit_above_default_cap(tmp_path):
    root = tmp_path / "repo"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "target.py").write_text("def SharedNeedle(): return True\n", encoding="utf-8")
    paths = []
    for number in range(101):
        name = f"caller_{number:03}.py"
        (source / name).write_text(
            f"from target import SharedNeedle\ndef caller_{number}(): return SharedNeedle()\n",
            encoding="utf-8",
        )
        paths.append(f"src/{name}")

    config = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools=tools)
    indexed = index.update_files_batch(str(root), ["src/target.py", *paths])
    assert indexed["success"] is True

    result = index.impact(str(root), ["src/target.py"], max_dependents=101)

    assert result["success"] is True
    assert len(result["likely_dependents"]) == 101
