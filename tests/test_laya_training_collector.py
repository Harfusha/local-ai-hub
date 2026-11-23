import os
import json
import pytest
from src.local_ai_hub.laya_training_collector import LayaTrainingCollector


def test_laya_training_collector(tmp_path):
    laya_file = tmp_path / "laya_test_inbox.jsonl"
    dpo_file = tmp_path / "dpo_test_inbox.jsonl"
    triplet_file = tmp_path / "triplet_test_inbox.jsonl"

    collector = LayaTrainingCollector(
        laya_inbox_path=laya_file,
        dpo_inbox_path=dpo_file,
        triplet_inbox_path=triplet_file,
        enabled=True,
    )

    # 1. Record Laya decision sample
    sample = collector.record_laya_decision(
        category="retrieval_strategy",
        state={"query_len": 24, "has_symbol": True},
        question_text="def calculate_matrix()",
        expected_choice="ast_symbol",
        confidence_distribution={"ast_symbol": 0.95, "hybrid": 0.05},
    )

    assert sample.category == "retrieval_strategy"
    assert sample.expected == "ast_symbol"
    assert sample.sample_id.startswith("laya_")

    # Flush async queue to disk before checking files
    assert collector.flush(timeout=2.0) is True

    # Verify written file content
    assert laya_file.exists()
    lines = laya_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["expected"] == "ast_symbol"

    # 2. Record DPO pair
    dpo_sample = collector.record_dpo_pair(
        category="code_generation",
        prompt="Fix buffer overflow in array copy",
        chosen="a = array.array('b'); a.frombytes(data)",
        rejected="a = array.array('b', data)",
        verification_passed=True,
        metadata={"test": "pytest_simd"},
    )

    assert dpo_sample.pair_id.startswith("dpo_")

    # 3. Record Retrieval Triplet
    trip_sample = collector.record_retrieval_triplet(
        query="acquire shared memory buffer",
        positive="def acquire_slot(): pass",
        negative="def release_slot(): pass",
        metadata={"overlap": 0.45},
    )
    assert trip_sample.triplet_id.startswith("trip_")

    # Flush all remaining async items
    assert collector.flush(timeout=2.0) is True

    assert dpo_file.exists()
    dpo_lines = dpo_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(dpo_lines) == 1
    dpo_data = json.loads(dpo_lines[0])
    assert "chosen" in dpo_data
    assert "rejected" in dpo_data

    assert triplet_file.exists()
    trip_lines = triplet_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(trip_lines) == 1

    # Check stats
    stats = collector.get_stats()
    assert stats["laya_samples_collected"] == 1
    assert stats["dpo_pairs_collected"] == 1
    assert stats["retrieval_triplets_collected"] == 1
    assert stats["total_samples"] == 3
    assert stats["queue_pending"] == 0

    # Test LRU ring buffer deduplication: duplicate sample does not increment stats or rewrite
    dup_sample = collector.record_laya_decision(
        category="retrieval_strategy",
        state={"query_len": 24, "has_symbol": True},
        question_text="def calculate_matrix()",
        expected_choice="ast_symbol",
        confidence_distribution={"ast_symbol": 0.95, "hybrid": 0.05},
    )
    assert dup_sample.sample_id == sample.sample_id
    assert collector.get_stats()["laya_samples_collected"] == 1

    collector.close()
