from local_ai_hub.commands import MultiplexEvent, StreamMultiplexer


def test_stream_multiplexer_orders_interleaved_lines_and_flushes_partial_output():
    ticks = iter((1.0, 2.0, 3.0))
    streams = StreamMultiplexer(clock_fn=lambda: next(ticks))

    assert streams.write("alpha", "stdout", "hel") == []
    first = streams.write("beta", "stderr", "error\npartial")
    second = streams.write("alpha", "stdout", "lo\n")
    final = streams.flush("beta")

    assert [event.text for event in first + second + final] == ["error", "hello", "partial"]
    assert [event.sequence for event in first + second + final] == [1, 2, 3]
    assert [event.timestamp for event in first + second + final] == [1.0, 2.0, 3.0]
    assert streams.get_source_output("alpha", "stdout") == "hello"
    assert streams.get_source_output("beta", "stderr") == "error\npartial"
    assert streams.format_unified() == (
        "[beta:stderr] error\n[alpha:stdout] hello\n[beta:stderr] partial"
    )
    assert streams.flush("missing") == []


def test_stream_multiplexer_subscribers_receive_events_and_failures_are_isolated():
    streams = StreamMultiplexer(clock_fn=lambda: 7.0)
    received: list[MultiplexEvent] = []

    def failing_subscriber(_event):
        raise RuntimeError("subscriber failed")

    streams.subscribe(failing_subscriber)
    streams.subscribe(received.append)
    emitted = streams.write("worker", "stdout", "done\n")

    assert received == emitted
    assert streams.get_events() == emitted
    assert emitted[0].to_dict() == {
        "source_id": "worker",
        "stream_name": "stdout",
        "text": "done",
        "timestamp": 7.0,
        "sequence": 1,
    }
