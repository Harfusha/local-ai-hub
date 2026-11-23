import json
import pytest
from tools.model_training.train_reranker import CrossEncoderLoss, RerankerTrainer


def test_cross_encoder_loss():
    loss_fn = CrossEncoderLoss(margin=0.5)

    # 1. Perfect margin: pos = 2.0, neg = -1.0 (diff = 3.0 > 0.5) -> loss should be 0.0
    zero_loss = loss_fn.compute_margin_loss(pos_score=2.0, neg_score=-1.0)
    assert zero_loss == 0.0

    # 2. Inverted order: pos = 0.0, neg = 1.0 (diff = -1.0) -> loss = 0.5 - (-1.0) = 1.5
    high_loss = loss_fn.compute_margin_loss(pos_score=0.0, neg_score=1.0)
    assert high_loss == 1.5

    # 3. BCE loss
    bce_good = loss_fn.compute_bce_loss(pos_score=3.0, neg_score=-3.0)
    bce_bad = loss_fn.compute_bce_loss(pos_score=-3.0, neg_score=3.0)
    assert bce_good < bce_bad


def test_reranker_trainer_batch_evaluation(tmp_path):
    trainer = RerankerTrainer(margin=0.5)

    batch = [
        {"query": "q1", "positive": "pos1", "negative": "neg1"},
        {"query": "q2", "positive": "pos2", "negative": "neg2"},
    ]

    # Model that scores positive higher than negative
    def good_model_fn(q, doc):
        return 2.0 if "pos" in doc else -0.5

    metrics = trainer.evaluate_batch(batch, good_model_fn)

    assert metrics.margin_accuracy == 1.0
    assert metrics.loss == 0.0
    assert metrics.avg_pos_score == 2.0
    assert metrics.avg_neg_score == -0.5

    # Test loading dataset from file
    data_file = tmp_path / "triplets.jsonl"
    with open(data_file, "w", encoding="utf-8") as f:
        for b in batch:
            f.write(json.dumps(b) + "\n")

    loaded = trainer.load_dataset(data_file)
    assert len(loaded) == 2
