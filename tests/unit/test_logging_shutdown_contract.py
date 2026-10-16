"""Stop saturated listeners safely, without unbounded waits or early closes."""

import logging
import queue

import pytest

from local_ai_hub import logging_setup


class WorkerProbe:
    def __init__(self, listener, finish=True):
        self.listener = listener
        self.finish = finish
        self.alive = True
        self.timeouts = []

    def join(self, timeout):
        self.timeouts.append(timeout)
        if self.finish:
            assert self.listener.queue.get_nowait() is self.listener._sentinel
            self.listener.queue.task_done()
            self.alive = False

    def is_alive(self):
        return self.alive


class HandlerProbe(logging.Handler):
    def __init__(self):
        super().__init__()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        super().close()


def test_full_queue_stop_balances_discarded_records():
    pending = queue.Queue(maxsize=1)
    pending.put_nowait(object())
    listener = logging_setup._BoundedQueueListener(pending)
    worker = WorkerProbe(listener)
    listener._thread = worker
    listener.stop()
    assert listener._thread is None
    assert pending.empty()
    assert pending.unfinished_tasks == 0
    assert 0 <= worker.timeouts[0] <= logging_setup._LOGGING_STOP_TIMEOUT_SECONDS


def test_timeout_preserves_listener_for_later_cleanup():
    pending = queue.Queue(maxsize=2)
    listener = logging_setup._BoundedQueueListener(pending)
    worker = WorkerProbe(listener, finish=False)
    listener._thread = worker
    with pytest.raises(RuntimeError, match="shutdown deadline"):
        listener.stop()
    assert listener._thread is worker
    assert listener._stop_requested
    assert pending.qsize() == 1
    worker.finish = True
    listener.stop()
    assert listener._thread is None
    assert pending.unfinished_tasks == 0


def test_sentinel_admission_respects_shared_deadline(monkeypatch):
    pending = queue.Queue(maxsize=1)
    record = object()
    pending.put_nowait(record)
    listener = logging_setup._BoundedQueueListener(pending)
    worker = WorkerProbe(listener)
    listener._thread = worker
    ticks = iter([0.0, logging_setup._LOGGING_STOP_TIMEOUT_SECONDS])
    with monkeypatch.context() as context:
        context.setattr(logging_setup.time, "monotonic", lambda: next(ticks))
        with pytest.raises(RuntimeError, match="sentinel deadline"):
            listener.stop()
    assert listener._thread is worker
    assert not listener._stop_requested
    assert not worker.timeouts
    assert pending.get_nowait() is record
    pending.task_done()


def test_shutdown_timeout_keeps_live_handlers_and_identity(tmp_path, monkeypatch):
    handler = HandlerProbe()
    logger = logging.Logger("isolated-logging-shutdown")
    attached = logging.NullHandler()
    logger.addHandler(attached)
    logger.propagate = False
    listener = logging_setup._BoundedQueueListener(queue.Queue(maxsize=1), handler)
    worker = WorkerProbe(listener, finish=False)
    listener._thread = worker
    path = tmp_path / "hub.log"
    monkeypatch.setattr(logging_setup, "_listener", listener)
    monkeypatch.setattr(logging_setup, "_log_path", path)
    monkeypatch.setattr(logging_setup, "_previous_propagate", True)
    with monkeypatch.context() as context:
        context.setattr(logging_setup.logging, "getLogger", lambda name=None: logger)
        try:
            with pytest.raises(RuntimeError, match="shutdown deadline"):
                logging_setup.shutdown_logging()
            assert logging_setup._listener is listener
            assert logging_setup._log_path == path
            assert handler.close_calls == 0
            assert logger.handlers == [attached]
            assert logger.propagate is False
        finally:
            worker.finish = True
            logging_setup.shutdown_logging()
    assert handler.close_calls == 1
    assert logging_setup._listener is None
    assert logging_setup._log_path is None
    assert not logger.handlers
    assert logger.propagate is True


def test_listener_start_failure_does_not_publish_partial_logger(tmp_path, monkeypatch):
    logger = logging.Logger("isolated-logging-startup")
    logger.setLevel(logging.WARNING)
    monkeypatch.setattr(logging_setup, "_listener", None)
    monkeypatch.setattr(logging_setup, "_log_path", None)
    monkeypatch.setattr(logging_setup, "_previous_propagate", None)

    def fail_start(self):
        raise RuntimeError("worker creation failed")

    monkeypatch.setattr(logging_setup._BoundedQueueListener, "start", fail_start)
    created_handlers = []
    handler_class = logging_setup.SafeWindowsRotatingFileHandler

    def record_handler(*args, **kwargs):
        handler = handler_class(*args, **kwargs)
        created_handlers.append(handler)
        return handler

    monkeypatch.setattr(logging_setup, "SafeWindowsRotatingFileHandler", record_handler)
    with monkeypatch.context() as context:
        context.setattr(logging_setup.logging, "getLogger", lambda name=None: logger)
        with pytest.raises(RuntimeError, match="worker creation failed"):
            logging_setup.configure_logging(tmp_path, {"logging": {"level": "DEBUG"}})
    assert logger.level == logging.WARNING
    assert logger.propagate is True
    assert not logger.handlers
    assert logging_setup._listener is None
    assert logging_setup._log_path is None
    assert len(created_handlers) == 1
    assert created_handlers[0]._closed
