import unittest
from unittest.mock import Mock

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.related_path_ranking import rank_related_paths


class RelatedPathRankingTests(unittest.TestCase):
    def test_combines_source_weights_and_sorts_ties_by_path(self):
        result = {
            "facts": [{"path": "z.py"}, {"path": "tie.py"}],
            "code_index": {
                "symbols": [{"path": "a.py"}, {"path": "tie.py"}],
                "references": [{"path": "b.py"}],
                "edges": [{"path": "c.py"}],
            },
            "test_candidates": ["b.py", "d.py"],
        }

        self.assertEqual(
            rank_related_paths(result, limit=4),
            ["tie.py", "b.py", "a.py", "z.py"],
        )

    def test_empty_inputs_return_no_paths(self):
        self.assertEqual(rank_related_paths({}, limit=10), [])

    def test_empty_scored_path_can_consume_limit_before_filtering(self):
        result = {"facts": [{"path": ""}, {"path": "b.py"}]}

        self.assertEqual(rank_related_paths(result, limit=1), [])

    def test_engine_queries_with_minimum_index_window_then_ranks(self):
        result = {"facts": [{"path": "src/b.py"}], "code_index": {"symbols": [{"path": "src/a.py"}]}}
        engine = object.__new__(DeterministicEngine)
        engine.query = Mock(return_value=result)

        self.assertEqual(engine.related_paths("repo", "query", limit=1), ["src/a.py"])
        engine.query.assert_called_once_with("repo", "query", limit=24)


if __name__ == "__main__":
    unittest.main()
