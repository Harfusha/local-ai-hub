from __future__ import annotations

import json
import os
import socket
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest

_TEST_PORT_GUARD: socket.socket | None = None
_ORIGINAL_CONFIG_CAPTURED = False
_ORIGINAL_CONFIG_PRESENT = False
_ORIGINAL_CONFIG: str | None = None


def pytest_configure(config):
    """Isolate default config, mode state, and loopback port before collection."""
    global _TEST_PORT_GUARD
    global _ORIGINAL_CONFIG_CAPTURED, _ORIGINAL_CONFIG_PRESENT, _ORIGINAL_CONFIG
    if _ORIGINAL_CONFIG_CAPTURED:
        return
    _ORIGINAL_CONFIG_CAPTURED = True
    _ORIGINAL_CONFIG_PRESENT = "LOCAL_AI_CONFIG" in os.environ
    _ORIGINAL_CONFIG = os.environ.get("LOCAL_AI_CONFIG")
    root = Path(tempfile.mkdtemp(prefix="local-ai-hub-pytest-"))
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        guard.bind(("127.0.0.1", 0))
        port = guard.getsockname()[1]
        config_path = root / "config.toml"
        config_path.write_text(
            "[server]\n"
            'bind = "127.0.0.1"\n'
            f"port = {port}\n"
            "auto_start_ollama = false\n"
            "state_dir = " + json.dumps((root / "state").as_posix()) + "\n",
            encoding="utf-8",
        )
        _TEST_PORT_GUARD = guard
        os.environ["LOCAL_AI_CONFIG"] = str(config_path)
    except BaseException:
        guard.close()
        raise


def pytest_unconfigure(config):
    """Restore inherited environment; retain isolated config/state as artifacts."""
    global _TEST_PORT_GUARD, _ORIGINAL_CONFIG_CAPTURED
    if not _ORIGINAL_CONFIG_CAPTURED:
        return
    if _ORIGINAL_CONFIG_PRESENT:
        os.environ["LOCAL_AI_CONFIG"] = _ORIGINAL_CONFIG or ""
    else:
        os.environ.pop("LOCAL_AI_CONFIG", None)
    if _TEST_PORT_GUARD is not None:
        _TEST_PORT_GUARD.close()
        _TEST_PORT_GUARD = None
    _ORIGINAL_CONFIG_CAPTURED = False


@pytest.fixture(autouse=True)
def _test_owned_mutation_fence(request, monkeypatch):
    if request.module.__name__ not in {"test_command_rollback", "test_command_transaction_snapshot"}:
        return

    from local_ai_hub.commands import CommandBroker
    from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence

    original_init = CommandBroker.__init__

    def init_with_test_fence(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        install_test_work_attempt_fence(self, FakeFencingLeaseStore())

    monkeypatch.setattr(CommandBroker, "__init__", init_with_test_fence)
