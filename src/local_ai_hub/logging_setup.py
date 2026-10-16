from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
import time
from pathlib import Path
from typing import Any


_listener: logging.handlers.QueueListener | None = None
_log_path: Path | None = None
_previous_propagate: bool | None = None
_LOGGING_STOP_TIMEOUT_SECONDS = 2.0


class _BoundedQueueListener(logging.handlers.QueueListener):
    """Stop within a deadline without closing a handler used by a live worker."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stop_requested = False

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("logging listener already started")
        self._stop_requested = False
        super().start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        deadline = time.monotonic() + _LOGGING_STOP_TIMEOUT_SECONDS
        if not self._stop_requested:
            while True:
                try:
                    self.enqueue_sentinel()
                    self._stop_requested = True
                    break
                except queue.Full:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("logging listener sentinel deadline exceeded")
                    # Operational log metadata is lossy; make room for shutdown.
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        continue
                    self.queue.task_done()
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            raise RuntimeError("logging listener shutdown deadline exceeded")
        self._thread = None


class _DropQueueHandler(logging.handlers.QueueHandler):
    """Never let operational logging back-pressure foreground work."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = super().prepare(record)
        from . import trace_context
        record.trace_context = trace_context.current()
        return record

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            pass


class SafeWindowsRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def doRollover(self):
        try:
            super().doRollover()
        except (PermissionError, OSError):
            if self.stream is None:
                try:
                    self.stream = self._open()
                except OSError:
                    pass

def configure_logging(state_dir: Path, config: dict[str, Any]) -> logging.Logger:
    """Configure non-blocking rotating operational logs.

    Logs contain runtime/component diagnostics only. Callers must not put prompts,
    source text or model output into log messages.
    """
    global _listener, _log_path, _previous_propagate
    if not isinstance(state_dir, Path) or "\x00" in str(state_dir):
        raise ValueError("state_dir must be a Path without null bytes")
    if not isinstance(config, dict):
        raise TypeError("logging configuration must be a mapping")
    cfg = config.get("logging", {})
    if not isinstance(cfg, dict):
        raise TypeError("logging settings must be a mapping")
    level_name = cfg.get("level", "INFO")
    if not isinstance(level_name, str) or not level_name or "\x00" in level_name:
        raise ValueError("logging level must name a standard logging level")
    level = getattr(logging, level_name.upper(), None)
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError("logging level must name a standard logging level")

    def positive_integer(name: str, default: int) -> int:
        value = cfg.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= sys.maxsize:
            raise ValueError(f"logging {name} must be a positive integer at most sys.maxsize")
        return value

    queue_size = max(100, positive_integer("queue_size", 5000))
    max_bytes = max(256 * 1024, positive_integer("max_bytes", 5_000_000))
    backup_count = positive_integer("backup_count", 5)
    logger = logging.getLogger("local_ai_hub")

    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = (logs_dir / "hub.log").resolve()
    if logger.handlers and _listener is not None and _log_path == log_path:
        logger.setLevel(level)
        logger.propagate = False
        for handler in _listener.handlers:
            handler.setLevel(level)
        return logger
    if _listener is not None or logger.handlers:
        shutdown_logging()
    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=queue_size)

    handler = SafeWindowsRotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    listener = _BoundedQueueListener(q, handler, respect_handler_level=True)
    try:
        listener.start()
    except Exception:
        handler.close()
        raise
    if _previous_propagate is None:
        _previous_propagate = logger.propagate
    logger.setLevel(level)
    logger.propagate = False
    logger.addHandler(_DropQueueHandler(q))
    _listener = listener
    _log_path = log_path
    return logger


def shutdown_logging() -> None:
    global _listener, _log_path, _previous_propagate
    listener = _listener
    listener_handlers = set(listener.handlers) if listener is not None else set()
    if listener is not None:
        listener.stop()
    _listener = None
    _log_path = None
    for handler in listener_handlers:
        handler.close()

    logger = logging.getLogger("local_ai_hub")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        if handler not in listener_handlers:
            handler.close()
    if _previous_propagate is not None:
        logger.propagate = _previous_propagate
        _previous_propagate = None
