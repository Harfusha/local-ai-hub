"""Unit tests for Pre-emptive Stream Multiplexing and Fast Cancellation."""

import time
from local_ai_hub.stream_multiplexer import (
    PRIORITY_BACKGROUND,
    PRIORITY_BATCH,
    PRIORITY_CRITICAL_STEERING,
    PRIORITY_INTERACTIVE,
    CancellationToken,
    StreamMultiplexer,
)


def _infinite_stream(label: str):
    count = 0
    while True:
        yield f"{label}_{count}"
        count += 1


def _finite_stream(label: str, count: int):
    for i in range(count):
        yield f"{label}_{i}"


def test_stream_priority_ordering() -> None:
    multiplexer = StreamMultiplexer(preempt_background_on_interactive=False)

    # Register batch and interactive streams
    multiplexer.register_stream("batch_1", _finite_stream("batch", 5), priority=PRIORITY_BATCH)
    multiplexer.register_stream("user_prompt", _finite_stream("interactive", 3), priority=PRIORITY_INTERACTIVE)

    chunks = []
    while multiplexer.active_stream_count() > 0:
        res = multiplexer.next_token()
        if res:
            chunks.append(res)

    # Interactive tokens must be yielded before batch tokens finish
    interactive_chunks = [c for tid, c in chunks if tid == "user_prompt"]
    assert len(interactive_chunks) == 3
    # The first 3 emitted items should be from interactive stream
    assert [tid for tid, _ in chunks[:3]] == ["user_prompt", "user_prompt", "user_prompt"]


def test_preemption_of_background_stream() -> None:
    multiplexer = StreamMultiplexer(preempt_background_on_interactive=True)

    bg_token = multiplexer.register_stream("bg_card", _infinite_stream("bg"), priority=PRIORITY_BACKGROUND)
    assert not bg_token.is_cancelled()

    # Read 2 bg tokens
    t1 = multiplexer.next_token()
    t2 = multiplexer.next_token()
    assert t1[0] == "bg_card"
    assert t2[0] == "bg_card"

    # Now interactive request arrives
    inter_token = multiplexer.register_stream("user_req", _finite_stream("user", 2), priority=PRIORITY_INTERACTIVE)

    # Background stream should have been preempted
    assert bg_token.is_cancelled()
    assert "Preempted" in bg_token.reason

    # Next tokens should be from user_req
    t3 = multiplexer.next_token()
    assert t3[0] == "user_req"


def test_explicit_cancellation() -> None:
    multiplexer = StreamMultiplexer()

    token = multiplexer.register_stream("long_query", _infinite_stream("chunk"), priority=PRIORITY_INTERACTIVE)
    assert multiplexer.active_stream_count() == 1

    t1 = multiplexer.next_token()
    assert t1[0] == "long_query"

    # Explicit cancel
    cancelled = multiplexer.cancel_stream("long_query", reason="User pressed Stop")
    assert cancelled
    assert token.is_cancelled()
    assert token.reason == "User pressed Stop"
    assert multiplexer.active_stream_count() == 0
    assert multiplexer.next_token() is None
