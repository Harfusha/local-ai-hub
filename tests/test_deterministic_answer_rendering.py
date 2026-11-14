import unittest

from local_ai_hub.deterministic_answer_rendering import render_deterministic_answer
from local_ai_hub.deterministic import DeterministicEngine


class DeterministicAnswerRenderingTests(unittest.TestCase):
    def test_dependencies_include_version_scope_and_source(self):
        result = render_deterministic_answer({
            "intent": "dependencies",
            "dependencies": [{"name": "requests", "version": "2.32", "scope": "runtime", "source": "pyproject.toml"}],
        })

        self.assertEqual(result, "- requests 2.32 [runtime] — pyproject.toml")

    def test_commands_keep_purpose_name_and_command(self):
        result = render_deterministic_answer({
            "intent": "commands",
            "scripts": [{"purpose": "test", "name": "unit", "command": "pytest"}],
        })

        self.assertEqual(result, "- test: unit → pytest")

    def test_tests_deduplicate_fact_paths_already_in_candidates(self):
        result = render_deterministic_answer({
            "intent": "tests",
            "test_candidates": ["tests/a.py"],
            "facts": [{"path": "tests/a.py"}, {"path": "tests/b.py"}],
        })

        self.assertEqual(result, "- tests/a.py\n- tests/b.py")

    def test_callers_render_callers_symbols_references_then_edges(self):
        result = render_deterministic_answer(
            {
                "intent": "callers",
                "code_index": {
                    "callers": [{"caller": "A", "callee": "B", "path": "src/a.py", "line": 2}],
                    "symbols": [{"name": "B", "path": "src/b.py", "line": 4}],
                    "references": [{"name": "B", "path": "src/c.py", "line": 7}],
                    "edges": [{"src": "A", "kind": "calls", "dst": "B", "path": "src/a.py", "line": 2}],
                },
            },
            max_items=4,
        )

        self.assertEqual(
            result,
            "- A calls B — src/a.py:2\n- definition B — src/b.py:4\n- reference B — src/c.py:7\n- A calls B — src/a.py:2",
        )

    def test_symbols_intent_omits_callers_and_caps_references_and_edges(self):
        result = render_deterministic_answer(
            {
                "intent": "symbols",
                "code_index": {
                    "callers": [{"caller": "A", "callee": "B", "path": "src/a.py", "line": 2}],
                    "symbols": [{"name": "B", "path": "src/b.py", "line": 4}],
                    "references": [{"name": "B", "path": "src/c.py", "line": 7}],
                    "edges": [{"src": "A", "kind": "calls", "dst": "B", "path": "src/a.py", "line": 2}],
                },
            },
            max_items=1,
        )

        self.assertEqual(result, "- definition B — src/b.py:4")

    def test_general_intent_renders_facts_with_optional_value(self):
        result = render_deterministic_answer({
            "intent": "general",
            "facts": [
                {"kind": "class", "name": "Widget", "value": "Widget", "path": "src/widget.py", "line": 3},
                {"kind": "function", "name": "build", "value": "Widget()", "path": "src/widget.py", "line": 9},
            ],
        })

        self.assertEqual(
            result,
            "- class: Widget — src/widget.py:3\n- function: build = Widget() — src/widget.py:9",
        )

    def test_general_intent_falls_back_to_symbols(self):
        result = render_deterministic_answer({
            "intent": "general",
            "facts": [],
            "code_index": {"symbols": [{"name": "Widget", "path": "src/widget.py", "line": 3}]},
        })

        self.assertEqual(result, "- definition Widget — src/widget.py:3")

    def test_empty_result_uses_existing_no_match_text(self):
        self.assertEqual(
            render_deterministic_answer({"intent": "general"}),
            "No deterministic match found.",
        )

    def test_engine_method_preserves_renderer_behavior(self):
        result = {"intent": "dependencies", "dependencies": [{"name": "requests", "version": "2.32"}]}

        self.assertEqual(
            DeterministicEngine.render_answer(object.__new__(DeterministicEngine), result),
            render_deterministic_answer(result),
        )


if __name__ == "__main__":
    unittest.main()
