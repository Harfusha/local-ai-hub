from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine


def test_compact_topology_retains_unverified_architecture_and_import_scope():
    from local_ai_hub import mcp_server

    raw = {
        "success": True,
        "architecture_pattern_hypothesis": "Package / Module Collection",
        "architecture_pattern_verified": False,
        "heuristic_layers": {"utilities": ["src/pkg/module.py"]},
        "module_graph": {"complete": False, "edges": []},
        "import_scope": "Python AST imports resolved against bounded local modules",
        "coverage": {"complete": False, "errors": ["file_limit"]},
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({
        "tool": "local_ai_repo", "max_response_tokens": 1800,
        "response_profile": "compact",
    })
    try:
        result = mcp_server._compact(raw, "topology")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    for key in (
        "architecture_pattern_hypothesis", "architecture_pattern_verified",
        "heuristic_layers", "module_graph", "import_scope", "coverage",
    ):
        assert result[key] == raw[key]


def test_topology_resolves_local_imports_and_labels_unresolved_edges(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    package = root / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "service.py").write_text(
        "import json\nimport thirdparty_lib\nfrom . import sibling\nfrom pkg.sibling import VALUE\nfrom ..missing import item\n"
        "# import fake.comment\ntext = 'import fake.string'\n",
        encoding="utf-8",
    )
    (package / "sibling.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "service-plan.py").write_text("", encoding="utf-8")

    result = DeterministicEngine().repo_topology(str(root))
    graph = result["module_graph"]

    assert "architecture_pattern_hypothesis" in result
    assert result["architecture_pattern_verified"] is False
    assert result["coverage"]["module_graph_resolved"] is True
    assert any(edge["target"] == "src/pkg/sibling.py" for edge in graph["edges"])
    assert any(item["reason"] == "unresolved_relative_import" for item in graph["unresolved"])
    assert graph["stdlib_import_count"] == 1
    assert any(item["module"] == "thirdparty_lib" for item in graph["external_imports"])
    assert graph["edge_count"] == len(graph["edges"])
    assert not any("service-plan.py" in path for paths in result["heuristic_layers"].values() for path in paths)
    assert "fake.comment" not in repr(graph)
    assert "fake.string" not in repr(graph)
    assert "Pattern hypothesis (unverified, path-based)" not in result["summary_markdown"]
    assert "Heuristic path labels" in result["summary_markdown"]


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

    assert "eligible Python source" in result["coverage"]["inventory_scope"]
    if linked:
        assert result["coverage"]["complete"] is False
        assert "unsafe_path" in result["coverage"]["errors"]
    assert {item["module"] for item in result["module_graph"]["external_imports"]} == {"useful.module"}
