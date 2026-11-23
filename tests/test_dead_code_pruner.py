"""Unit tests for AST Dead-Code Elimination."""

from local_ai_hub.dead_code_pruner import prune_dead_code


def test_prune_unused_private_functions() -> None:
    code = """import os
import sys

def _unused_private_helper():
    x = 10
    y = 20
    return x + y

def _used_helper():
    return 42

def public_api():
    val = _used_helper()
    return val * 2
"""
    res = prune_dead_code(code)
    assert "_unused_private_helper" in res.removed_symbols
    assert "_used_helper" not in res.removed_symbols
    assert "public_api" in res.cleaned_code
    assert "_used_helper" in res.cleaned_code
    assert "_unused_private_helper" not in res.cleaned_code
    assert res.saved_lines > 0


def test_prune_if_false_branches() -> None:
    code = """def compute():
    x = 1
    if False:
        print("This is completely dead code and unreachable")
        dead_var = 12345
    return x * 10
"""
    # Expand code to exceed 10 lines
    code = "import math\nimport os\nimport time\n" + code + "\ndef extra(): return 1\n"
    res = prune_dead_code(code)
    assert "This is completely dead code" not in res.cleaned_code
    assert "def compute():" in res.cleaned_code
    assert "return x * 10" in res.cleaned_code
