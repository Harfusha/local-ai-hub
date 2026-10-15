from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine


def test_compact_topology_retains_unverified_architecture_and_import_scope():
    from local_ai_hub import mcp_server

    raw = {"success": True, "architecture_pattern_verified": False,
           "import_scope": "declared Python imports; unresolved",
           "coverage": {"complete": False, "errors": ["file_limit"]}}
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({
        "tool": "local_ai_repo", "max_response_tokens": 1800,
        "response_profile": "compact",
    })
    try:
        result = mcp_server._compact(raw, "topology")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert result["architecture_pattern_verified"] is False
    assert result["import_scope"] == raw["import_scope"]
    assert result["coverage"] == raw["coverage"]


def test_topology_reports_declared_python_imports_as_unresolved_heuristics(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "service.py").write_text(
        "import package.submodule\nfrom ..shared.parts import item\nfrom . import sibling\n"
        "# import fake.comment\ntext = 'import fake.string'\n",
        encoding="utf-8",
    )
    (root / "src" / "pkg" / "api_controller.py").write_text(
        "from package.submodule import value\n", encoding="utf-8"
    )
    (root / "src" / "contest.py").write_text("value = 1\n", encoding="utf-8")

    result = DeterministicEngine().repo_topology(str(root))

    assert result["import_scope"].startswith("Python AST declared imports only")
    assert result["architecture_pattern_verified"] is False
    assert result["coverage"]["module_graph_resolved"] is False
    assert {item["module"]: item["in_degree"] for item in result["hub_modules"]} == {
        "package.submodule": 2,
        "..shared.parts": 1,
        ".sibling": 1,
    }
    assert "fake.comment" not in repr(result["hub_modules"])
    assert "fake.string" not in repr(result["hub_modules"])
    assert "src/contest.py" in result["layers"]["utilities"]
    assert "Blast Radius" not in result["summary_markdown"]
    assert "Pattern hypothesis (unverified, path-based)" in result["summary_markdown"]
    assert "Filename-based layer hypotheses (unverified)" in result["summary_markdown"]


def test_topology_oversize_and_symlink_omissions_are_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "large.py").write_bytes(b"#" * (256 * 1024 + 1))
    (root / "inside.py").write_text("import useful.module\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("import secret.module\n", encoding="utf-8")
    linked = False
    try:
        (root / "linked.py").symlink_to(outside)
        linked = True
    except (OSError, NotImplementedError):
        pass

    result = DeterministicEngine().repo_topology(str(root))

    assert "eligible files only" in result["coverage"]["inventory_scope"]
    if linked:
        assert result["coverage"]["complete"] is False
        assert "unsafe_path" in result["coverage"]["errors"]
    assert {item["module"] for item in result["hub_modules"]} == {"useful.module"}
