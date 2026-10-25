"""Exercise the queue runner against the canonical model-free async API."""

import sys
from types import SimpleNamespace

import pytest

from tools import benchmark_queue_admission as benchmark


@pytest.mark.parametrize("cancel_first_fails", [False, True])
def test_queue_runner_uses_canonical_submit_and_cleanup(tmp_path, monkeypatch, cancel_first_fails):
    submissions = []
    cancellations = []
    closed = []

    class Jobs:
        def stats(self):
            return {"counts": {}, "counts_truncated": False}

        def submit(self, action, payload, *, dispatch_delay_seconds):
            assert action == "reason"
            assert dispatch_delay_seconds == 30.0
            submissions.append(payload)
            return {"success": True, "job_id": payload["task_id"]}

        def cancel(self, job_id):
            cancellations.append(job_id)
            if cancel_first_fails and cancellations.count(job_id) == 1:
                return {"success": False, "state": "queued"}
            return {"success": True, "state": "cancelled"}

    class App:
        def __init__(self, config):
            self.async_jobs = Jobs()

        def close(self):
            closed.append(True)

    monkeypatch.setitem(sys.modules, "local_ai_hub.app", SimpleNamespace(LocalAIApp=App))
    result = benchmark.run_queue_benchmark(
        state_dir=tmp_path / "output", scratch_dir=tmp_path / "scratch",
        checkpoint_path=tmp_path / "checkpoint.json", run_id="canonical-smoke",
        light_repetitions=2, concurrency=(1, 4),
    )
    assert len(submissions) == 10
    assert len(cancellations) == (20 if cancel_first_fails else 10)
    assert len({item["task_id"] for item in submissions}) == 10
    assert closed == [True]
    assert result["success"] is (not cancel_first_fails)
    assert "TypeError" not in str(result)
    import json
    saved = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    level = saved["progress"]["queue_admission"]["by_concurrency"]["4"]
    assert len(level["decision_samples"]) == 8
    assert all(burst["offered_concurrency"] == 4 for burst in level["bursts"])
    assert all(1 <= burst["observed_active_concurrency"] <= 4 for burst in level["bursts"])
    assert all(sample["enqueue_ms"] is not None and sample["rejection_ms"] is None
               for sample in level["decision_samples"])


def test_queue_checkpoint_rejects_other_runner_and_preserves_progress(tmp_path):
    path = tmp_path / "checkpoint.json"
    scratch = tmp_path / "scratch"
    checkpoint = benchmark._BenchmarkCheckpoint(
        path, run_fingerprint="current", scratch_path=scratch, resume=False,
    )
    checkpoint.save_progress("queue_admission", {"next_repetition": 2})
    original = path.read_bytes()
    with pytest.raises(ValueError, match="fingerprint"):
        benchmark._BenchmarkCheckpoint(
            path, run_fingerprint="old", scratch_path=scratch, resume=True,
        )
    assert path.read_bytes() == original
    resumed = benchmark._BenchmarkCheckpoint(
        path, run_fingerprint="current", scratch_path=scratch, resume=True,
    )
    assert resumed.stage_progress("queue_admission") == {"next_repetition": 2}
    with pytest.raises(ValueError, match="exists"):
        benchmark._BenchmarkCheckpoint(
            path, run_fingerprint="current", scratch_path=scratch, resume=False,
        )
