import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize("evaluation", [
    {"success": False, "error_code": "invalid_eval_suite_cases"},
    {"success": True, "summary": {"pass_rate": 0.0, "benchmark_valid": False, "role_mismatch": True}},
    {"success": True, "summary": {"pass_rate": 0.0, "benchmark_valid": True, "execution_failures": 1}},
    {"success": True, "summary": {}},
    {"success": True, "summary": {"pass_rate": float("nan")}},
    {"success": True, "summary": {"pass_rate": 0.5}, "cases": [{"status": "error"}]},
    {"success": True, "summary": {"pass_rate": 0.5}, "cases": [{"outcome_unknown": True}]},
])
def test_invalid_evaluation_does_not_replace_history(tmp_path, evaluation):
    history = tmp_path / "eval_history.json"
    original = b'{"demo":{"summary":{"pass_rate":0.75},"cases":[]}}'
    history.write_bytes(original)
    service = SimpleNamespace(state_dir=tmp_path, eval_suite=Mock(return_value=evaluation))
    result = LocalAIServices.eval_drift(service, {"suite_name": "demo"})
    assert result["success"] is False
    assert history.read_bytes() == original


def test_corrupt_history_is_not_overwritten(tmp_path):
    history = tmp_path / "eval_history.json"
    history.write_bytes(b"{broken")
    service = SimpleNamespace(state_dir=tmp_path)
    result = LocalAIServices.eval_drift(service, {"suite_name": "demo", "current": {"summary": {"pass_rate": 0.5}}})
    assert result["success"] is False
    assert history.read_bytes() == b"{broken"


def test_history_write_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(process_utils, "atomic_write_file", fail)
    service = SimpleNamespace(state_dir=tmp_path)
    result = LocalAIServices.eval_drift(service, {"suite_name": "demo", "current": {"summary": {"pass_rate": 0.5}}})
    assert result["success"] is False
    assert not (tmp_path / "eval_history.json").exists()


def test_actual_invalid_suite_propagates_without_writing_history(tmp_path):
    service = SimpleNamespace(state_dir=tmp_path, config={})
    service.eval_suite = lambda payload: LocalAIServices.eval_suite(service, payload)
    result = LocalAIServices.eval_drift(service, {"suite_name": "demo", "cases": []})
    assert result["success"] is False
    assert result["error_code"] == "invalid_eval_suite_cases"
    assert not (tmp_path / "eval_history.json").exists()
