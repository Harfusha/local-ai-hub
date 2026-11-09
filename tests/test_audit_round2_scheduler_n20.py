from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from local_ai_hub.scheduler import AffinityScheduler


def _make_scheduler(tmp_path: Path):
    runtime = SimpleNamespace(
        loaded_model_details=lambda: [],
        is_online=lambda: True,
        ensure_running=lambda: True,
        prepare_model=lambda *a, **kw: [],
    )
    config = {
        "server": {"state_dir": str(tmp_path)},
        "scheduler": {"max_parallel": 1},
    }
    return AffinityScheduler(runtime, config)


def test_n20_clean_app_error_does_not_mark_gpu_uncertain(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    try:
        # A model call completed cleanly, but model returned an application-level failure
        app_error_response = {
            "success": False,
            "error": "Model refused query: safety guidelines",
            "completed_cleanly_with_app_error": True,
            "_lah_backend_completed": True,
        }
        res = scheduler.submit("test-model", source="test", execute=lambda: app_error_response)
        assert res["success"] is False
        assert scheduler._internal_gpu_uncertain is False, "Clean application error must NOT mark GPU runtime uncertain"
    finally:
        scheduler.close()


def test_n20_fatal_system_error_marks_gpu_uncertain(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    try:
        # A fatal crash / unknown outcome
        fatal_response = {
            "success": False,
            "error": "CUDA kernel failure",
            "outcome_unknown": True,
        }
        res = scheduler.submit("test-model", source="test", execute=lambda: fatal_response)
        assert res["success"] is False
        assert scheduler._internal_gpu_uncertain is True, "Fatal system error MUST mark GPU runtime uncertain"
    finally:
        scheduler.close()
