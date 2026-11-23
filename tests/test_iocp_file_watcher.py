"""Unit tests for Windows Kernel IOCP File Watcher."""

import sys
import tempfile
import time
from pathlib import Path

import pytest
from local_ai_hub.iocp_file_watcher import FileChangeEvent, IOCPFileWatcher


@pytest.mark.skipif(sys.platform != "win32", reason="Windows IOCP tests require win32 platform")
def test_iocp_watcher_live_file_events() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        watch_path = Path(tmp_dir)
        captured_events: list[FileChangeEvent] = []

        def _on_event(evt: FileChangeEvent):
            captured_events.append(evt)

        watcher = IOCPFileWatcher(
            directory=watch_path,
            recursive=True,
            debounce_ms=50.0,
            callback=_on_event,
        )
        watcher.start()

        try:
            # Create a file
            test_file = watch_path / "hello.py"
            test_file.write_text("print('hello')\n", encoding="utf-8")

            # Wait for kernel event propagation
            time.sleep(0.3)

            events = watcher.poll_events()
            all_events = captured_events + events
            assert len(all_events) > 0
            paths = [e.path for e in all_events]
            assert any("hello.py" in p for p in paths)

            # Modify file
            test_file.write_text("print('updated')\n", encoding="utf-8")
            time.sleep(0.3)

            events2 = watcher.poll_events()
            all_events2 = captured_events + events2
            assert len(all_events2) >= 2
        finally:
            watcher.stop()


def test_iocp_watcher_graceful_stop_without_start() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        watcher = IOCPFileWatcher(directory=tmp_dir)
        # Should not raise exception
        watcher.stop()
        events = watcher.poll_events()
        assert events == []
