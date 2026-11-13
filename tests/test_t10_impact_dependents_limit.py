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

def test_fallback_impact_bounds_file_scan_and_reports_partial_coverage(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src" / "target.py"
    source.parent.mkdir(parents=True)
    source.write_text("def SharedNeedle(): return True\n", encoding="utf-8")

    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    monkeypatch.setattr(
        tools,
        "git_diff",
        lambda *_args, **_kwargs: {
            "success": True,
            "changed_files": ["src/target.py"],
            "truncated": False,
            "diff_sha256": "test-digest",
        },
    )
    monkeypatch.setattr(tools, "_rg", None)
    monkeypatch.setattr("local_ai_hub.repo_tools._IMPACT_SCAN_MAX_FILES", 3)
    observed = {}

    def iter_files(_root, *, max_depth, max_files, inventory_status, inventory_deadline):
        observed.update(
            max_depth=max_depth,
            max_files=max_files,
            inventory_status=inventory_status,
            inventory_deadline=inventory_deadline,
        )
        for _ in range(max_files):
            yield source, source.stat()

    monkeypatch.setattr(tools, "_iter_files_with_stat", iter_files)

    result = tools.impact_analysis(str(root))

    assert observed["max_files"] == 4
    assert observed["inventory_deadline"] is not None
    assert observed["inventory_status"] is not None
    assert result["analysis_coverage"] == {
        "complete": False,
        "files_scanned": 3,
        "limit": 3,
        "truncated_reason": "file_limit",
    }


def test_fallback_impact_caps_ripgrep_timeout(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src" / "target.py"
    source.parent.mkdir(parents=True)
    source.write_text("def SharedNeedle(): return True\n", encoding="utf-8")

    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    monkeypatch.setattr(
        tools,
        "git_diff",
        lambda *_args, **_kwargs: {
            "success": True,
            "changed_files": ["src/target.py"],
            "truncated": False,
            "diff_sha256": "test-digest",
        },
    )
    monkeypatch.setattr(tools, "_rg", "rg")
    monkeypatch.setattr(tools, "ripgrep_timeout", 30.0)
    observed = {}

    def run_rg(*_args, timeout, **_kwargs):
        observed["timeout"] = timeout
        raise TimeoutError("synthetic ripgrep timeout")

    monkeypatch.setattr("local_ai_hub.repo_tools.subprocess.run", run_rg)
    monkeypatch.setattr(
        tools,
        "_iter_files_with_stat",
        lambda _root, *, max_depth, max_files, inventory_status, inventory_deadline: iter(
            [(source, source.stat())]
        ),
    )

    result = tools.impact_analysis(str(root))

    assert observed["timeout"] == 1.5
    assert result["analysis_coverage"]["complete"] is True


def test_fallback_impact_reports_inventory_deadline_timeout(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src" / "target.py"
    source.parent.mkdir(parents=True)
    source.write_text("def SharedNeedle(): return True\n", encoding="utf-8")

    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    monkeypatch.setattr(
        tools,
        "git_diff",
        lambda *_args, **_kwargs: {
            "success": True,
            "changed_files": ["src/target.py"],
            "truncated": False,
            "diff_sha256": "test-digest",
        },
    )
    monkeypatch.setattr(tools, "_rg", None)
    observed = {}

    def timed_out_inventory(
        _root, *, max_depth, max_files, inventory_status, inventory_deadline
    ):
        observed["inventory_deadline"] = inventory_deadline
        inventory_status["complete"] = False
        inventory_status["reasons"].append("time_limit")
        return iter(())

    monkeypatch.setattr(tools, "_iter_files_with_stat", timed_out_inventory)

    result = tools.impact_analysis(str(root))

    assert observed["inventory_deadline"] is not None
    assert result["analysis_coverage"] == {
        "complete": False,
        "files_scanned": 0,
        "limit": 8_000,
        "truncated_reason": "deadline",
    }
