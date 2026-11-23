"""Unit tests for AST-Aware 3-Way Semantic Auto-Merge."""

import ast
from local_ai_hub.ast_auto_merge import semantic_ast_merge


def test_merge_disjoint_function_additions() -> None:
    base = """
def original():
    return 1
"""
    ours = """
def original():
    return 1

def feature_a():
    return "A"
"""
    theirs = """
def original():
    return 1

def feature_b():
    return "B"
"""
    res = semantic_ast_merge(base, ours, theirs)
    assert res.success, f"Merge failed: {res.conflicts}"
    tree = ast.parse(res.merged_code)
    fn_names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert "original" in fn_names
    assert "feature_a" in fn_names
    assert "feature_b" in fn_names


def test_merge_class_different_methods() -> None:
    base = """
class Worker:
    def method_1(self):
        return 1

    def method_2(self):
        return 2
"""
    # Ours edited method_1
    ours = """
class Worker:
    def method_1(self):
        return 100

    def method_2(self):
        return 2
"""
    # Theirs edited method_2 and added method_3
    theirs = """
class Worker:
    def method_1(self):
        return 1

    def method_2(self):
        return 200

    def method_3(self):
        return 300
"""
    res = semantic_ast_merge(base, ours, theirs)
    assert res.success, f"Merge failed: {res.conflicts}"
    # Verify merged code execution
    exec_env = {}
    exec(res.merged_code, exec_env)
    worker = exec_env["Worker"]()
    assert worker.method_1() == 100
    assert worker.method_2() == 200
    assert worker.method_3() == 300


def test_detect_true_conflict() -> None:
    base = """
def calculate(x):
    return x * 2
"""
    ours = """
def calculate(x):
    return x * 10
"""
    theirs = """
def calculate(x):
    return x * 99
"""
    res = semantic_ast_merge(base, ours, theirs)
    assert not res.success
    assert any("calculate" in c for c in res.conflicts)
