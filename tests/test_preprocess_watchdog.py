"""Tests for PreprocessWatchdogDaemon debouncing and file change tracking."""

import os
import tempfile
import time

from src.local_ai_hub.preprocess_watchdog import (
    PreprocessWatchdogDaemon,
    _DebouncedEventHandler,
)


def test_debounced_event_handler_coalescing():
    dispatched = []

    def on_change(root: str, rel_path: str, change_type: str):
        dispatched.append((rel_path, change_type))

    with tempfile.TemporaryDirectory() as tmpdir:
        handler = _DebouncedEventHandler(
            root=tmpdir,
            callback=on_change,
            debounce_window_s=0.1,  # Fast 100ms for unit testing
        )

        dummy_file = os.path.join(tmpdir, "main.py")

        class MockEvent:
            is_directory = False
            src_path = dummy_file

        # Trigger 5 rapid modifications
        for _ in range(5):
            handler.on_modified(MockEvent())

        assert handler.events_received == 5
        assert handler.events_debounced == 4

        # Wait for debounce window to fire
        time.sleep(0.25)

        assert len(dispatched) == 1
        assert dispatched[0][0] == "main.py"
        assert dispatched[0][1] == "modified"
        assert handler.callbacks_dispatched == 1


def test_watchdog_daemon_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        daemon = PreprocessWatchdogDaemon(debounce_window_s=0.1)
        started = daemon.start([tmpdir])
        assert started is True

        stats = daemon.stats()
        assert stats.running is True
        assert len(stats.watched_roots) == 1

        daemon.stop()
        stats_after = daemon.stats()
        assert stats_after.running is False
