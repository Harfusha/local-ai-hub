from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools import selftest


def _source_tree(tmp_path, monkeypatch, source):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "probe.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(selftest, "ROOT", tmp_path)


def test_compiler_only_conditional_annotation_symbol_is_not_a_nameerror(tmp_path, monkeypatch):
    _source_tree(tmp_path, monkeypatch, "value: int = 1\n")
    original = selftest.symtable.symtable
    implicit = SimpleNamespace(
        get_name=lambda: "__conditional_annotations__",
        is_assigned=lambda: False, is_imported=lambda: False,
        is_parameter=lambda: False, is_referenced=lambda: True,
        is_global=lambda: True,
    )

    def compiler_table(*args, **kwargs):
        table = original(*args, **kwargs)
        return SimpleNamespace(
            get_symbols=lambda: [*table.get_symbols(), implicit],
            get_children=table.get_children,
        )

    monkeypatch.setattr(selftest.symtable, "symtable", compiler_table)
    assert selftest._undefined_globals() == []


@pytest.mark.parametrize("name", ["__conditional_annotations__", "actual_missing_name"])
def test_explicit_undefined_names_still_fail(tmp_path, monkeypatch, name):
    _source_tree(tmp_path, monkeypatch, f"def read():\n    return {name}\n")
    assert selftest._undefined_globals() == [f"src/probe.py: undefined global {name}".replace("/", selftest.os.sep)]


def test_real_conditional_annotations_and_builtins(tmp_path, monkeypatch):
    _source_tree(tmp_path, monkeypatch,
                 "if True:\n    value: int = 1\nclass Example:\n    if True:\n        name: str = 'test'\n")
    assert selftest._undefined_globals() == []


def test_syntax_errors_remain_failures(tmp_path, monkeypatch):
    _source_tree(tmp_path, monkeypatch, "def broken(:\n")
    failures = selftest._undefined_globals()
    assert len(failures) == 1 and "parse error:" in failures[0]
