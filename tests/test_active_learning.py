"""Tests for Active Learning continuous data collection inbox."""

import os
import tempfile

from src.local_ai_hub.active_learning import ActiveLearningInbox


def test_active_learning_inbox_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        inbox_file = os.path.join(tmpdir, "inbox.jsonl")
        inbox = ActiveLearningInbox(inbox_path=inbox_file)
        assert inbox.count_samples() == 0

        sample = inbox.record_sample(
            root="/repo",
            file_path="src/engine.py",
            feedback_type="test_success",
            prompt_context="FILE: src/engine.py\ncode",
            target_card={"purpose": "Core compute engine", "symbols": ["run"]},
            source_sha256="abc123456",
        )

        assert sample.sample_id
        assert sample.feedback_type == "test_success"
        assert inbox.count_samples() == 1

        batch = inbox.curate_batch()
        assert len(batch) == 1
        assert batch[0]["id"] == sample.sample_id
        assert len(batch[0]["messages"]) == 3
