import pytest
from src.local_ai_hub.persistent_shm_pool import PersistentSharedMemoryPool


def test_persistent_shm_pool_lifecycle():
    pool_name = "test_shm_pool_v9"
    with PersistentSharedMemoryPool(pool_name=pool_name, num_slots=2, slot_size_bytes=64 * 1024) as pool:
        # Acquire slot 0
        slot0 = pool.acquire_slot(timeout_seconds=1.0)
        assert slot0.slot_id == 0

        # Write data
        test_payload = b"Hello from Persistent SHM Pool! High-frequency vector exchange."
        written = slot0.write(test_payload)
        assert written == len(test_payload)

        # Read back via bytes
        read_back = slot0.read_bytes()
        assert read_back == test_payload

        # Read back via zero-copy memoryview
        view = slot0.get_view()
        assert bytes(view) == test_payload

        # Acquire slot 1
        slot1 = pool.acquire_slot(timeout_seconds=1.0)
        assert slot1.slot_id == 1

        # Trying to acquire 3rd slot should timeout
        with pytest.raises(TimeoutError):
            pool.acquire_slot(timeout_seconds=0.05)

        # Release slot 0 and re-acquire
        pool.release_slot(slot0)
        slot0_reacquired = pool.acquire_slot(timeout_seconds=1.0)
        assert slot0_reacquired.slot_id == 0

        pool.release_slot(slot0_reacquired)
        pool.release_slot(slot1)
