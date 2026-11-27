import multiprocessing

import pytest

from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler, Job


def _candidate_scheduler_gpu_state(config, result_queue):
    scheduler = AffinityScheduler(object(), config)
    try:
        snapshot = scheduler._external_gpu_store.capacity_snapshot()
        result_queue.put({
            "admission": scheduler.status()["gpu_admission_state"],
            "lease_ids": [row["lease_id"] for row in snapshot["leases"]] if isinstance(snapshot, dict) else [],
        })
    finally:
        scheduler.close()


def test_scheduler_status_tracks_external_reservation_fence(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    scheduler = AffinityScheduler(object(), config)
    external_store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation")
    digest = "a" * 64
    try:
        assert scheduler.status()["gpu_admission_state"] == "available"
        assert external_store.claim_internal(digest) is True
        assert scheduler.status()["gpu_admission_state"] == "external_reservation"
    finally:
        external_store.release_internal(digest)
        scheduler.close()


@pytest.mark.parametrize("process_alive", [False, True, None])
def test_scheduler_reaps_only_confirmed_dead_opencode_owner(tmp_path, monkeypatch, process_alive):
    scheduler = AffinityScheduler(object(), {"server": {"state_dir": str(tmp_path)}})
    store = scheduler._external_gpu_store
    reservation = None
    try:
        reservation = store.reserve(
            "c" * 64,
            owner="opencode:2147483647:session-1",
            owner_vram_budget_bytes=4 * 1024**3,
        )
        assert reservation is not None
        monkeypatch.setattr(
            "local_ai_hub.process_utils.process_is_alive",
            lambda _pid: process_alive,
        )

        scheduler.status()

        assert (store.read() is None) is (process_alive is False)
    finally:
        if reservation is not None:
            current = store.read()
            if current is not None:
                store.release(current["token_digest"], current["generation"])
        scheduler.close()


def test_scheduler_status_reads_external_state_outside_condition_lock(tmp_path):
    scheduler = AffinityScheduler(object(), {"server": {"state_dir": str(tmp_path)}})
    scheduler.close()
    scheduler._pending.append(
        Job(id=1, model="model", source="test", priority=1, execute=lambda: {})
    )
    calls = {}
    try:
        for name in (
            "_external_gpu_reserved",
            "_external_gpu_blocks_scheduler",
            "_capacity_sharing_active",
            "_cache_stats",
        ):
            original = getattr(scheduler, name)

            def outside_lock(*args, _name=name, _original=original, **kwargs):
                assert not scheduler._cond._is_owned(), f"{_name} ran under scheduler lock"
                calls[_name] = calls.get(_name, 0) + 1
                return _original(*args, **kwargs)

            setattr(scheduler, name, outside_lock)

        state = scheduler.status()

        assert state["queued"] == 1
        assert state["pending_jobs"][0]["wait_reason"] == "model-affinity"
        assert calls == {
            "_external_gpu_reserved": 1,
            "_external_gpu_blocks_scheduler": 1,
            "_capacity_sharing_active": 1,
            "_cache_stats": 1,
        }
    finally:
        scheduler.close()
def test_isolated_scheduler_can_share_hub_gpu_fence_with_separate_state(tmp_path):
    primary_state = tmp_path / "primary"
    candidate_state = tmp_path / "candidate"
    primary_state.mkdir()
    candidate_state.mkdir()
    primary = AffinityScheduler(object(), {"server": {"state_dir": str(primary_state)}})
    candidate_config = {
        "server": {"state_dir": str(candidate_state)},
        "scheduler": {
            "external_gpu_reservation_path": str(primary_state / "external-gpu-reservation"),
        },
    }
    digest = "b" * 64
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = None
    reservation = None
    lease = None
    try:
        reservation = primary._external_gpu_store.reserve(
            digest, owner="primary-test", owner_vram_budget_bytes=4 * 1024**3,
        )
        assert reservation is not None
        lease = primary._external_gpu_store.acquire_capacity_lease(
            owner="scheduler-job:test", requested_bytes=1024**3,
            total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
            expected_reservation_generation=reservation["generation"],
        )
        assert lease is not None
        process = context.Process(target=_candidate_scheduler_gpu_state, args=(candidate_config, result_queue))
        process.start()
        assert result_queue.get(timeout=15) == {
            "admission": "available", "lease_ids": [lease["lease_id"]],
        }
        process.join(timeout=15)
        assert process.exitcode == 0
    finally:
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=5)
        result_queue.close()
        if lease is not None:
            primary._external_gpu_store.release_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])
        if reservation is not None:
            primary._external_gpu_store.release(reservation["token_digest"], reservation["generation"])
        primary.close()


@pytest.mark.parametrize("path", ["relative/external-gpu-reservation", "C:/temp/wrong-name"])
def test_config_rejects_noncanonical_shared_gpu_fence_path(path):
    with pytest.raises(ConfigError, match="external_gpu_reservation_path"):
        validate_config({"scheduler": {"external_gpu_reservation_path": path}})
