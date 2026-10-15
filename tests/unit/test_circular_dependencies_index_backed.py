import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine


def _index(tmp_path: Path) -> CodeIndex:
    def read_snapshot(path: Path, **_kwargs):
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest(), content.decode("utf-8").splitlines()

    return CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        SimpleNamespace(max_file_bytes=10_000_000, _read_snapshot=read_snapshot),
    )


def _write_project(root: Path, files: dict[str, str]) -> list[str]:
    paths = []
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paths.append(relative)
    return paths


def _index_project(index: CodeIndex, root: Path, paths: list[str]) -> None:
    result = index.update_files_batch(str(root), paths)
    assert result["success"] is True


@pytest.mark.parametrize("backend", ["configured", "ast"])
def test_circular_dependencies_keep_absolute_and_from_imports(tmp_path, monkeypatch, backend):
    if backend == "ast":
        monkeypatch.setattr(
            "local_ai_hub.treesitter_parser.parse_treesitter_with_status",
            lambda *_args, **_kwargs: {"status": "unavailable", "result": None},
        )
    root = tmp_path / "absolute-project"
    paths = _write_project(root, {
        "package/__init__.py": "",
        "package/alpha.py": "import package.beta as child\nfrom package import beta as sibling\n",
        "package/beta.py": "from package.alpha import Alpha\n",
    })
    index = _index(root)
    _index_project(index, root, paths)

    result = DeterministicEngine(code_index=index).find_circular_dependencies(str(root))

    assert result["success"] is True
    assert ["package.alpha", "package.beta", "package.alpha"] in [
        item["cycle"] for item in result["cycles"]
    ], result


@pytest.mark.parametrize("backend", ["configured", "ast"])
def test_circular_dependencies_use_indexed_relative_imports_without_source_scan(tmp_path, monkeypatch, backend):
    if backend == "ast":
        monkeypatch.setattr(
            "local_ai_hub.treesitter_parser.parse_treesitter_with_status",
            lambda *_args, **_kwargs: {"status": "unavailable", "result": None},
        )
    root = tmp_path / "project"
    paths = _write_project(root, {
        "package/__init__.py": "",
        "package/alpha.py": "from . import beta as child\n",
        "package/beta.py": "from .alpha import Alpha\n",
    })
    index = _index(tmp_path)
    _index_project(index, root, paths)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("cycle query attempted a cold source scan")

    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(ast, "parse", forbidden)

    result = DeterministicEngine(code_index=index).find_circular_dependencies(str(root))

    assert result["success"] is True
    assert result["modules_scanned"] == 3
    assert result["cycles"] == [{
        "cycle": ["package.alpha", "package.beta", "package.alpha"],
        "chain": "package.alpha -> package.beta -> package.alpha",
        "length": 2,
        "files": [str(root / "package/alpha.py"), str(root / "package/beta.py")],
    }]


def test_circular_dependencies_isolate_roots_and_reflect_index_updates(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    index = _index(tmp_path)
    first_paths = _write_project(first, {
        "package/__init__.py": "",
        "package/alpha.py": "from . import beta\n",
        "package/beta.py": "from . import alpha\n",
    })
    second_paths = _write_project(second, {
        "package/__init__.py": "",
        "package/alpha.py": "VALUE = 1\n",
        "package/beta.py": "VALUE = 2\n",
    })
    _index_project(index, first, first_paths)
    _index_project(index, second, second_paths)
    tools = DeterministicEngine(code_index=index)

    first_result = tools.find_circular_dependencies(str(first))
    second_result = tools.find_circular_dependencies(str(second))
    assert first_result["cycles"][0]["cycle"] == [
        "package.alpha", "package.beta", "package.alpha"
    ]
    assert second_result["success"] is True
    assert second_result["cycles"] == []

    (first / "package/beta.py").write_text("VALUE = 'cycle removed'\n", encoding="utf-8")
    assert index.update_file(str(first), "package/beta.py")["success"] is True
    updated = tools.find_circular_dependencies(str(first))
    assert updated["success"] is True
    assert updated["cycles"] == []


def test_circular_dependencies_reject_missing_or_unindexed_code_index(tmp_path):
    unavailable = DeterministicEngine().find_circular_dependencies(str(tmp_path))
    assert unavailable["success"] is False
    assert "index" in unavailable["error"].lower()
    assert unavailable["index_state"] == "unindexed"

    unindexed = DeterministicEngine(code_index=_index(tmp_path)).find_circular_dependencies(str(tmp_path))
    assert unindexed["success"] is False
    assert "index" in unindexed["error"].lower()


def test_circular_dependencies_reject_files_changed_after_indexing(tmp_path):
    root = tmp_path / "project"
    paths = _write_project(root, {
        "alpha.py": "import beta\n",
        "beta.py": "import alpha\n",
    })
    index = _index(tmp_path)
    _index_project(index, root, paths)
    (root / "beta.py").write_text("VALUE = 'changed after indexing'\n", encoding="utf-8")

    result = DeterministicEngine(code_index=index).find_circular_dependencies(str(root))

    assert result["success"] is False
    assert "stale" in result["error"].lower()
