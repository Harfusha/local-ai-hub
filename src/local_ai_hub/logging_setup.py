from __future__ import annotations

import logging
import logging.handlers
import queue
from pathlib import Path
from typing import Any


_listener: logging.handlers.QueueListener | None = None


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
    global _listener
    cfg = config.get("logging", {})
    logger = logging.getLogger("local_ai_hub")
    level = getattr(logging, str(cfg.get("level", "INFO")).upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers and _listener is not None:
        return logger
    if logger.handlers and _listener is None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)

    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=max(100, int(cfg.get("queue_size", 5000))))
    logger.addHandler(_DropQueueHandler(q))

    handler = SafeWindowsRotatingFileHandler(
        logs_dir / "hub.log",
        maxBytes=max(256 * 1024, int(cfg.get("max_bytes", 5_000_000))),
        backupCount=max(1, int(cfg.get("backup_count", 5))),
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _listener = logging.handlers.QueueListener(q, handler, respect_handler_level=True)
    _listener.start()
    return logger


def shutdown_logging() -> None:
    global _listener
    if _listener is not None:
        try:
            _listener.stop()
        finally:
            _listener = None
