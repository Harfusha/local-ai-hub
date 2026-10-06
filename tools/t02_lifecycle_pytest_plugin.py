"""Emit bounded AsyncJobManager lifecycle snapshots after each pytest case."""

from __future__ import annotations

import gc
import json
import sys
from typing import Any

from local_ai_hub.async_jobs import AsyncJobManager


def _open_manager_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manager in gc.get_objects():
        if not isinstance(manager, AsyncJobManager):
            continue
        shutdown = getattr(manager, "_shutdown", None)
        shutdown_state = shutdown.is_set() if hasattr(shutdown, "is_set") else None
        live_threads: list[dict[str, Any]] = []
        for role, attribute in (
            ("worker", "_workers"),
            ("dispatcher", "_dispatchers"),
            ("delayed_dispatch", "_delayed_dispatch"),
        ):
            handles = getattr(manager, attribute, ())
            try:
                handles = tuple(handles.values()) if isinstance(handles, dict) else tuple(handles)
            except RuntimeError:
                continue
            for thread in handles:
                if getattr(thread, "is_alive", lambda: False)():
                    live_threads.append({
                        "role": role,
                        "name": thread.name,
                        "daemon": thread.daemon,
                    })
        if live_threads or shutdown_state is not True:
            rows.append({
                "database": str(getattr(manager, "path", "")),
                "shutdown": shutdown_state,
                "live_threads": live_threads,
            })
    rows.sort(key=lambda row: (row["database"], str(row["shutdown"])))
    return rows


def pytest_runtest_logreport(report: Any) -> None:
    if report.when == "teardown":
        print("T02_LIFECYCLE " + json.dumps({
            "nodeid": report.nodeid,
            "outcome": report.outcome,
            "open_managers": _open_manager_rows(),
        }, sort_keys=True), file=sys.stderr)
