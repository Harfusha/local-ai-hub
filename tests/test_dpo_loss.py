"""Tests for DPO loss computation and sequence log-probabilities."""

import torch

from tools.model_training.train_dpo import compute_sequence_logps, dpo_loss


def test_dpo_loss_directionality():
    # If policy prefers chosen over rejected more than reference, loss should be low
    batch_size = 2
    # Case 1: Policy assigns much higher logprob to chosen than rejected
    pi_c = torch.tensor([-2.0, -2.5])
    pi_r = torch.tensor([-10.0, -12.0])
    # Reference model assigns similar logprobs to both
    ref_c = torch.tensor([-5.0, -5.0])
    ref_r = torch.tensor([-5.0, -5.0])

    loss_aligned, c_rew, r_rew = dpo_loss(pi_c, pi_r, ref_c, ref_r, beta=0.1)
    assert c_rew > r_rew
    assert loss_aligned.item() < 0.5

    # Case 2: Inverted policy (prefers rejected)
    loss_unaligned, _, _ = dpo_loss(pi_r, pi_c, ref_c, ref_r, beta=0.1)
    assert loss_unaligned.item() > loss_aligned.item()


def test_compute_sequence_logps():
    # 1 sequence of length 4, vocab size 5
    logits = torch.randn(1, 4, 5)
    # Mask out first 2 tokens with -100
    labels = torch.tensor([[-100, -100, 2, 3]])
    logps = compute_sequence_logps(logits, labels)
    assert logps.shape == (1,)
    assert logps.item() < 0.0  # Log-probabilities are non-positive
