from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import local_ai_hub.treesitter_parser as treesitter_parser


def _simulate_windows_python_313(monkeypatch) -> None:
    monkeypatch.setattr(treesitter_parser, "_INIT_ATTEMPTED", False)
    monkeypatch.setattr(treesitter_parser, "_PARSERS", {})
    monkeypatch.setattr(treesitter_parser, "_LANGUAGES", {})
    monkeypatch.setattr(treesitter_parser, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(treesitter_parser, "sys", SimpleNamespace(version_info=(3, 13)))


def test_windows_python_313_uses_available_language_pack_for_java_and_cpp(monkeypatch) -> None:
    _simulate_windows_python_313(monkeypatch)
    requested: list[str] = []
    pack = ModuleType("tree_sitter_language_pack")
    pack.has_language = lambda name: name in {"java", "cpp"}
    pack.get_language = lambda name: f"language:{name}"

    def get_parser(name: str) -> object:
        requested.append(name)
        return object()

    pack.get_parser = get_parser
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", pack)

    assert treesitter_parser._init_treesitter() is True
    assert treesitter_parser.is_treesitter_available("java") is True
    assert treesitter_parser.is_treesitter_available("cpp") is True
    assert requested == ["java", "cpp"]


def test_windows_python_313_keeps_legacy_binding_fallback_disabled(monkeypatch) -> None:
    _simulate_windows_python_313(monkeypatch)
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)

    assert treesitter_parser._init_treesitter() is False
    assert treesitter_parser._PARSERS == {}
