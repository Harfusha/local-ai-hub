from __future__ import annotations

import pytest

from local_ai_hub.diff_parsers import (
    extract_cs_diff_defs,
    extract_go_diff_defs,
    extract_py_diff_defs,
    extract_rust_diff_defs,
    extract_ts_diff_defs,
)


def test_none_and_empty_inputs_return_empty_dict() -> None:
    assert extract_py_diff_defs(None) == {}  # type: ignore[arg-type]
    assert extract_py_diff_defs([]) == {}

    assert extract_ts_diff_defs(None) == {}  # type: ignore[arg-type]
    assert extract_ts_diff_defs([]) == {}

    assert extract_cs_diff_defs(None) == {}  # type: ignore[arg-type]
    assert extract_cs_diff_defs([]) == {}

    assert extract_go_diff_defs(None) == {}  # type: ignore[arg-type]
    assert extract_go_diff_defs([]) == {}

    assert extract_rust_diff_defs(None) == {}  # type: ignore[arg-type]
    assert extract_rust_diff_defs([]) == {}


def test_raw_diff_prefixes_supported_across_languages() -> None:
    py_defs = extract_py_diff_defs(["+def compute(a, b=1):", "+    pass"])
    assert "compute" in py_defs
    assert py_defs["compute"]["required_count"] == 1
    assert py_defs["compute"]["pos_args"] == ["a", "b"]

    ts_defs = extract_ts_diff_defs(["+export function greet(name: string, title?: string): void {}"])
    assert "greet" in ts_defs
    assert ts_defs["greet"]["required_count"] == 1

    cs_defs = extract_cs_diff_defs(["-public void Process(int code = 0)"])
    assert "Process" in cs_defs
    assert cs_defs["Process"]["required_count"] == 0

    go_defs = extract_go_diff_defs(["+func Calculate(x int) int {}"])
    assert "Calculate" in go_defs

    rust_defs = extract_rust_diff_defs(["+pub fn execute() {}"])
    assert "execute" in rust_defs


def test_py_diff_posonlyargs_supported() -> None:
    defs = extract_py_diff_defs(["def compute(x, /, y, z=10): pass"])
    assert "compute" in defs
    assert defs["compute"]["pos_args"] == ["x", "y", "z"]
    assert defs["compute"]["required_count"] == 2


def test_cs_diff_generic_parameter_splitting() -> None:
    # Generic parameter with comma should not be split into two separate arguments
    defs = extract_cs_diff_defs(["public void MapData(Dictionary<string, int> dict, int flag = 0)"])
    assert "MapData" in defs
    assert defs["MapData"]["required_count"] == 1
