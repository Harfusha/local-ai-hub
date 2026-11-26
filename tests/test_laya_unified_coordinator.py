import pytest
from src.local_ai_hub.laya_unified_coordinator import LayaUnifiedCoordinator
from src.local_ai_hub.laya_training_collector import LayaTrainingCollector


def test_unified_coordinator_end_to_end(tmp_path):
    laya_file = tmp_path / "laya_coord_inbox.jsonl"
    dpo_file = tmp_path / "dpo_coord_inbox.jsonl"
    collector = LayaTrainingCollector(
        laya_inbox_path=laya_file,
        dpo_inbox_path=dpo_file,
        enabled=True,
    )

    coordinator = LayaUnifiedCoordinator(
        mode="advisory",
        default_budget=8192,
        training_collector=collector,
    )

    # 1. Analyze Task without promoting model/heuristic output to a training label
    instruction = "Oprav paměťový leak a inicializaci sdílené paměti napříč systémem"
    affected = ["src/ipc.py", "src/shm.py", "src/engine.py"]

    plan = coordinator.analyze_task(
        instruction=instruction,
        affected_paths=affected,
        incoming_context_tokens=2500,
        max_budget=8192,
    )

    # Cross-lingual expansion & Intent
    assert plan.crosslingual_expansion.detected_language == "cs"
    assert "memory" in plan.crosslingual_expansion.composite_query
    assert plan.intent_analysis.intent in ("bugfix", "performance")

    # Runtime proposals are not labels; collection requires an explicit verified source.
    stats = collector.get_stats()
    assert stats["laya_samples_collected"] == 0

    # 2. Code Quality Scoring
    sample_code = """
def multiply_matrices(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    \"\"\"Multiply two 2D matrices.\"\"\"
    return [[sum(x * y for x, y in zip(row, col)) for col in zip(*b)] for row in a]
"""
    quality = coordinator.score_code(sample_code)
    assert quality.overall_score > 0.8
    assert quality.has_docstrings is True
    assert quality.type_coverage_percent == 100.0

    # 3. Test Invariant & Edge-Case Suggestions
    test_suggestions = coordinator.suggest_tests(sample_code)
    assert test_suggestions.target_function == "multiply_matrices"
    assert any(h.edge_value_repr == "[]" for h in test_suggestions.hypotheses)

    # 4. Semantic Deduplication & Task Indexing
    coordinator.index_completed_task(
        prompt="run full regression test suite",
        result_payload={"passed": 111, "failed": 0},
    )

    plan_hit = coordinator.analyze_task(
        instruction="run full regression test suite now",
        incoming_context_tokens=100,
    )
    assert plan_hit.cached_match is not None
    assert plan_hit.cached_match.is_hit is True
    assert plan_hit.cached_match.cached_payload["passed"] == 111

    # 5. DPO Receipt Capture
    coordinator.record_verification_receipt(
        prompt="Fix buffer overflow",
        chosen_code="a.frombytes(data)",
        rejected_code="array.array('b', data)",
        passed=True,
    )
    updated_stats = collector.get_stats()
    assert updated_stats["laya_samples_collected"] == 0
    assert updated_stats["dpo_pairs_collected"] == 1
    assert updated_stats["total_samples"] == 1
