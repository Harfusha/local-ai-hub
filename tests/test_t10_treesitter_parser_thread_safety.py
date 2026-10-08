from __future__ import annotations

import builtins
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import local_ai_hub.treesitter_parser as treesitter_parser
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_parser_initialization_is_serialized(monkeypatch) -> None:
    initializer_entered = threading.Event()
    second_initializer_entered = threading.Event()
    second_call_started = threading.Event()
    release_initializer = threading.Event()
    active_initializers = 0
    max_active_initializers = 0
    state_lock = threading.Lock()

    def initialize_once() -> bool:
        nonlocal active_initializers, max_active_initializers
        with state_lock:
            active_initializers += 1
            max_active_initializers = max(max_active_initializers, active_initializers)
            if active_initializers > 1:
                second_initializer_entered.set()
        initializer_entered.set()
        assert release_initializer.wait(timeout=2)
        with state_lock:
            active_initializers -= 1
        return True

    monkeypatch.setattr(treesitter_parser, "_init_treesitter_once", initialize_once)

    def first_call() -> bool:
        return treesitter_parser._init_treesitter()

    def second_call() -> bool:
        second_call_started.set()
        return treesitter_parser._init_treesitter()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_call)
        assert initializer_entered.wait(timeout=2)
        second = pool.submit(second_call)
        assert second_call_started.wait(timeout=2)
        assert not second_initializer_entered.wait(timeout=0.1)
        release_initializer.set()
        assert first.result(timeout=2) is True
        assert second.result(timeout=2) is True

    assert max_active_initializers == 1


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


def test_windows_python_313_skips_legacy_import_when_language_pack_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(treesitter_parser, "_INIT_ATTEMPTED", False)
    monkeypatch.setattr(treesitter_parser, "_PARSERS", {})
    monkeypatch.setattr(treesitter_parser, "_LANGUAGES", {})
    monkeypatch.setattr(treesitter_parser.os, "name", "nt")
    monkeypatch.setattr(treesitter_parser.sys, "version_info", (3, 13, 0))
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    imported_native_packages = []
    original_import = builtins.__import__

    def record_native_import(name, *args, **kwargs):
        if name.startswith("tree_sitter"):
            imported_native_packages.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", record_native_import)

    assert treesitter_parser._init_treesitter() is False
    assert imported_native_packages == ["tree_sitter_language_pack"]
