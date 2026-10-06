"""Repeat the original T18 record_error/flush/SQLite sequence with failure diagnostics."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from local_ai_hub.telemetry import TelemetryStore


def main(iterations: int = 50) -> int:
    failures = 0
    for iteration in range(iterations):
        with tempfile.TemporaryDirectory(prefix="t18-telemetry-flush-") as tmp:
            store = TelemetryStore(Path(tmp) / "telemetry", enabled=True)
            started = time.monotonic()
            try:
                store.record_error(
                    "provider",
                    "generate",
                    RuntimeError(
                        'prompt="PROMPT-PRIVATE-SENTINEL" '
                        'source_text="SOURCE-PRIVATE-SENTINEL" '
                        'api_key="API-SECRET-SENTINEL" '
                        r"file=C:\private\project\source.py"
                    ),
                    retryable=True,
                    recovered=True,
                )
                flushed = store.flush(1)
                elapsed = time.monotonic() - started
                if not flushed:
                    failures += 1
                    with store._stats_lock:
                        stats = dict(store._stats)
                    diagnostic = {
                        "iteration": iteration,
                        "flush": False,
                        "elapsed_seconds": round(elapsed, 6),
                        "stats": stats,
                        "queue_size": store._queue.qsize(),
                        "writer_alive": bool(store._thread and store._thread.is_alive()),
                    }
                    try:
                        with store._connect() as con:
                            diagnostic["persisted_error_rows"] = con.execute(
                                "SELECT COUNT(*) FROM errors"
                            ).fetchone()[0]
                            diagnostic["persisted_events"] = con.execute(
                                "SELECT COUNT(*) FROM events"
                            ).fetchone()[0]
                    except Exception as exc:
                        diagnostic["read_error_type"] = type(exc).__name__
                    print(json.dumps(diagnostic, sort_keys=True))
                    return 1
            finally:
                store.close()
    print(json.dumps({"iterations": iterations, "flush_failures": failures}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
