from __future__ import annotations

import logging
import logging.handlers
import queue
from pathlib import Path
from typing import Any


_listener: logging.handlers.QueueListener | None = None
_log_path: Path | None = None


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
            pass

def configure_logging(state_dir: Path, config: dict[str, Any]) -> logging.Logger:
    """Configure non-blocking rotating operational logs.

    Logs contain runtime/component diagnostics only. Callers must not put prompts,
    source text or model output into log messages.
    """
    global _listener, _log_path
    cfg = config.get("logging", {})
    logger = logging.getLogger("local_ai_hub")
    level = getattr(logging, str(cfg.get("level", "INFO")).upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = (logs_dir / "hub.log").resolve()
    if logger.handlers and _listener is not None and _log_path == log_path:
        for handler in _listener.handlers:
            handler.setLevel(level)
        return logger
    if _listener is not None or logger.handlers:
        shutdown_logging()

    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=max(100, int(cfg.get("queue_size", 5000))))
    logger.addHandler(_DropQueueHandler(q))

    handler = SafeWindowsRotatingFileHandler(
        log_path,
        maxBytes=max(256 * 1024, int(cfg.get("max_bytes", 5_000_000))),
        backupCount=max(1, int(cfg.get("backup_count", 5))),
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
    global _listener, _log_path
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
