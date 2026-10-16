import pytest
from local_ai_hub.diff_parsers import (
    extract_py_diff_defs,
    extract_ts_diff_defs,
    extract_cs_diff_defs,
    extract_go_diff_defs,
    extract_rust_diff_defs,
)


def test_diff_parsers_boolean_and_non_sequence_inputs():
    # Passing booleans or non-sequences must return {} without crashing
    assert extract_py_diff_defs(True) == {}
    assert extract_py_diff_defs(False) == {}
    assert extract_py_diff_defs(12345) == {}
    assert extract_py_diff_defs("def foo(): pass") == {}

    assert extract_ts_diff_defs(True) == {}
    assert extract_ts_diff_defs(12345) == {}
    assert extract_ts_diff_defs("export function foo() {}") == {}

    assert extract_cs_diff_defs(True) == {}
    assert extract_cs_diff_defs(12345) == {}

    assert extract_go_diff_defs(True) == {}
    assert extract_go_diff_defs("func Foo() {}") == {}

    assert extract_rust_diff_defs(True) == {}
    assert extract_rust_diff_defs(12345) == {}


def test_diff_parsers_null_bytes_in_lines():
    py_lines = ["+def foo\x00_bar():", "+    pass"]
    defs = extract_py_diff_defs(py_lines)
    assert defs == {}

    ts_lines = ["+export function foo\x00_ts(a: number) {}"]
    ts_defs = extract_ts_diff_defs(ts_lines)
    assert ts_defs == {}
