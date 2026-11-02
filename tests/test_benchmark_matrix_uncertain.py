import pytest

from tools.benchmark_surfaces import _run_t12_matrix


class Runner:
    config = {"models": {"reasoning": "model", "fast_code": "model", "heavy_code": "model"}}

    def __init__(self, first_result):
        self.first_result = first_result
        self.case_calls = []
        self.scenario_calls = []

    def run_t12_case(self, **kwargs):
        self.case_calls.append(kwargs)
        return self.first_result

    def run_benchmark_scenario(self, **kwargs):
        self.scenario_calls.append(kwargs)
        return {"success": False}


@pytest.mark.parametrize("result", [
    {"success": False, "outcome_unknown": True, "job_id": 917, "timed_out": True},
    {"success": False, "in_progress": True, "job_id": 917},
    {"success": False, "timed_out": True, "job_id": 917},
    {"success": True, "timed_out": True, "job_id": 917},
])
def test_matrix_stops_after_unconfirmed_case(result):
    runner = Runner(result)
    report = _run_t12_matrix(runner, repetitions=2, concurrency_limit=2)
    assert len(runner.case_calls) == 1
    assert runner.scenario_calls == []
    assert report["accepted"] is False
    assert report["outcome_unknown"] is True
    assert report["job_id"] == 917


def test_matrix_stops_after_untyped_timeout():
    class TimeoutRunner(Runner):
        def run_t12_case(self, **kwargs):
            self.case_calls.append(kwargs)
            raise TimeoutError("caller timed out")

    runner = TimeoutRunner({})
    report = _run_t12_matrix(runner, repetitions=2, concurrency_limit=2)
    assert len(runner.case_calls) == 1
    assert runner.scenario_calls == []
    assert report["outcome_unknown"] is True


def test_known_unsent_failure_does_not_claim_unknown():
    runner = Runner({"success": False, "timed_out": True, "request_not_sent": True})
    report = _run_t12_matrix(runner, repetitions=1, concurrency_limit=2)
    assert len(runner.case_calls) > 1
    assert report.get("outcome_unknown") is not True


def test_matrix_stops_after_unconfirmed_scenario():
    class ScenarioRunner(Runner):
        def run_benchmark_scenario(self, **kwargs):
            self.scenario_calls.append(kwargs)
            return {"success": False, "outcome_unknown": True, "job_id": "job-42"}

    runner = ScenarioRunner({"success": True})
    report = _run_t12_matrix(runner, repetitions=1, concurrency_limit=2)
    assert len(runner.case_calls) > 1
    assert len(runner.scenario_calls) == 1
    assert report["outcome_unknown"] is True
    assert report["job_id"] == "job-42"
    assert report["accepted"] is False
