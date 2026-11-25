import os
import pytest
from src.local_ai_hub.laya_training_collector import LayaTrainingCollector
from src.local_ai_hub.laya_unified_coordinator import LayaUnifiedCoordinator
from src.local_ai_hub.telemetry import TelemetryStore


def test_training_capture_disabled_zero_overhead(tmp_path):
    laya_file = tmp_path / "should_not_exist_laya.jsonl"
    dpo_file = tmp_path / "should_not_exist_dpo.jsonl"
    triplet_file = tmp_path / "should_not_exist_triplet.jsonl"

    # Default: enabled=False
    collector = LayaTrainingCollector(
        laya_inbox_path=laya_file,
        dpo_inbox_path=dpo_file,
        triplet_inbox_path=triplet_file,
        enabled=False,
    )
    assert collector.enabled is False

    # Recording must immediately return None without creating files
    res_laya = collector.record_laya_decision(
        category="routing",
        state={"test": 123},
        question_text="hello",
        expected_choice="fast",
    )
    assert res_laya is None

    res_dpo = collector.record_dpo_pair(
        category="code",
        prompt="prompt",
        chosen="chosen",
        rejected="rejected",
    )
    assert res_dpo is None

    res_trip = collector.record_retrieval_triplet(
        query="query",
        positive="pos",
        negative="neg",
    )
    assert res_trip is None

    # Verify zero disk I/O: no files created
    assert not laya_file.exists()
    assert not dpo_file.exists()
    assert not triplet_file.exists()

    stats = collector.get_stats()
    assert stats["total_samples"] == 0
    assert stats["laya_samples_collected"] == 0
    assert stats["dpo_pairs_collected"] == 0
    assert stats["retrieval_triplets_collected"] == 0


def test_coordinator_with_disabled_training_capture(tmp_path):
    coordinator = LayaUnifiedCoordinator(
        mode="advisory",
        training_capture_enabled=False,
    )
    assert coordinator.collector.enabled is False

    # Execute task analysis
    plan = coordinator.analyze_task(
        instruction="Refactor database queries for faster index scan",
        incoming_context_tokens=1500,
    )
    assert plan.model_recommendation is not None

    # Call verification receipt
    coordinator.record_verification_receipt(
        prompt="Refactor queries",
        chosen_code="select * from idx",
        rejected_code="select * from scan",
    )

    # 0 samples collected
    assert coordinator.collector.get_stats()["total_samples"] == 0


def test_telemetry_modes_decoupling():
    # Helper to simulate config parsing logic from app_runtime
    def resolve_telemetry_modes(telemetry_mode: str, obs_enabled: bool = True):
        mode = telemetry_mode.lower()
        if mode == "off":
            return {"telemetry_enabled": False, "endpoint_stats_enabled": False}
        elif mode == "minimal":
            return {"telemetry_enabled": True, "endpoint_stats_enabled": False}
        elif mode == "full":
            return {"telemetry_enabled": True, "endpoint_stats_enabled": True}
        else:
            return {"telemetry_enabled": obs_enabled, "endpoint_stats_enabled": obs_enabled}

    # 1. Telemetry OFF
    off_cfg = resolve_telemetry_modes("off")
    assert off_cfg["telemetry_enabled"] is False
    assert off_cfg["endpoint_stats_enabled"] is False

    # 2. Telemetry MINIMAL
    min_cfg = resolve_telemetry_modes("minimal")
    assert min_cfg["telemetry_enabled"] is True
    assert min_cfg["endpoint_stats_enabled"] is False

    # 3. Telemetry FULL
    full_cfg = resolve_telemetry_modes("full")
    assert full_cfg["telemetry_enabled"] is True
    assert full_cfg["endpoint_stats_enabled"] is True


def test_telemetry_store_minimal_mode(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True, mode="minimal")
    assert store.enabled is True
    assert store.mode == "minimal"
    # In minimal mode, no background writer thread is spawned (zero thread overhead)
    assert store._thread is None
    # No sqlite db file initialized
    assert not (tmp_path / "telemetry.sqlite3").exists()

    # Fast in-memory recording
    assert store.record(event_type="inference", input_tokens=150, output_tokens=50) is True
    assert store.record(event_type="inference", input_tokens=100, output_tokens=25) is True
    err_res = store.record_error(component="http", operation="get", error=ValueError("Test err"))
    assert err_res == "minimal_err"

    # Flush is instantaneous
    assert store.flush(timeout=1.0) is True

    # Check summary reports atomic counters from RAM
    summ = store.summary()
    assert summ["enabled"] is True
    assert summ["mode"] == "minimal"
    assert summ["requests_total"] == 2
    assert summ["errors_total"] == 1
    assert summ["input_tokens"] == 250
    assert summ["output_tokens"] == 75
    assert summ["total_tokens"] == 325
    assert "uptime_seconds" in summ
    report = store.report()
    assert report["status"] == "unavailable"
    assert report["reason"] == "telemetry_mode_minimal"
    assert report["summary"]["requests_total"] == 2
    assert report["by_agent"] == []
    assert not (tmp_path / "telemetry.sqlite3").exists()


def test_telemetry_store_full_mode(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True, mode="full", batch_size=32, flush_interval_seconds=0.1)
    assert store.enabled is True
    assert store.mode == "full"
    # In full mode, background writer thread is running and SQLite is active
    assert store._thread is not None
    assert (tmp_path / "telemetry.sqlite3").exists()

    # Recording queues event
    assert store.record(event_type="inference", input_tokens=100, output_tokens=50, duration_ms=12.5) is True
    assert store.flush(timeout=2.0) is True

    summ = store.summary()
    assert summ["enabled"] is True
    assert summ.get("mode") != "minimal"
    assert summ["events"] >= 1
    assert summ["local_input_tokens_est"] >= 100
    assert summ["local_output_tokens_est"] >= 50
    store._stop.set()
    if store._thread and store._thread.is_alive():
        store._thread.join(timeout=1.0)
