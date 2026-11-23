import tempfile
from pathlib import Path
import pytest

from local_ai_hub.context_virtualizer import (
    virtualize_file_read,
    virtualize_python_source,
)


def test_virtualize_python_source_small():
    code = "def foo():\n    return 42\n"
    res, mode = virtualize_python_source(code, max_lines=80)
    assert mode == "raw"
    assert res == code


def test_virtualize_python_source_large_ast_skeleton():
    # Generate 120 lines with 5 functions
    lines = ["import os", "import sys", ""]
    for i in range(1, 6):
        lines.append(f"def func_{i}(x: int) -> int:")
        lines.append(f'    """Docstring for func {i}."""')
        for j in range(15):
            lines.append(f"    x += {j}")
        lines.append("    return x")
        lines.append("")
    code = "\n".join(lines)
    assert len(lines) > 80

    res, mode = virtualize_python_source(code, max_lines=60, file_name="sample.py")
    assert mode == "ast_skeleton"
    assert "[Virtual Context: sample.py" in res
    assert "def func_1" in res
    assert "def func_5" in res
    # Line annotations exist
    assert "   1: import os" in res


def test_virtualize_python_source_query_slice():
    lines = ["import math", ""]
    for i in range(1, 10):
        lines.append(f"def calculation_alpha_{i}():")
        for j in range(10):
            lines.append(f"    v = {j} * {i}")
        lines.append("    return v")
        lines.append("")
    lines.append("def special_target_handler():")
    lines.append('    """Crucial handler."""')
    lines.append("    return 'TARGET_FOUND'")
    code = "\n".join(lines)

    res, mode = virtualize_python_source(code, query="special_target_handler", max_lines=80)
    assert mode == "query_slice"
    assert "special_target_handler" in res
    assert "TARGET_FOUND" in res


def test_virtualize_file_read_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        small_file = tmp_path / "small.txt"
        small_file.write_text("Hello\nWorld\n", encoding="utf-8")

        res_small = virtualize_file_read(tmp_path, "small.txt", max_lines=80)
        assert res_small["success"] is True
        assert res_small["virtualized"] is False
        assert "Hello" in res_small["text"]

        large_py = tmp_path / "large.py"
        py_lines = [f"def worker_{i}():\n    pass\n" for i in range(100)]
        large_py.write_text("\n".join(py_lines), encoding="utf-8")

        res_large = virtualize_file_read(tmp_path, "large.py", max_lines=80)
        assert res_large["success"] is True
        assert res_large["virtualized"] is True
        assert "worker_0" in res_large["text"]
        assert "lines omitted" in res_large["text"]

        # With query, targeted symbol is extracted even in huge file
        res_targeted = virtualize_file_read(tmp_path, "large.py", query="worker_99", max_lines=80)
        assert res_targeted["success"] is True
        assert "worker_99" in res_targeted["text"]


def test_virtualize_file_read_not_found():
    res = virtualize_file_read(Path.cwd(), "non_existent_file_xyz_123.py")
    assert res["success"] is False
    assert "File not found" in res["error"]
