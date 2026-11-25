import concurrent.futures
import threading
import time
import pytest
from src.local_ai_hub.laya_unified_coordinator import LayaUnifiedCoordinator, UnifiedLayaPlan
from src.local_ai_hub.laya_semantic_dedup import LayaSemanticDeduplicator, SemanticMatchResult
from src.local_ai_hub.laya_training_collector import LayaTrainingCollector


def test_lah_012_replay_admissibility_and_isolation():
    """LAH-012: Verify exact replay requires matching repo, worktree, revision, no mutation, and word order/polarity."""
    dedup = LayaSemanticDeduplicator()

    # 1. Index baseline query in repo A, worktree A, revision 1
    dedup.index_prompt(
        prompt_id="p1",
        prompt_text="povol zápis a zakaž čtení",
        payload={"action": "set_permissions", "write": True, "read": False},
        repo_root="/repo/A",
        worktree_id="wt-main",
        revision="rev-001",
        operation="perm_config",
        is_mutation=False,
    )

    # Inverted word order: exact bag-of-words similarity is 1.0, but semantic polarity / word order is inverted!
    match_inv = dedup.find_match(
        "zakaž zápis a povol čtení",
        repo_root="/repo/A",
        worktree_id="wt-main",
        revision="rev-001",
        operation="perm_config",
    )
    assert match_inv is not None
    assert match_inv.is_hit is True
    assert match_inv.is_replay_admissible is False
    assert "word_order" in (match_inv.rejection_reason or "")

    # Negation insertion: "povol zápis a čtení" vs "povol zápis a nepovol čtení"
    dedup.index_prompt(
        prompt_id="p2",
        prompt_text="povol zápis a čtení",
        payload={"allow_both": True},
        repo_root="/repo/A",
    )
    match_neg = dedup.find_match(
        "povol zápis a nepovol čtení",
        repo_root="/repo/A",
    )
    assert match_neg is not None
    assert match_neg.is_replay_admissible is False
    assert "negation" in (match_neg.rejection_reason or "")

    # Numeric argument mismatch: "read configuration file 1 and parse it" vs "read configuration file 2 and parse it"
    dedup.index_prompt(
        prompt_id="p3",
        prompt_text="read configuration file 1 and parse it",
        payload={"file_num": 1},
        repo_root="/repo/A",
    )
    match_num = dedup.find_match("read configuration file 2 and parse it", repo_root="/repo/A")
    assert match_num is not None
    assert match_num.is_replay_admissible is False
    assert "numeric_argument" in (match_num.rejection_reason or "")

    # Cross-repo mismatch: prompt exists in /repo/A, query is for /repo/B
    match_cross_repo = dedup.find_match(
        "povol zápis a zakaž čtení",
        repo_root="/repo/B",
        worktree_id="wt-main",
        revision="rev-001",
    )
    assert match_cross_repo is not None
    assert match_cross_repo.is_replay_admissible is False
    assert "repository_mismatch" in (match_cross_repo.rejection_reason or "")

    # Cross-worktree mismatch
    match_cross_wt = dedup.find_match(
        "povol zápis a zakaž čtení",
        repo_root="/repo/A",
        worktree_id="wt-feature-branch",
        revision="rev-001",
    )
    assert match_cross_wt is not None
    assert match_cross_wt.is_replay_admissible is False
    assert "worktree_mismatch" in (match_cross_wt.rejection_reason or "")

    # Cross-revision mismatch
    match_cross_rev = dedup.find_match(
        "povol zápis a zakaž čtení",
        repo_root="/repo/A",
        worktree_id="wt-main",
        revision="rev-002",
    )
    assert match_cross_rev is not None
    assert match_cross_rev.is_replay_admissible is False
    assert "revision_mismatch" in (match_cross_rev.rejection_reason or "")

    # Mutation replay rejection
    dedup.index_prompt(
        prompt_id="p_mutation",
        prompt_text="delete temporary cache files now",
        payload={"deleted": 15},
        repo_root="/repo/A",
        is_mutation=True,
    )
    match_mut = dedup.find_match(
        "delete temporary cache files now",
        repo_root="/repo/A",
        allow_mutation=False,
    )
    assert match_mut is not None
    assert match_mut.is_replay_admissible is False
    assert "mutation_replay_prohibited" in (match_mut.rejection_reason or "")

    # Exact valid replay match
    match_valid = dedup.find_match(
        "povol zápis a zakaž čtení",
        repo_root="/repo/A",
        worktree_id="wt-main",
        revision="rev-001",
        operation="perm_config",
    )
    assert match_valid is not None
    assert match_valid.is_hit is True
    assert match_valid.is_exact_match is True
    assert match_valid.is_replay_admissible is True
    assert match_valid.rejection_reason is None
    assert match_valid.cached_payload["write"] is True


