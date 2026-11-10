import pytest
from types import SimpleNamespace

from local_ai_hub.scheduler import AffinityScheduler
from local_ai_hub.services import _backend_completion_metadata


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"done": True}, {"_lah_backend_completed": True}),
        ({"done": False}, {}),
        ({}, {}),
    ],
)
def test_backend_completion_metadata_requires_explicit_done(response, expected):
    assert _backend_completion_metadata(response) == expected


def test_empty_response_after_done_does_not_leave_gpu_outcome_unknown(tmp_path):
    scheduler = AffinityScheduler(
        SimpleNamespace(
            loaded_model_details=lambda: [],
            is_online=lambda: True,
            ensure_running=lambda: True,
            prepare_model=lambda *args, **kwargs: [],
        ),
        {"server": {"state_dir": str(tmp_path)}, "scheduler": {"max_parallel": 1}},
    )
    response = {
        "success": False,
        "error": "local model returned empty response",
        "retryable": True,
        "terminal": False,
        **_backend_completion_metadata({"done": True}),
    }
    try:
        result = scheduler.submit("test-model", source="test", execute=lambda: response)
        assert result["success"] is False
        assert result.get("outcome_unknown") is not True
        assert scheduler._internal_gpu_uncertain is False
    finally:
        scheduler.close()
