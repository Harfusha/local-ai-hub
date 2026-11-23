"""Unit tests for Knowledge Distillation Engine."""

import pytest
import torch
import torch.nn as nn
from tools.model_training.distill import (
    DistillationConfig,
    DistillationLossOutput,
    compute_distillation_loss,
    distill_step,
)


def test_compute_distillation_loss_identical_models() -> None:
    # When student and teacher have identical logits, KL divergence should be near 0
    batch_size = 2
    seq_len = 8
    vocab_size = 32

    logits = torch.randn(batch_size, seq_len, vocab_size)
    labels = torch.randint(0, vocab_size, (batch_size, seq_len))

    config = DistillationConfig(temperature=2.0, alpha=0.0, top_k=None)
    out = compute_distillation_loss(logits, logits, labels, config=config)

    assert isinstance(out, DistillationLossOutput)
    assert out.kl_loss.item() < 1e-4
    assert out.total_loss.item() < 1e-4


def test_distillation_top_k_bounding() -> None:
    batch_size = 2
    seq_len = 10
    vocab_size = 128

    s_logits = torch.randn(batch_size, seq_len, vocab_size, requires_grad=True)
    t_logits = torch.randn(batch_size, seq_len, vocab_size)
    labels = torch.randint(0, vocab_size, (batch_size, seq_len))
    # Add some -100 ignore labels
    labels[:, :3] = -100

    config = DistillationConfig(temperature=2.5, alpha=0.3, top_k=16)
    out = compute_distillation_loss(s_logits, t_logits, labels, config=config)

    assert out.total_loss.requires_grad
    assert out.ce_loss > 0.0
    assert out.kl_loss > 0.0

    # Verify backpropagation works
    out.total_loss.backward()
    assert s_logits.grad is not None
    assert not torch.isnan(s_logits.grad).any()


def test_distill_step_mock_models() -> None:
    class MockModel(nn.Module):
        def __init__(self, vocab: int = 16):
            super().__init__()
            self.emb = nn.Embedding(vocab, 32)
            self.head = nn.Linear(32, vocab)

        def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor = None):
            x = self.emb(input_ids)
            logits = self.head(x)
            return type("Output", (), {"logits": logits})()

    student = MockModel(16)
    teacher = MockModel(16)

    input_ids = torch.randint(0, 16, (2, 6))
    labels = input_ids.clone()

    out = distill_step(student, teacher, input_ids, labels)
    assert out.total_loss > 0.0
    assert out.ce_loss > 0.0
