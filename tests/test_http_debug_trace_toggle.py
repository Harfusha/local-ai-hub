from __future__ import annotations

import threading
from types import SimpleNamespace

from local_ai_hub.http_server import _apply_live_debug_trace_toggle


def test_live_debug_trace_toggle_updates_cached_status_snapshot():
    stale_snapshot = {"success": True, "debug_traces": {"enabled": False, "count": 2}}
    app = SimpleNamespace(
        debug_traces=SimpleNamespace(enabled=False),
        _live_status_lock=threading.RLock(),
        _live_status_cache={"brief": (1.0, stale_snapshot)},
    )

    assert _apply_live_debug_trace_toggle(app, {"debug_traces.enabled": True}) is True

    assert app.debug_traces.enabled is True
    assert stale_snapshot["debug_traces"] == {"enabled": True, "count": 2}


def test_live_debug_trace_toggle_rejects_other_settings_and_missing_store():
    app = SimpleNamespace(debug_traces=SimpleNamespace(enabled=False))

    assert _apply_live_debug_trace_toggle(app, {"debug_traces.enabled": True, "other": 1}) is False
    assert _apply_live_debug_trace_toggle(SimpleNamespace(), {"debug_traces.enabled": True}) is False


def test_live_debug_trace_toggle_skips_malformed_cache_entries_without_lock():
    snapshot_without_trace_status = {"success": True}
    app = SimpleNamespace(
        debug_traces=SimpleNamespace(enabled=False),
        _live_status_lock=object(),
        _live_status_cache={
            "bad-entry": "cached",
            "bad-snapshot": (1.0, []),
            "bad-trace-status": (1.0, snapshot_without_trace_status),
        },
    )

    assert _apply_live_debug_trace_toggle(app, {"debug_traces.enabled": True}) is True
    assert app.debug_traces.enabled is True
    assert snapshot_without_trace_status == {"success": True}


def test_live_debug_trace_toggle_skips_non_mapping_cache():
    app = SimpleNamespace(
        debug_traces=SimpleNamespace(enabled=False),
        _live_status_cache=[],
    )

    assert _apply_live_debug_trace_toggle(app, {"debug_traces.enabled": True}) is True
    assert app.debug_traces.enabled is True

