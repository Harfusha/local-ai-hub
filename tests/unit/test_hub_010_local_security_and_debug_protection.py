from __future__ import annotations

from pathlib import Path
import tomllib
import pytest

from local_ai_hub.debug_traces import DebugTraceStore, redact_trace_export
from local_ai_hub.http_server import Handler, _strict_root_path, validate_network_security
from local_ai_hub.work_orchestrator import _patch_paths


def test_default_bind_is_loopback_no_lan():
    """DoD: No LAN bind by default; server strictly binds to 127.0.0.1 and enforces network security."""
    defaults_path = Path("src/local_ai_hub/defaults.toml")
    with defaults_path.open("rb") as f:
        data = tomllib.load(f)

    bind_host = data.get("server", {}).get("bind")
    assert bind_host == "127.0.0.1"
    assert bind_host != "0.0.0.0"

    # validate_network_security passes on loopback
    validate_network_security(data)

    # Any remote exposure must be rejected with RuntimeError
    with pytest.raises(RuntimeError, match="Refusing Local AI Hub network exposure"):
        validate_network_security({"server": {"bind": "0.0.0.0"}})

    with pytest.raises(RuntimeError, match="Refusing remote Hub access"):
        validate_network_security({"server": {"bind": "127.0.0.1"}, "security": {"allow_remote": True}})


def test_origin_and_host_validation_rejects_cross_origin():
    """DoD: Origin and host validation blocks cross-origin dashboard requests."""
    handler = object.__new__(Handler)
    handler.headers = {
        "X-LocalAI-Client": "dashboard",
        "Sec-Fetch-Site": "cross-site",
    }
    sent_responses = []
    handler._send = lambda code, payload: sent_responses.append((code, payload))

    # Import APP check guard
    import local_ai_hub.http_server as hs
    old_app = hs.APP
    try:
        hs.APP = object()  # Simulate active server
        valid = handler._validate_host_and_origin()
        assert valid is False
        assert len(sent_responses) == 1
        assert sent_responses[0][0] == 403
        assert "forbidden" in sent_responses[0][1]["error"]
    finally:
        hs.APP = old_app


def test_path_traversal_and_escape_rejected(tmp_path: Path):
    """DoD: Path traversal escapes outside project root and TOCTOU swaps are rejected."""
    # 1. Traversal in patch paths rejected
    with pytest.raises(ValueError):
        _patch_paths("--- a/../secret\n+++ b/../secret\n@@ -1 +1 @@\n-x\n+y\n")

    with pytest.raises(ValueError):
        _patch_paths("--- a/x\n+++ C:/temp/x\n@@ -1 +1 @@\n-x\n+y\n")

    # 2. Strict root path rejects relative paths and non-existent directories
    with pytest.raises(ValueError):
        _strict_root_path("../../relative/path")

    # 3. TOCTOU target swap is rejected
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside"
    candidate.mkdir()
    outside.mkdir()
    original_resolve = Path.resolve

    def swapped_resolve(path, *args, **kwargs):
        if path == candidate:
            return outside
        return original_resolve(path, *args, **kwargs)

    import unittest.mock
    with unittest.mock.patch.object(Path, "resolve", swapped_resolve):
        with pytest.raises(ValueError, match="changed during validation"):
            _strict_root_path(str(candidate))


def test_debug_traces_purge_clears_records(tmp_path: Path):
    """DoD: Debug trace purge removes all traces atomically."""
    config = {
        "server": {"state_dir": str(tmp_path)},
        "debug_traces": {"enabled": True, "max_bytes": 10 * 1024 * 1024},
    }
    store = DebugTraceStore(config)
    trace_id = "tr_1234567890abcdef"
    tid = store.start(
        kind="test_eval",
        action="solve",
        source="test",
        request_id="req_12345",
        trace_id=trace_id,
    )
    assert tid == trace_id
    store.event(trace_id, "start_step", {"step": 1})
    store.finish(trace_id, state="done", response={"result": "ok"})

    assert store.stats()["counts"].get("done") == 1
    assert store.stats()["events"] >= 1

    purge_result = store.purge()
    assert purge_result["success"] is True
    assert store.stats()["counts"] == {}
    assert store.stats()["events"] == 0


def test_debug_traces_redacted_export_masks_secrets_and_paths():
    """DoD: Export redacts sensitive headers, bearer tokens, passwords, and paths."""
    raw_trace = {
        "authorization": "Bearer sk-proj-1234567890abcdef1234567890",
        "api_key": "secret_key_value_999",
        "password": "super_secret_password",
        "path": "C:\\Users\\Adam\\PrivateDocuments\\secret.py",
        "repo_root": "/home/user/super_secret_repo",
        "nested": {
            "token": "tok_xyz123456",
            "safe_field": "public_data",
        },
    }
    redacted = redact_trace_export(raw_trace)

    assert redacted["authorization"] == "Bearer [redacted]"
    assert redacted["api_key"] == "[redacted]"
    assert redacted["password"] == "[redacted]"
    assert redacted["path"] == "[path]"
    assert redacted["repo_root"] == "[path]"
    assert redacted["nested"]["token"] == "[redacted]"
    assert redacted["nested"]["safe_field"] == "public_data"
