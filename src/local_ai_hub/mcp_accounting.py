from __future__ import annotations

import functools
import inspect
import ntpath
import os
import queue
import threading
import time
from typing import Any

from local_ai_hub.token_accounting import json_tokens

__all__ = [
    "current_accounting_time",
    "functools",
    "inspect",
    "normalize_accounting_root",
    "ntpath",
    "os",
    "schema_descriptor",
    "time",
    "tool_catalog_schema_tokens",
]


def schema_descriptor(tool_name: str, fn_lookup: Any = None, desc_map: Any = None) -> dict[str, Any]:
    """Return one stable public-tool descriptor for token-cost estimation."""
    try:
        fn = None
        if callable(fn_lookup):
            fn = fn_lookup(tool_name)
        elif isinstance(fn_lookup, dict):
            fn = fn_lookup.get(tool_name)
        elif hasattr(fn_lookup, "get"):
            fn = fn_lookup.get(tool_name)

        builder = None
        if isinstance(desc_map, dict):
            builder = desc_map.get(tool_name)
        elif hasattr(desc_map, "get"):
            builder = desc_map.get(tool_name)
        elif callable(desc_map):
            try:
                builder = desc_map(tool_name)
            except Exception:
                builder = desc_map

        description = builder() if callable(builder) else ((getattr(fn, "__doc__", "") or "") if fn is not None else "")
        signature = str(inspect.signature(fn)) if callable(fn) else ""
        return {"name": tool_name, "description": str(description or ""), "signature": signature}
    except Exception:
        return {"name": tool_name}


def tool_catalog_schema_tokens(
    desc_map: Any,
    disabled_tools: set[str] | None = None,
    fn_lookup: Any = None,
) -> int:
    """Estimate enabled MCP schema exposure once per process.

    Hosts differ in how often the catalog is re-injected, so this value is kept as
    a separate conservative/upper-bound adjustment rather than folded into the
    default protocol cost.
    """
    try:
        disabled = set(disabled_tools or [])
        map_obj = desc_map if isinstance(desc_map, (dict, list, set, tuple)) else {}
        names = [name for name in map_obj if name not in disabled]
        return json_tokens({"tools": [schema_descriptor(name, fn_lookup=fn_lookup, desc_map=desc_map) for name in names]})
    except Exception:
        return 0


def normalize_accounting_root(raw_root: Any) -> str:
    """Validate and return absolute root path string if valid, else empty string."""
    if isinstance(raw_root, str) and (os.path.isabs(raw_root) or ntpath.isabs(raw_root)):
        return raw_root
    return ""


def current_accounting_time() -> float:
    """Return current timestamp for accounting events."""
    return time.time()


class _ProtocolAccountingReporter:
    """Non-blocking MCP-boundary telemetry reporter.

    Tool accounting must never add foreground latency, so calls enqueue a tiny
    metadata-only event. A lazy daemon batches events to the hub. If the hub is
    unavailable, accounting is dropped rather than delaying the agent.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[dict[str, Any], Any]] = queue.Queue(maxsize=2048)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="local-ai-token-accounting", daemon=True)
            self._thread.start()

    def record(self, event: dict[str, Any]) -> None:
        from . import mcp_server as services_module
        try:
            # A queued report must keep the client that owned it at enqueue time;
            # CLIENT can be replaced during controlled reconfiguration or tests.
            self._queue.put_nowait((dict(event), services_module.CLIENT))
        except services_module.queue.Full:
            return
        self._ensure_worker()

    def _send(self, events: list[dict[str, Any]], *, client: Any = None) -> None:
        from . import mcp_server as services_module
        if not events:
            return
        try:
            mode_state_dir = services_module.configured_state_dir(services_module.CFG, create=False)
            mode_snapshot = services_module.load_operational_mode(mode_state_dir)
            if mode_snapshot.mode != "active":
                return
        except Exception:
            pass
        operational_context = services_module._CURRENT_OPERATIONAL_CONTEXT
        operational_token = operational_context.set(("telemetry", False))
        try:
            # batch_id prevents HubClient single-flight from coalescing two
            # numerically identical accounting batches from concurrent MCP clients.
            (services_module.CLIENT if client is None else client).post(
                "/api/telemetry/tool-accounting",
                {"batch_id": f"{services_module.os.getpid()}-{services_module.time.time_ns()}", "events": list(events)},
                timeout=0.25,
            )
        except Exception:
            # Observability is best effort and must never become a retry/backpressure
            # path for the MCP foreground request.
            return
        finally:
            operational_context.reset(operational_token)

    def _send_batch(self, batch: list[tuple[dict[str, Any], Any]]) -> None:
        client_batches: dict[int, tuple[Any, list[dict[str, Any]]]] = {}
        for event, client in batch:
            client_batches.setdefault(id(client), (client, []))[1].append(event)
        for client, events in client_batches.values():
            self._send(events, client=client)

    def _run(self) -> None:
        from . import mcp_server as services_module
        batch: list[tuple[dict[str, Any], Any]] = []
        idle_since = services_module.time.monotonic()
        while not self._stop.is_set():
            try:
                batch.append(self._queue.get(timeout=0.35))
                idle_since = services_module.time.monotonic()
            except services_module.queue.Empty:
                pass
            while len(batch) < 32:
                try:
                    batch.append(self._queue.get_nowait())
                except services_module.queue.Empty:
                    break
            if batch:
                self._send_batch(batch)
                batch.clear()
            if services_module.time.monotonic() - idle_since > 15.0:
                # Retire atomically with submit/start. A record that races with
                # retirement either makes the queue non-empty here or observes
                # _thread=None in _ensure_worker and starts a replacement.
                with self._lock:
                    if self._queue.empty() and self._thread is services_module.threading.current_thread():
                        self._thread = None
                        return
        if batch:
            self._send_batch(batch)
        with self._lock:
            if self._thread is services_module.threading.current_thread():
                self._thread = None

    def close(self) -> None:
        from . import mcp_server as services_module
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not services_module.threading.current_thread():
            thread.join(timeout=0.35)
        remaining: list[tuple[dict[str, Any], Any]] = []
        while len(remaining) < 64:
            try:
                remaining.append(self._queue.get_nowait())
            except services_module.queue.Empty:
                break
        if remaining:
            self._send_batch(remaining)
        client = getattr(self, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
