from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
import pytest

from local_ai_hub.commands import CommandBroker, StreamMultiplexer, MultiplexEvent


def test_stream_multiplexer_buffers_and_emits_lines_atomically() -> None:
    multiplexer = StreamMultiplexer()
    # Write partial chunks
    events1 = multiplexer.write("worker-1", "stdout", "Hello ")
    assert events1 == []  # No complete line yet

    events2 = multiplexer.write("worker-1", "stdout", "World!\nSecond line\n")
    assert len(events2) == 2
    assert events2[0].text == "Hello World!"
    assert events2[0].source_id == "worker-1"
    assert events2[0].stream_name == "stdout"
    assert events2[0].sequence == 1
    assert events2[1].text == "Second line"
    assert events2[1].sequence == 2


def test_stream_multiplexer_flush_emits_unclosed_tail() -> None:
    multiplexer = StreamMultiplexer()
    multiplexer.write("worker-2", "stderr", "Unfinished error chunk")
    events = multiplexer.flush("worker-2")
    assert len(events) == 1
    assert events[0].text == "Unfinished error chunk"
    assert events[0].stream_name == "stderr"


def test_concurrent_writes_do_not_tear_lines() -> None:
    multiplexer = StreamMultiplexer()
    num_threads = 5
    lines_per_thread = 20

    def worker(worker_id: str) -> None:
        for i in range(lines_per_thread):
            # Send in small chunks to induce potential interleaving
            multiplexer.write(worker_id, "stdout", f"line {i:02d} ")
            time.sleep(0.001)
            multiplexer.write(worker_id, "stdout", f"from {worker_id}\n")

    threads = [
        threading.Thread(target=worker, args=(f"worker-{t}",))
        for t in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    multiplexer.flush()
    events = multiplexer.get_events()
    assert len(events) == num_threads * lines_per_thread

    # Verify every emitted line is intact and not torn
    for ev in events:
        assert ev.text.startswith("line ")
        assert f"from {ev.source_id}" in ev.text

    # Verify per-source filtered outputs
    for t in range(num_threads):
        worker_id = f"worker-{t}"
        source_out = multiplexer.get_source_output(worker_id, "stdout")
        for i in range(lines_per_thread):
            assert f"line {i:02d} from {worker_id}" in source_out


def test_format_unified_includes_tags() -> None:
    multiplexer = StreamMultiplexer()
    multiplexer.write("test-a", "stdout", "test a passed\n")
    multiplexer.write("test-b", "stderr", "test b failed\n")
    formatted = multiplexer.format_unified(tag_prefix=True)
    assert "[test-a:stdout] test a passed" in formatted
    assert "[test-b:stderr] test b failed" in formatted


def test_multiplexer_subscribers_receive_events_in_realtime() -> None:
    received = []
    multiplexer = StreamMultiplexer()
    multiplexer.subscribe(received.append)

    multiplexer.write("test-1", "stdout", "ping\n")
    assert len(received) == 1
    assert received[0].text == "ping"
    assert received[0].source_id == "test-1"


def test_command_broker_run_parallel_executes_and_multiplexes(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})

    py_cmd_1 = f'"{sys.executable}" -c "print(\'alpha line 1\'); print(\'alpha line 2\')"'
    py_cmd_2 = f'"{sys.executable}" -c "import sys; print(\'beta out\'); sys.stderr.write(\'beta err\\n\')"'

    commands = [
        {"id": "job-alpha", "cmd": py_cmd_1},
        {"id": "job-beta", "cmd": py_cmd_2},
    ]

    res = broker.run_parallel(commands, cwd=str(tmp_path), max_concurrency=2)
    assert res["success"] is True
    assert "job-alpha" in res["results"]
    assert "job-beta" in res["results"]
    assert res["results"]["job-alpha"]["success"] is True
    assert res["results"]["job-beta"]["success"] is True

    unified = res["multiplexed_output"]
    assert "[job-alpha:stdout] alpha line 1" in unified
    assert "[job-alpha:stdout] alpha line 2" in unified
    assert "[job-beta:stdout] beta out" in unified
    assert "[job-beta:stderr] beta err" in unified
