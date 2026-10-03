from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import local_ai_hub.treesitter_parser as treesitter_parser
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_parser_lock_covers_native_tree_walk_when_parser_is_reused(monkeypatch) -> None:
    class Parser:
        def parse(self, _source: bytes) -> SimpleNamespace:
            return SimpleNamespace(root_node=object())

    active_walks = 0
    max_active_walks = 0
    state_lock = threading.Lock()
    first_walk_entered = threading.Event()
    second_walk_entered = threading.Event()
    release_first_walk = threading.Event()

    def extract(_root, _lines, _source_bytes):
        nonlocal active_walks, max_active_walks
        with state_lock:
            active_walks += 1
            max_active_walks = max(max_active_walks, active_walks)
            first = active_walks == 1
        if first:
            first_walk_entered.set()
            assert release_first_walk.wait(timeout=2)
        else:
            second_walk_entered.set()
        with state_lock:
            active_walks -= 1
        return [], [], []

    monkeypatch.setattr(treesitter_parser, "_INIT_ATTEMPTED", True)
    monkeypatch.setitem(treesitter_parser._PARSERS, "python", Parser())
    monkeypatch.setattr(treesitter_parser, "_extract_python", extract)

    def parse_one(source: str):
        return treesitter_parser.parse_treesitter(source, "python")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(parse_one, "first = 1")
        assert first_walk_entered.wait(timeout=2)
        second = pool.submit(parse_one, "second = 2")
        second_walk_entered.wait(timeout=0.2)
        release_first_walk.set()
        assert first.result(timeout=2) == ([], [], [])
        assert second.result(timeout=2) == ([], [], [])

    assert max_active_walks == 1


def test_code_index_batch_serializes_shared_python_tree_walks(tmp_path) -> None:
    if not treesitter_parser.is_treesitter_available("python"):
        import pytest

        pytest.skip("Tree-sitter Python parser unavailable")

    root = tmp_path / "repo"
    paths = []
    for index in range(8):
        relative = f"src/module_{index}.py"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"def run_{index}():\n    return helper_{index}()\n",
            encoding="utf-8",
        )
        paths.append(relative)

    config = {"server": {"state_dir": str(tmp_path / "state")}}
    code_index = CodeIndex(config, RepositoryTools(config))

    result = code_index.update_files_batch(str(root), paths)

    assert result["success"] is True


def test_python_extractor_handles_deep_expression_without_recursive_walk_failure() -> None:
    if not treesitter_parser.is_treesitter_available("python"):
        import pytest

        pytest.skip("Tree-sitter Python parser unavailable")

    depth = 1300
    source = "def run():\n    return " + "(" * depth + "1" + ")" * depth + "\n"

    result = treesitter_parser.parse_treesitter(source, "python")

    assert result is not None
    assert any(symbol["name"] == "run" for symbol in result[0])
