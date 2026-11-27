"""Tests for speculative decoding engine and verification logic."""

import pytest

torch = pytest.importorskip("torch", exc_type=ModuleNotFoundError)

from src.local_ai_hub.speculative_decoding import speculative_step


def test_speculative_step_full_agreement():
    # Both draft and target always predict token 42
    def draft_fn(ids: torch.Tensor) -> torch.Tensor:
        batch, seq = ids.shape
        logits = torch.zeros((batch, seq, 100))
        logits[:, :, 42] = 10.0
        return logits

    def target_fn(ids: torch.Tensor) -> torch.Tensor:
        batch, seq = ids.shape
        logits = torch.zeros((batch, seq, 100))
        logits[:, :, 42] = 10.0
        return logits

    prefix = torch.tensor([[1, 2, 3]], dtype=torch.long)
    new_prefix, accepted, drafted = speculative_step(
        draft_fn, target_fn, prefix, lookahead_k=3, temperature=0.0
    )

    assert drafted == 3
    assert accepted == 3
    assert new_prefix.shape[1] == 6
    assert new_prefix[0, -3:].tolist() == [42, 42, 42]


def test_speculative_step_rejection_and_correction():
    # Draft predicts 10, but target predicts 20 on the 2nd token
    def draft_fn(ids: torch.Tensor) -> torch.Tensor:
        batch, seq = ids.shape
        logits = torch.zeros((batch, seq, 100))
        logits[:, :, 10] = 10.0
        return logits

    call_count = 0

    def target_fn(ids: torch.Tensor) -> torch.Tensor:
        batch, seq = ids.shape
        logits = torch.zeros((batch, seq, 100))
        # At first drafted position (index 2 in prefix of len 3): agree on 10
        logits[:, 2, 10] = 10.0
        # At second drafted position (index 3): target predicts 20 instead
        logits[:, 3, 20] = 10.0
        return logits

    prefix = torch.tensor([[1, 2, 3]], dtype=torch.long)
    new_prefix, accepted, drafted = speculative_step(
        draft_fn, target_fn, prefix, lookahead_k=4, temperature=0.0
    )

    assert drafted == 4
    # Accepted 1st draft token (10) + corrected 2nd token (20), then stopped
    assert accepted == 2
    assert new_prefix[0, -2:].tolist() == [10, 20]
