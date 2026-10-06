from __future__ import annotations

import socket

import pytest

from tools import benchmark_context_pack_quality as benchmark


def test_network_guard_fails_closed_for_socket_and_subprocess() -> None:
    with benchmark._offline_network_guard() as guard:
        with pytest.raises(OSError, match="offline benchmark"):
            socket.create_connection(("example.invalid", 443), timeout=0.01)
        with socket.socket() as sock, pytest.raises(OSError, match="offline benchmark"):
            sock.sendto(b"blocked", ("127.0.0.1", 9))
        with pytest.raises(OSError, match="offline benchmark"):
            benchmark.subprocess.Popen(["not-started"])

    assert guard.report() == {
        "enforced": True,
        "outbound_attempts": 3,
        "blocked_calls": ["socket.create_connection", "socket.sendto", "subprocess.Popen"],
        "offline_environment": True,
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"cache_hit": False, "coalesced": False, "cache_layer": "miss"}, "miss"),
        ({"adaptive_context_pack": {"cache_hit": True, "cache_layer": "memory"}}, "hit"),
        ({"workspace_cache": {"hit": True}, "coalesced": True}, "coalesced"),
        ({"cache_hit": False, "workspace_cache": {"hit": True}}, "mixed"),
        ({"retrieval": {"backend_states": {"lexical": "used"}}}, "not_reported"),
    ],
)
def test_cache_observation_reports_only_service_evidence(payload: dict, expected: str) -> None:
    observation = benchmark._cache_observation(payload)
    assert observation["state"] == expected
    assert observation["reported"] is (expected != "not_reported")


def test_cache_summary_checks_cold_miss_and_warm_hit_without_assuming_them() -> None:
    summary = benchmark._cache_summary(
        [{"state": "miss", "reported": True}, {"state": "hit", "reported": True}],
        [{"state": "hit", "reported": True}, {"state": "hit", "reported": True}],
    )
    assert summary["cold_first_miss"] == {"expected": "miss", "observed": "miss", "passed": True}
    assert summary["warm_hits"] == {
        "expected": "hit", "observed": 2, "samples": 2, "reported_samples": 2, "passed": True,
    }

    unknown = benchmark._cache_summary([{"state": "not_reported", "reported": False}], [])
    assert unknown["cold_first_miss"]["passed"] is None
    assert unknown["warm_hits"]["passed"] is None


def test_percentile_uses_nearest_rank_for_meaningful_sample_set() -> None:
    samples = [float(value) for value in range(1, 101)]
    assert benchmark._percentile(samples, 0.50) == 50.0
    assert benchmark._percentile(samples, 0.95) == 95.0


@pytest.mark.parametrize("value", [0, 3, 99, 10_001])
def test_sample_count_rejects_uninformative_or_unbounded_values(value: int) -> None:
    with pytest.raises(ValueError, match="100..10000"):
        benchmark._normalize_sample_count(value)


def test_sample_count_is_parameterized_with_meaningful_default() -> None:
    assert benchmark._normalize_sample_count(None) == 100
    assert benchmark._normalize_sample_count(250) == 250


def test_run_benchmark_returns_structured_partial_report_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_after_one_sample(*, repetitions: int, concurrency_requests: int, progress: dict) -> dict:
        progress["stage"] = "cold"
        progress["cold_samples"].append({"latency_ms": 12.5, "cache": {"state": "miss", "reported": True}})
        raise RuntimeError("fixture request failed")

    monkeypatch.setattr(benchmark, "_run_benchmark", fail_after_one_sample)
    report = benchmark.run_benchmark()

    assert report["success"] is False
    assert report["status"] == "partial"
    assert report["partial_report"]["stage"] == "cold"
    assert len(report["partial_report"]["cold_samples"]) == 1
    assert report["errors"] == [{"type": "RuntimeError", "message": "fixture request failed"}]
    assert report["network_policy"]["enforced"] is True


def test_run_benchmark_marks_swallowed_network_attempt_as_policy_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    def attempt_network(*, repetitions: int, concurrency_requests: int, progress: dict) -> dict:
        try:
            socket.create_connection(("example.invalid", 443), timeout=0.01)
        except OSError:
            pass
        return {"success": True, "status": "complete", "sample_count": repetitions}

    monkeypatch.setattr(benchmark, "_run_benchmark", attempt_network)
    report = benchmark.run_benchmark()

    assert report["success"] is False
    assert report["status"] == "policy_violation"
    assert report["network_policy"]["outbound_attempts"] == 1
    assert report["errors"][0]["type"] == "ExternalAccessBlocked"
