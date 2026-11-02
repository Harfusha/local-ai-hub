import json
from types import SimpleNamespace

import pytest

from local_ai_hub.benchmark import HardwareBenchmarkRunner
from local_ai_hub.scheduler import SchedulerTimeoutError
from tools.benchmark_surfaces import _run_t12_matrix


@pytest.mark.parametrize("state", ["pending", "dispatching", "running"])
def test_benchmark_preserves_scheduler_timeout_state(tmp_path, state):
    class Scheduler:
        def submit(self, *args, **kwargs):
            raise SchedulerTimeoutError(SimpleNamespace(id=917), state, 0.1)

    runner = HardwareBenchmarkRunner(tmp_path / "benchmark.json", runtime=object(), scheduler=Scheduler())
    result = runner.run_t12_case(task="reason", model="example", prompt="x", num_tokens=4,
                                 expected={}, evidence_paths=[])
    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["job_id"] == 917
    assert result["failure_code"] == "request_timeout"
    assert "quality_score_pct" not in result
    record = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    entry = record[-1] if isinstance(record, list) else record
    assert "quality_score_pct" not in entry
    if state == "pending":
        assert result["request_not_sent"] is True
        assert result["operation_not_started"] is True
        assert result.get("outcome_unknown") is not True
    else:
        assert result["outcome_unknown"] is True
        assert result["retryable"] is False
        assert result.get("request_not_sent") is not True


def test_untyped_timeout_is_not_assumed_to_be_unsent(tmp_path):
    class Scheduler:
        def submit(self, *args, **kwargs):
            raise TimeoutError("unknown stage")

    runner = HardwareBenchmarkRunner(tmp_path / "benchmark.json", runtime=object(), scheduler=Scheduler())
    result = runner.run_t12_case(task="reason", model="example", prompt="x", num_tokens=4,
                                 expected={}, evidence_paths=[])
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    assert result.get("request_not_sent") is not True


def test_scheduler_timeout_response_preserves_authentic_job_identity(tmp_path):
    class Scheduler:
        def submit(self, *args, **kwargs):
            return {"success": False, "error": "request timed out", "timed_out": True,
                    "outcome_unknown": True, "job_id": 321, "retryable": False}

    runner = HardwareBenchmarkRunner(tmp_path / "benchmark.json", runtime=object(), scheduler=Scheduler())
    result = runner.run_t12_case(task="reason", model="example", prompt="x", num_tokens=4,
                                 expected={}, evidence_paths=[])
    assert result["timed_out"] is True
    assert result["outcome_unknown"] is True
    assert result["job_id"] == 321
    assert result["retryable"] is False
    assert "quality_score_pct" not in result


def test_scheduler_in_progress_is_not_reported_as_finished(tmp_path):
    class Scheduler:
        def submit(self, *args, **kwargs):
            return {"success": True, "in_progress": True, "job_id": 322}

    runner = HardwareBenchmarkRunner(tmp_path / "benchmark.json", runtime=object(), scheduler=Scheduler())
    result = runner.run_t12_case(task="reason", model="example", prompt="x", num_tokens=4,
                                 expected={}, evidence_paths=[])
    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["job_id"] == 322
    assert result["retryable"] is False
    assert "quality_score_pct" not in result


def test_scenario_rejects_success_with_known_unsent_timeout(tmp_path):
    class Scheduler:
        def run_benchmark_scenario(self, **kwargs):
            return {"success": True, "timed_out": True, "request_not_sent": True,
                    "some_metric": 1, "receipt_id": "receipt-1"}

    runner = HardwareBenchmarkRunner(tmp_path / "benchmark.json", runtime=object(), scheduler=Scheduler())
    result = runner.run_benchmark_scenario(name="scheduler", contract={
        "scenario": "scheduler", "required_fields": ["some_metric"],
    })
    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["request_not_sent"] is True


def test_matrix_stops_when_real_scenario_runner_reports_in_progress(tmp_path):
    class Scheduler:
        def __init__(self):
            self.calls = 0

        def run_benchmark_scenario(self, **kwargs):
            self.calls += 1
            return {"success": True, "in_progress": True, "job_id": 323}

    class Runner(HardwareBenchmarkRunner):
        def run_t12_case(self, **kwargs):
            return {"success": True}

    scheduler = Scheduler()
    runner = Runner(tmp_path / "benchmark.json", runtime=object(), scheduler=scheduler,
                    config={"models": {"reasoning": "model", "fast_code": "model", "heavy_code": "model"}})
    report = _run_t12_matrix(runner, repetitions=1, concurrency_limit=2)
    assert scheduler.calls == 1
    assert report["accepted"] is False
    assert report["outcome_unknown"] is True
    assert report["job_id"] == 323


@pytest.mark.parametrize("raised", [False, True])
def test_scenario_preserves_uncertainty_before_next_scenario(tmp_path, raised):
    class Scheduler:
        def run_benchmark_scenario(self, **kwargs):
            if raised:
                raise TimeoutError("scenario still running")
            return {"success": False, "outcome_unknown": True, "job_id": 321}

    runner = HardwareBenchmarkRunner(tmp_path / "benchmark.json", runtime=object(), scheduler=Scheduler())
    result = runner.run_benchmark_scenario(name="scheduler", contract={
        "scenario": "scheduler", "required_fields": ["some_metric"],
    })
    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    if not raised:
        assert result["job_id"] == 321
