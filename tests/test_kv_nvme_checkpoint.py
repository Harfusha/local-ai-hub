"""Unit tests for NVMe KV-Cache Checkpointing and Fast Mapped Restore."""

import tempfile
import time
from pathlib import Path

from local_ai_hub.kv_nvme_checkpoint import (
    KVCacheState,
    load_kv_checkpoint,
    prune_stale_kv_checkpoints,
    save_kv_checkpoint,
)


def test_kv_checkpoint_save_and_mmap_load() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        num_layers = 4
        num_heads = 8
        head_dim = 64
        seq_len = 512

        # Generate mock KV layer tensors (512 * 64 * 2 bytes = 65536 bytes per layer)
        kv_layers = {}
        for l in range(num_layers):
            key_data = bytes([l % 256] * (num_heads * head_dim * 4))
            val_data = bytes([(l + 1) % 256] * (num_heads * head_dim * 4))
            kv_layers[l] = (key_data, val_data)

        start_save = time.time()
        ckpt_path = save_kv_checkpoint(
            checkpoint_dir=tmp_dir,
            session_id="session_test_42",
            model_tag="qwen2.5-coder:3b",
            num_layers=num_layers,
            num_heads=num_heads,
            head_dim=head_dim,
            seq_len=seq_len,
            dtype="fp16",
            kv_layers=kv_layers,
        )
        assert ckpt_path.is_file()

        # Measure mmap load latency
        start_load = time.time()
        state = load_kv_checkpoint(ckpt_path, use_mmap=True)
        load_ms = (time.time() - start_load) * 1000.0

        assert state.model_tag == "qwen2.5-coder:3b"
        assert state.seq_len == 512
        assert state.num_layers == 4
        assert state.dtype == "fp16"
        assert len(state.layers) == 4
        assert state.layers[0] == kv_layers[0]
        assert load_ms < 50.0, f"Load took too long: {load_ms:.2f} ms"


def test_prune_stale_checkpoints() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        p_dir = Path(tmp_dir)
        # Create 3 dummy files
        f1 = p_dir / "s1.kvpage"
        f2 = p_dir / "s2.kvpage"
        f1.write_bytes(b"data1")
        f2.write_bytes(b"data2")

        # Prune with age threshold 0 (prune all)
        pruned = prune_stale_kv_checkpoints(p_dir, max_age_seconds=-1.0)
        assert pruned == 2
        assert not f1.exists()
        assert not f2.exists()