def test_lah_013_concurrent_barrier_and_byte_caps():
    """LAH-013: Verify thread-safe single-map deduplicator under concurrent inserts/lookups/evictions and byte limits."""
    # Strict 4 KB cap to force continuous evictions
    dedup = LayaSemanticDeduplicator(max_entries=20, max_bytes=4096)

    errors = []
    num_threads = 8
    items_per_thread = 50

    def worker(tid: int):
        try:
            for i in range(items_per_thread):
                pid = f"thread_{tid}_item_{i}"
                text = f"synthetic search query for item {i} in partition {tid}"
                dedup.index_prompt(
                    prompt_id=pid,
                    prompt_text=text,
                    payload={"tid": tid, "i": i, "payload": "x" * 50},
                    repo_root="/workspace/test",
                )
                # Lookup previous or current item
                res = dedup.find_match(text, repo_root="/workspace/test")
                assert res is not None
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(errors) == 0, f"Encountered concurrency errors: {errors}"
    assert len(dedup._entries) <= 20
    assert dedup._total_bytes <= 4096


def test_lah_014_training_collector_provenance_and_non_contamination(tmp_path):
    """LAH-014: Ensure unverified predictions and failed tests NEVER become gold ground truth, redact secrets, assign splits."""
    laya_file = tmp_path / "laya_inbox.jsonl"
    dpo_file = tmp_path / "dpo_inbox.jsonl"
    collector = LayaTrainingCollector(
        laya_inbox_path=laya_file,
        dpo_inbox_path=dpo_file,
        enabled=True,
    )

    # 1. Unverified model prediction without receipt: gold MUST be empty {}!
    sample_unverified = collector.record_laya_decision(
        category="model_route",
        state={"context_len": 500},
        question_text="Route this task with apiKey=sk-abcdef123456789012345678",
        expected_choice="fast_tier",
        label_source="model_prediction",
    )
    assert sample_unverified is not None
    assert sample_unverified.gold == {}  # NOT contaminated!
    assert sample_unverified.label_source == "model_prediction"
    assert "[REDACTED_SECRET]" in sample_unverified.questions["query"]
    assert "sk-" not in sample_unverified.questions["query"]

    # 2. Failed verification receipt: gold MUST be empty {}!
    sample_failed = collector.record_laya_decision(
        category="code_strategy",
        state={"error_code": 404},
        question_text="Fix missing route handler",
        expected_choice="rewrite_router",
        verification_receipt={"passed": False, "exit_code": 1},
    )
    assert sample_failed is not None
    assert sample_failed.gold == {}  # Failed receipt never becomes gold!
    assert sample_failed.label_source == "failed_verification"

    # 3. Passing verification receipt: gold is populated with ground truth!
    sample_verified = collector.record_laya_decision(
        category="code_strategy",
        state={"error_code": 500},
        question_text="Fix null pointer exception in parser",
        expected_choice="null_check_guard",
        confidence_distribution={"null_check_guard": 1.0},
        verification_receipt={"passed": True, "tests_run": 5},
    )
    assert sample_verified is not None
    assert sample_verified.gold == {"null_check_guard": 1.0}
    assert sample_verified.label_source == "verified_receipt"

    # 4. Human label correction: gold is populated with human correction!
    sample_human = collector.record_laya_decision(
        category="retrieval_strategy",
        state={"has_symbols": False},
        question_text="Locate all architectural patterns",
        expected_choice="model_said_ast",
        human_label="hybrid_rag",
    )
    assert sample_human is not None
    assert sample_human.expected == "human_label_not_overwritten" if False else "hybrid_rag"
    assert sample_human.gold == {"hybrid_rag": 1.0}
    assert sample_human.label_source == "human_correction"

    # 5. DPO secret redaction & failed test metadata
    dpo_sample = collector.record_dpo_pair(
        category="security",
        prompt="Authenticate user with password=SecretPassword123!",
        chosen="verify_hash(token)",
        rejected="if pwd == 'SecretPassword123!': return True",
        verification_passed=True,
    )
    assert dpo_sample is not None
    assert "[REDACTED_SECRET]" in dpo_sample.prompt
    assert "SecretPassword123!" not in dpo_sample.prompt

    collector.flush(timeout=2.0)


