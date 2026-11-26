from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler, Job


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
