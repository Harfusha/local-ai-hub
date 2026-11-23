"""Unit tests for Zero-Copy Memory-Mapped Binary Event Log."""

import tempfile
from pathlib import Path
from local_ai_hub.mmap_event_log import MmapEventLogger


def test_mmap_event_log_write_and_read() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = Path(tmp_dir) / "test_events.bin"
        logger = MmapEventLogger(log_path, num_slots=32, slot_size=128)

        try:
            seq1 = logger.log_event(event_type=1, payload="Task initialized")
            seq2 = logger.log_event(event_type=2, payload="Preprocessing complete")
            seq3 = logger.log_event(event_type=3, payload="Tool called: search")

            assert seq1 == 1
            assert seq2 == 2
            assert seq3 == 3

            recent = logger.read_recent(limit=5)
            assert len(recent) == 3
            # Ordered newest first
            assert recent[0].seq == 3
            assert recent[0].payload == "Tool called: search"
            assert recent[0].event_type == 3

            assert recent[1].seq == 2
            assert recent[2].seq == 1
        finally:
            logger.close()


def test_mmap_event_log_ring_rollover() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = Path(tmp_dir) / "ring.bin"
        # Small ring: 4 slots
        logger = MmapEventLogger(log_path, num_slots=4, slot_size=64)

        try:
            for i in range(10):
                logger.log_event(event_type=1, payload=f"evt_{i}")

            recent = logger.read_recent(limit=4)
            assert len(recent) == 4
            # Should read latest 4 events: evt_9, evt_8, evt_7, evt_6
            assert recent[0].payload == "evt_9"
            assert recent[1].payload == "evt_8"
            assert recent[2].payload == "evt_7"
            assert recent[3].payload == "evt_6"
        finally:
            logger.close()