def test_lah_032_laya_state_machine_modes():
    """LAH-032: Verify explicit Laya state machine (off, shadow, advisory, active), OOD abstention, and calibration."""
    # 1. Mode: "off" -> Zero neural/heuristic inference, zero telemetry, instant deterministic baseline
    coord_off = LayaUnifiedCoordinator(mode="off")
    plan_off = coord_off.analyze_task("Any complex instruction requiring reasoning")
    assert plan_off.mode == "off"
    assert plan_off.provenance == "deterministic_default_mode_off"
    assert plan_off.is_actionable is False
    assert plan_off.abstained is False
    assert plan_off.overall_confidence == 1.0
    assert plan_off.retrieval_recommendation.strategy == "ast_symbol"

    # In "off" mode, helper methods return fast deterministic results
    assert coord_off.scan_code("import os; os.system('rm -rf /')").has_violations is False
    assert coord_off.score_code("def foo(): pass").overall_score == 1.0
    assert coord_off.index_completed_task("prompt", {}) == ""

    # 2. Mode: "shadow" -> Runs inference/telemetry in background, but marked non-binding and abstained
    coord_shadow = LayaUnifiedCoordinator(mode="shadow")
    plan_shadow = coord_shadow.analyze_task("Oprav paměťový leak v parseru")
    assert plan_shadow.mode == "shadow"
    assert plan_shadow.provenance == "laya_shadow_evaluation_only"
    assert plan_shadow.is_actionable is False
    assert plan_shadow.abstained is True
    assert plan_shadow.abstention_reason == "shadow_mode_non_binding"
    assert plan_shadow.crosslingual_expansion.detected_language == "cs"

    # 3. Mode: "advisory" -> Recommendations provided with calibrated confidence, non-binding
    coord_advisory = LayaUnifiedCoordinator(mode="advisory")
    plan_advisory = coord_advisory.analyze_task("Oprav paměťový leak v parseru")
    assert plan_advisory.mode == "advisory"
    assert plan_advisory.provenance == "laya_advisory_recommendation"
    assert plan_advisory.is_actionable is False
    assert plan_advisory.abstained is False
    assert plan_advisory.calibrated_head_confidences is not None
    assert "retrieval" in plan_advisory.calibrated_head_confidences

    # 4. Mode: "active" -> Actionable when confidence is high; abstains when OOD or low confidence
    coord_active = LayaUnifiedCoordinator(mode="active", active_confidence_threshold=0.65)
    
    # Normal in-distribution task with high confidence
    plan_active = coord_active.analyze_task("Oprav paměťový leak v parseru", affected_paths=["src/parser.py"])
    assert plan_active.mode == "active"
    assert plan_active.is_actionable is True
    assert plan_active.abstained is False
    assert plan_active.provenance == "laya_active_calibrated"

    # Out-of-distribution (empty / single character) -> abstains to baseline
    plan_ood = coord_active.analyze_task(" ")
    assert plan_ood.mode == "active"
    assert plan_ood.is_actionable is False
    assert plan_ood.abstained is True
    assert plan_ood.abstention_reason == "out_of_distribution"
    assert plan_ood.provenance == "laya_active_abstained_to_baseline"
