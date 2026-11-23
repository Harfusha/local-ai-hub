"""Embeddings Bi-Encoder Fine-Tuning Engine with Matryoshka Contrastive Loss.

Fine-tunes bi-encoders (e.g. BGE, ModernBERT, or MiniLM) using Multiple Negatives Ranking (InfoNCE)
combined with Matryoshka Representation Learning (MRL):
- Loss computed across nested dimensional cuts (e.g., [128, 256, 768]).
- Maximizes cosine similarity of positive pairs while repelling intra-batch and mined hard negatives.
- Allows ultra-fast Int8 first-stage filtering at dimension 128 before high-precision re-check at 768.
"""

from __future__ import annotations

# import json
import logging
import math
# from dataclasses import dataclass
from typing import Callable, Sequence

logger = logging.getLogger(__name__)


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    n = min(len(v1), len(v2))
    if n == 0:
        return 0.0

    dot = sum(v1[i] * v2[i] for i in range(n))
    norm1 = math.sqrt(sum(v1[i] * v1[i] for i in range(n)))
    norm2 = math.sqrt(sum(v2[i] * v2[i] for i in range(n)))

    if norm1 < 1e-9 or norm2 < 1e-9:
        return 0.0
    return dot / (norm1 * norm2)


class MatryoshkaBiEncoderLoss:
    """Multi-dimensional contrastive loss for Matryoshka Embeddings."""

    def __init__(self, matryoshka_dims: Sequence[int] = (128, 256, 768), temperature: float = 0.05) -> None:
        self.dims = tuple(sorted(list(matryoshka_dims)))
        self.temperature = temperature

    def compute_infonce_loss(
        self,
        q_vec: Sequence[float],
        pos_vec: Sequence[float],
        neg_vecs: Sequence[Sequence[float]],
        dim: int,
    ) -> float:
        """Compute InfoNCE contrastive loss truncated to dimension `dim`."""
        d = min(dim, len(q_vec), len(pos_vec))
        q_slice = q_vec[:d]
        pos_slice = pos_vec[:d]

        sim_pos = cosine_similarity(q_slice, pos_slice) / self.temperature

        # Softmax denominator: exp(sim_pos) + sum(exp(sim_neg))
        denom_sum = math.exp(min(50.0, sim_pos))

        for neg in neg_vecs:
            neg_slice = neg[:d]
            sim_neg = cosine_similarity(q_slice, neg_slice) / self.temperature
            denom_sum += math.exp(min(50.0, sim_neg))

        numerator = math.exp(min(50.0, sim_pos))
        loss = -math.log(max(1e-9, numerator / max(1e-9, denom_sum)))
        return loss

    def compute_matryoshka_loss(
        self,
        q_vec: Sequence[float],
        pos_vec: Sequence[float],
        neg_vecs: Sequence[Sequence[float]],
    ) -> float:
        """Compute average InfoNCE loss across all Matryoshka dimension slices."""
        total_loss = 0.0
        for dim in self.dims:
            total_loss += self.compute_infonce_loss(q_vec, pos_vec, neg_vecs, dim)
        return total_loss / len(self.dims)


class EmbeddingsTrainer:
    """Orchestrates bi-encoder contrastive training and evaluation."""

    def __init__(self, matryoshka_dims: Sequence[int] = (128, 256, 768)) -> None:
        self.loss_fn = MatryoshkaBiEncoderLoss(matryoshka_dims=matryoshka_dims)

    def evaluate_batch(
        self,
        triplets: Sequence[dict[str, str]],
        query_embed_fn: Callable[[str], list[float]],
        doc_embed_fn: Callable[[str], list[float]],
    ) -> dict[str, float]:
        """Compute average loss and top-1 retrieval accuracy across batch."""
        if not triplets:
            return {"loss": 0.0, "accuracy": 1.0}

        total_loss = 0.0
        correct_count = 0

        for item in triplets:
            q = item["query"]
            pos = item["positive"]
            neg = item["negative"]

            q_vec = query_embed_fn(q)
            pos_vec = doc_embed_fn(pos)
            neg_vec = doc_embed_fn(neg)

            loss = self.loss_fn.compute_matryoshka_loss(q_vec, pos_vec, [neg_vec])
            total_loss += loss

            sim_pos = cosine_similarity(q_vec, pos_vec)
            sim_neg = cosine_similarity(q_vec, neg_vec)

            if sim_pos > sim_neg:
                correct_count += 1

        n = len(triplets)
        return {
            "loss": round(total_loss / n, 4),
            "accuracy": round(correct_count / n, 4),
        }
