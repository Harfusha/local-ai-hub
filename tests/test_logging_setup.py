from __future__ import annotations

import logging
import queue
import time

import pytest

from local_ai_hub import logging_setup
from local_ai_hub.logging_setup import _DropQueueHandler, configure_logging, shutdown_logging


@pytest.fixture(autouse=True)
def reset_logging() -> None:
    shutdown_logging()
    yield
    shutdown_logging()


def test_reconfigure_logging_uses_new_state_directory(tmp_path):
    first_state = tmp_path / "first"
    second_state = tmp_path / "second"

    logger = configure_logging(first_state, {"logging": {"level": "INFO"}})
    logger.error("first destination")
    logger = configure_logging(second_state, {"logging": {"level": "INFO"}})
    logger.error("second destination")
    shutdown_logging()

    first_log = (first_state / "logs" / "hub.log").read_text(encoding="utf-8")
    second_log = (second_state / "logs" / "hub.log").read_text(encoding="utf-8")
    assert "first destination" in first_log
    assert "second destination" not in first_log
    assert "second destination" in second_log


def test_shutdown_detaches_and_closes_logging_handlers(tmp_path):
    logger = configure_logging(tmp_path, {"logging": {"level": "INFO"}})
    logger.error("close me")
    listener = logging_setup._listener
    assert listener is not None
    file_handler = listener.handlers[0]

    shutdown_logging()

    assert logger.handlers == []
    assert file_handler.stream is None


def test_full_logging_queue_drops_without_blocking():
    log_queue = queue.Queue(maxsize=1)
    handler = _DropQueueHandler(log_queue)
    record = logging.LogRecord("local_ai_hub", logging.INFO, __file__, 1, "drop", (), None)
    handler.enqueue(record)

    started = time.monotonic()
    handler.enqueue(record)

    assert time.monotonic() - started < 0.1
