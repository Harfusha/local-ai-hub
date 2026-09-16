from __future__ import annotations

import os
import socket
import sys
import pytest

from local_ai_hub.process_utils import find_listening_pid


def test_find_listening_pid_invalid_port():
    assert find_listening_pid(0) is None
    assert find_listening_pid(-1) is None


def test_find_listening_pid_ipv4():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert find_listening_pid(port) == os.getpid()
    finally:
        sock.close()

    # Once closed, should no longer find this PID
    # (or port is unused, so None)
    assert find_listening_pid(port) is None or find_listening_pid(port) != os.getpid()


def test_find_listening_pid_ipv6():
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("IPv6 not supported on this host")
    try:
        sock.bind(("::1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert find_listening_pid(port) == os.getpid()
    finally:
        sock.close()


def test_find_listening_pid_windows_no_subprocess(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows only test")

    import subprocess

    def forbidden_run(*args, **kwargs):
        raise AssertionError(f"subprocess.run must not be called: {args} {kwargs}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        monkeypatch.setattr(subprocess, "run", forbidden_run)
        assert find_listening_pid(port) == os.getpid()
    finally:
        sock.close()
