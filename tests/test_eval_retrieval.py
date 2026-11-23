import pytest
from tools.model_training.eval_retrieval import RetrievalEvaluator, RetrievalMetrics


def test_retrieval_evaluator_perfect_ranking():
    evaluator = RetrievalEvaluator(top_k=5)

    queries = ["find fibonacci", "find router"]
    ground_truth = {"find fibonacci": "doc_fib", "find router": "doc_route"}
    candidate_pool = {
        "doc_fib": "def fib(): pass",
        "doc_route": "def route(): pass",
        "doc_math": "def math(): pass",
    }

    # Perfect ranker: always puts true doc first
    def perfect_rank_fn(q, items):
        if "fibonacci" in q:
            return ["doc_fib", "doc_math", "doc_route"]
        return ["doc_route", "doc_fib", "doc_math"]

    metrics = evaluator.evaluate(queries, ground_truth, candidate_pool, perfect_rank_fn)

    assert metrics.total_queries == 2
    assert metrics.mrr == 1.0
    assert metrics.hit_at_1 == 1.0
    assert metrics.hit_at_5 == 1.0
    assert metrics.ndcg == 1.0  # 1 / log2(2) = 1.0


def test_retrieval_evaluator_imperfect_ranking():
    evaluator = RetrievalEvaluator(top_k=5)

    queries = ["find fibonacci"]
    ground_truth = {"find fibonacci": "doc_fib"}
    candidate_pool = {
        "doc_math": "def math(): pass",
        "doc_fib": "def fib(): pass",
    }

    # Ranker puts target at 2nd place
    def imperfect_rank_fn(q, items):
        return ["doc_math", "doc_fib"]

    metrics = evaluator.evaluate(queries, ground_truth, candidate_pool, imperfect_rank_fn)

    assert metrics.total_queries == 1
    assert metrics.mrr == 0.5  # 1 / 2 = 0.5
    assert metrics.hit_at_1 == 0.0
    assert metrics.hit_at_5 == 1.0
