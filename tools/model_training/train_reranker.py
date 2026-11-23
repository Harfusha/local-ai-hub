"""Reranker Cross-Encoder Fine-Tuning Engine with Triplet Margin & BCE Loss.

Fine-tunes cross-encoders (e.g. BAAI/bge-reranker-base or ModernBERT) on code triplets:
- Margin Ranking Loss: L = max(0, margin - (score(q, pos) - score(q, neg)))
- Binary Cross-Entropy Loss: L_bce = -log(sigmoid(score(pos))) - log(1 - sigmoid(score(neg)))

Ensures high discriminative precision between genuine functions and hard negatives.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainingMetrics:
    epoch: int
    step: int
    loss: float
    margin_accuracy: float
    avg_pos_score: float
    avg_neg_score: float


class CrossEncoderLoss:
    """Computes Margin Ranking and Binary Cross-Entropy losses for Cross-Encoder scoring."""

    def __init__(self, margin: float = 0.5) -> None:
        self.margin = margin

    @staticmethod
    def sigmoid(x: float) -> float:
        if x > 30:
            return 1.0
        if x < -30:
            return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    def compute_margin_loss(self, pos_score: float, neg_score: float) -> float:
        """Margin Ranking Loss: max(0, margin - (pos - neg))."""
        diff = pos_score - neg_score
        return max(0.0, self.margin - diff)

    def compute_bce_loss(self, pos_score: float, neg_score: float) -> float:
        """BCE Loss with positive target 1.0 and negative target 0.0."""
        p_prob = max(1e-7, min(1.0 - 1e-7, self.sigmoid(pos_score)))
        n_prob = max(1e-7, min(1.0 - 1e-7, self.sigmoid(neg_score)))

        loss_pos = -math.log(p_prob)
        loss_neg = -math.log(1.0 - n_prob)
        return (loss_pos + loss_neg) / 2.0


class RerankerTrainer:
    """Manages dataset loading, loss computation, and training loops for Cross-Encoder rerankers."""

    def __init__(self, margin: float = 0.5, learning_rate: float = 2e-5) -> None:
        self.loss_fn = CrossEncoderLoss(margin=margin)
        self.lr = learning_rate
        self.step_counter = 0

    def evaluate_batch(
        self,
        batch: Sequence[dict[str, Any]],
        score_fn: Callable[[str, str], float],
    ) -> TrainingMetrics:
        """Compute metrics for a batch of triplets using the supplied scoring function."""
        if not batch:
            return TrainingMetrics(0, self.step_counter, 0.0, 1.0, 0.0, 0.0)

        total_loss = 0.0
        pos_scores: list[float] = []
        neg_scores: list[float] = []
        correct_order = 0

        for item in batch:
            q = item["query"]
            pos = item["positive"]
            neg = item["negative"]

            s_pos = score_fn(q, pos)
            s_neg = score_fn(q, neg)

            loss = self.loss_fn.compute_margin_loss(s_pos, s_neg)
            total_loss += loss

            pos_scores.append(s_pos)
            neg_scores.append(s_neg)
            if s_pos > s_neg:
                correct_order += 1

        n = len(batch)
        self.step_counter += 1

        return TrainingMetrics(
            epoch=1,
            step=self.step_counter,
            loss=round(total_loss / n, 4),
            margin_accuracy=round(correct_order / n, 4),
            avg_pos_score=round(sum(pos_scores) / n, 4),
            avg_neg_score=round(sum(neg_scores) / n, 4),
        )

    def load_dataset(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Load mined triplets from JSONL file."""
        items: list[dict[str, Any]] = []
        p = Path(file_path)
        if not p.exists():
            return items

        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return items
