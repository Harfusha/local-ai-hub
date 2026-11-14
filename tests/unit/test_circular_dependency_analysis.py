from pathlib import Path

from local_ai_hub.circular_dependency_analysis import find_circular_dependencies


class _ImportIndex:
    def python_module_import_graph(self, root):
        return {
            "success": True,
            "paths": ["alpha.py", "beta.py"],
            "imports": [
                {"path": "alpha.py", "target": "beta"},
                {"path": "beta.py", "target": "alpha"},
            ],
        }


def test_find_circular_dependencies_formats_indexed_cycle(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "alpha.py").write_text("import beta\n", encoding="utf-8")
    (root / "beta.py").write_text("import alpha\n", encoding="utf-8")

    result = find_circular_dependencies(
        str(root), "python", 15, 50, _ImportIndex()
    )

    assert result == {
        "success": True,
        "root": str(root.resolve()),
        "modules_scanned": 2,
        "cycles_found": 1,
        "cycles": [
            {
                "cycle": ["alpha", "beta", "alpha"],
                "chain": "alpha -> beta -> alpha",
                "length": 2,
                "files": [str(root / "alpha.py"), str(root / "beta.py")],
            }
        ],
        "has_cycles": True,
        "truncated": False,
        "complete": True,
    }
