from itertools import islice
from pathlib import Path

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def _project(tmp_path: Path, sources: dict[str, str]):
    root = tmp_path / "repo"
    for relative, text in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    return root, engine


@pytest.mark.parametrize("has_initializer", [False, True])
def test_from_import_resolves_child_modules_and_counts_unique_source_hubs(
    tmp_path: Path, has_initializer: bool,
):
    sources = {
        "src/pkg/client.py": "from pkg import helper\nfrom . import helper\n",
        "src/pkg/helper.py": "VALUE = 1\n",
        "docs/service-plan.md": "This is documentation, not a service.\n",
    }
    if has_initializer:
        sources["src/pkg/__init__.py"] = ""
    root, engine = _project(tmp_path, sources)

    result = engine.repo_topology(str(root))
    graph = result["module_graph"]

    child_edges = [edge for edge in graph["edges"] if edge["target"] == "src/pkg/helper.py"]
    assert {edge["line"] for edge in child_edges} == {1, 2}
    assert all(edge["module"] == "pkg.helper" for edge in child_edges)
    assert {hub["path"]: hub["in_degree"] for hub in graph["hub_paths"]}["src/pkg/helper.py"] == 1
    assert graph["external_import_count"] == 0
    assert graph["unresolved_count"] == 0
    assert graph["complete"] is True
    assert all("docs/" not in path for paths in result["heuristic_layers"].values() for path in paths)


def test_missing_dotted_local_module_cannot_resolve_to_package_initializer(tmp_path: Path):
    root, engine = _project(tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/client.py": "import pkg.missing\n",
    })

    graph = engine.repo_topology(str(root))["module_graph"]

    assert graph["edges"] == []
    assert graph["unresolved"] == [{
        "source": "src/pkg/client.py", "module": "pkg.missing", "line": 1,
        "reason": "unresolved_local_module",
    }]
    assert graph["external_import_count"] == 0
    assert graph["complete"] is False


def test_beyond_package_relative_import_cannot_become_root_module(tmp_path: Path):
    root, engine = _project(tmp_path, {
        "src/pkg/client.py": "from ..other import VALUE\n",
        "src/other.py": "VALUE = 1\n",
    })

    graph = engine.repo_topology(str(root))["module_graph"]

    assert graph["edges"] == []
    assert graph["unresolved"] == [{
        "source": "src/pkg/client.py", "module": "..other", "line": 1,
        "reason": "unresolved_relative_import",
    }]
    assert graph["complete"] is False


def test_dependency_record_limit_stops_before_reading_next_file(tmp_path: Path, monkeypatch):
    root, engine = _project(tmp_path, {
        "a.py": "import " + ",".join(f"dependency_{number}" for number in range(5001)) + "\n",
        "b.py": "import overflow_dependency\n",
    })
    monkeypatch.setattr(
        engine.repo_tools, "iter_files", lambda *_args, **_kwargs: iter([root / "a.py", root / "b.py"]),
    )

    result = engine.repo_topology(str(root))

    assert result["module_graph"]["external_import_count"] == 5000
    assert result["module_graph"]["complete"] is False
    assert result["coverage"]["files_read"] == 1
    assert result["coverage"]["files_skipped"] == 1
    assert "edge_limit" in result["coverage"]["errors"]


def test_inventory_cap_is_incomplete_even_when_prefix_contains_no_python(tmp_path: Path, monkeypatch):
    root, engine = _project(tmp_path, {"late.py": "VALUE = 1\n"})

    def inventory(_root, *, max_files):
        paths = (root / f"data-{number}.txt" for number in range(20001))
        return islice(paths, max_files)

    monkeypatch.setattr(engine.repo_tools, "iter_files", inventory)

    result = engine.repo_topology(str(root))

    assert result["coverage"]["complete"] is False
    assert result["module_graph"]["complete"] is False
    assert "inventory_limit" in result["coverage"]["errors"]
