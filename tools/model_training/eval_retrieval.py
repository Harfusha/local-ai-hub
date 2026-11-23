"""Retrieval Accuracy Evaluator for Embeddings and Rerankers.

Calculates standard Information Retrieval (IR) benchmark metrics:
- Mean Reciprocal Rank (MRR@k)
- Normalized Discounted Cumulative Gain (NDCG@k)
- Hit Rate (Hit@1, Hit@5, Hit@10)

Provides reproducible benchmarking before and after fine-tuning on code triplets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class RetrievalMetrics:
    total_queries: int
    mrr: float
    ndcg: float
    hit_at_1: float
    hit_at_5: float
    hit_at_10: float


class RetrievalEvaluator:
    """Evaluates ranking models against known ground truth relevant documents."""

    def __init__(self, top_k: int = 10) -> None:
        self.top_k = top_k

    def evaluate(
        self,
        queries: Sequence[str],
        ground_truth: Mapping[str, str],  # query -> true_doc_id
        candidate_pool: Mapping[str, str],  # doc_id -> doc_text
        rank_fn: Callable[[str, list[tuple[str, str]]], list[str]],  # (query, [(id, text)]) -> [ranked_doc_ids]
    ) -> RetrievalMetrics:
        """Evaluate rank_fn across all queries."""
        if not queries:
            return RetrievalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0)

        mrr_total = 0.0
        ndcg_total = 0.0
        hit1_count = 0
        hit5_count = 0
        hit10_count = 0

        pool_items = list(candidate_pool.items())

        for q in queries:
            true_id = ground_truth.get(q)
            if not true_id:
                continue

            ranked_ids = rank_fn(q, pool_items)[:self.top_k]

            # Find rank of true_id (1-indexed)
            try:
                rank = ranked_ids.index(true_id) + 1
            except ValueError:
                rank = None

            if rank is not None:
                mrr_total += 1.0 / rank
                # DCG: 1 / log2(rank + 1)
                ndcg_total += 1.0 / math.log2(rank + 1)

                if rank == 1:
                    hit1_count += 1
                if rank <= 5:
                    hit5_count += 1
                if rank <= 10:
                    hit10_count += 1

        n = len(queries)
        return RetrievalMetrics(
            total_queries=n,
            mrr=round(mrr_total / n, 4),
            ndcg=round(ndcg_total / n, 4),
            hit_at_1=round(hit1_count / n, 4),
            hit_at_5=round(hit5_count / n, 4),
            hit_at_10=round(hit10_count / n, 4),
        )
