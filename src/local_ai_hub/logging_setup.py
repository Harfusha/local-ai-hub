from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
from pathlib import Path
from typing import Any


_listener: logging.handlers.QueueListener | None = None
_log_path: Path | None = None
_previous_propagate: bool | None = None


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
    logger.setLevel(level)

    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = (logs_dir / "hub.log").resolve()
    if logger.handlers and _listener is not None and _log_path == log_path:
        logger.propagate = False
        for handler in _listener.handlers:
            handler.setLevel(level)
        return logger
    if _listener is not None or logger.handlers:
        shutdown_logging()
    if _previous_propagate is None:
        _previous_propagate = logger.propagate
    logger.propagate = False

    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=queue_size)
    logger.addHandler(_DropQueueHandler(q))

    handler = SafeWindowsRotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _listener = logging.handlers.QueueListener(q, handler, respect_handler_level=True)
    _log_path = log_path
    _listener.start()
    return logger


def shutdown_logging() -> None:
    global _listener, _log_path, _previous_propagate
    listener = _listener
    _listener = None
    _log_path = None
    listener_handlers = set(listener.handlers) if listener is not None else set()
    if listener is not None:
        try:
            listener.stop()
        finally:
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
