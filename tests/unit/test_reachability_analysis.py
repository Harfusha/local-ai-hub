from local_ai_hub.reachability_analysis import analyze_reachability
from local_ai_hub.deterministic import DeterministicEngine


def test_analyze_reachability_skips_ambiguous_names_and_finds_transitive_calls():
    defs = {
        "main.py:1:entry": {"name": "entry", "file": "main.py", "line": 1},
        "lib.py:1:used": {"name": "used", "file": "lib.py", "line": 1},
        "lib.py:4:deep": {"name": "deep", "file": "lib.py", "line": 4},
        "a.py:1:shared": {"name": "shared", "file": "a.py", "line": 1},
        "b.py:1:shared": {"name": "shared", "file": "b.py", "line": 1},
        "dead.py:1:unused": {"name": "unused", "file": "dead.py", "line": 1},
    }
    defs_by_name = {
        "entry": ["main.py:1:entry"],
        "used": ["lib.py:1:used"],
        "deep": ["lib.py:4:deep"],
        "shared": ["a.py:1:shared", "b.py:1:shared"],
        "unused": ["dead.py:1:unused"],
    }
    module_calls = {"main.py": {"used", "shared"}, "lib.py": {"deep"}}

    ambiguous, reachable, ambiguous_symbols, unreachable = analyze_reachability(
        defs, defs_by_name, module_calls, ["main.py"]
    )

    assert ambiguous == {"shared"}
    assert reachable == {"lib.py:1:used", "lib.py:4:deep"}
    assert {item["file"] for item in ambiguous_symbols} == {"a.py", "b.py"}
    assert [item["name"] for item in unreachable] == ["entry", "unused"]


def test_reachability_dead_code_preserves_report_shape(tmp_path):
    (tmp_path / "main.py").write_text("def main():\n    used()\n", encoding="utf-8")
    (tmp_path / "lib.py").write_text("def used():\n    deep()\n\ndef deep():\n    pass\n", encoding="utf-8")
    (tmp_path / "dead.py").write_text("def unused():\n    pass\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)

    result = engine.reachability_dead_code(str(tmp_path))

    assert result["success"] is True
    assert result["complete"] is True
    assert result["reachable_symbols_count"] == 2
    assert {item["name"] for item in result["unreachable_symbols"]} == {"main", "unused"}
