import pytest
from tools.model_training.train_embeddings import (
    cosine_similarity,
    MatryoshkaBiEncoderLoss,
    EmbeddingsTrainer,
)


def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    assert pytest.approx(cosine_similarity(v1, v2)) == 1.0
    assert pytest.approx(cosine_similarity(v1, v3)) == 0.0


def test_matryoshka_contrastive_loss():
    loss_fn = MatryoshkaBiEncoderLoss(matryoshka_dims=(2, 4), temperature=0.1)

    # Query vector aligned with positive vector
    q = [1.0, 1.0, 1.0, 1.0]
    pos = [1.0, 1.0, 1.0, 1.0]
    neg = [-1.0, -1.0, -1.0, -1.0]

    loss = loss_fn.compute_matryoshka_loss(q, pos, [neg])
    # When positive is perfectly aligned and negative is opposite, InfoNCE loss should be very small
    assert loss < 0.01

    # When query is aligned with negative instead of positive, loss should be large
    loss_inverted = loss_fn.compute_matryoshka_loss(q, neg, [pos])
    assert loss_inverted > 5.0


def test_embeddings_trainer_batch_eval():
    trainer = EmbeddingsTrainer(matryoshka_dims=(2, 4))

    batch = [
        {"query": "fibonacci calculation", "positive": "def fib(): pass", "negative": "def server(): pass"},
        {"query": "http router handler", "positive": "def route(): pass", "negative": "def math(): pass"},
    ]

    # Mock embeddings based on presence of keywords
    def embed_q(text):
        if "fibonacci" in text:
            return [1.0, 0.0, 1.0, 0.0]
        return [0.0, 1.0, 0.0, 1.0]

    def embed_d(text):
        if "fib" in text:
            return [0.95, 0.0, 0.95, 0.0]
        elif "route" in text:
            return [0.0, 0.95, 0.0, 0.95]
        return [-0.5, -0.5, -0.5, -0.5]

    metrics = trainer.evaluate_batch(batch, embed_q, embed_d)
    assert metrics["accuracy"] == 1.0
    assert metrics["loss"] < 0.5
