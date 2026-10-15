"""Deferred tests for the owned Biome transport; intentionally not executed here."""
from __future__ import annotations

import io
import os
import sys
import types
import ctypes
import json
import queue

import pytest

from local_ai_hub import biome_owned_ipc as biome


def test_pipe_peer_must_be_the_retained_child_before_stream_use():
    with pytest.raises(biome.BiomeOwnershipError, match="different process"):
        biome._assert_peer_pid(actual_pid=901, expected_pid=900)


def test_only_explicit_supported_biome_version_is_accepted():
    assert biome._VERSION.fullmatch("biome 2.5.15")
    assert not biome._VERSION.fullmatch("biome 2.3.8")
    assert not biome._VERSION.fullmatch("biome 3.0.0")
    assert not biome._VERSION.fullmatch("Biome version unknown")


def test_non_windows_owned_transport_is_typed_unsupported(tmp_path, monkeypatch):
    from local_ai_hub.lint_daemon import OwnedBiomeDaemonPool

    monkeypatch.setattr(biome.OwnedBiomeDaemon, "supported_here", staticmethod(lambda: False))
    pool = OwnedBiomeDaemonPool()
    result = pool.run(sys.executable, str(tmp_path), "tenant-a", ["src/app.ts"])
    assert result["unsupported"] is True
    assert result["transport"] == "unsupported_unowned_platform"
    assert result["terminal"] is True and result["retryable"] is False


def test_lsp_framing_is_bounded_and_roundtrips_complete_json_object():
    wire = biome._frame({"jsonrpc": "2.0", "id": 1, "result": {"ready": True}})
    assert biome._read(io.BytesIO(wire)) == {"jsonrpc": "2.0", "id": 1, "result": {"ready": True}}
    with pytest.raises(ValueError, match="frame limit"):
        biome._frame({"payload": "x" * biome._MAX_FRAME})


def test_server_launch_uses_only_owned_foreground_entrypoint(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 77
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        def __init__(self):
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def wait(self, timeout=None):
            self.alive = False
            return 0

    monkeypatch.setattr(biome, "popen_managed", lambda argv, **kwargs: calls.append(list(argv)) or FakeProcess())
    monkeypatch.setattr(biome, "terminate_tree", lambda pid, **kwargs: True)
    daemon = biome.OwnedBiomeDaemon("biome")
    monkeypatch.setattr(daemon, "supported_here", lambda: True)
    monkeypatch.setattr(daemon, "_capture_version", lambda deadline: "2.5.15")
    proc, version = daemon._ensure_server(10**12)
    assert proc.pid == 77
    assert version == "2.5.15"
    assert calls == [["biome", "__run_server"]]
    assert all("proxy" not in item and "start" not in item for item in calls[0])
    daemon.close()


def test_unknown_binary_version_never_starts_foreground_server(monkeypatch):
    calls = []

    class FakeVersionProcess:
        pid = 79
        stdout = io.BytesIO(b"biome 2.5.16\n")
        stderr = io.BytesIO()
        returncode = 0

        @staticmethod
        def poll():
            return 0

    def launch(argv, **kwargs):
        calls.append(list(argv))
        return FakeVersionProcess()

    monkeypatch.setattr(biome, "popen_managed", launch)
    daemon = biome.OwnedBiomeDaemon("biome")
    monkeypatch.setattr(daemon, "supported_here", lambda: True)
    with pytest.raises(biome.BiomeOwnershipError, match="unsupported Biome version"):
        daemon._ensure_server(10**12)
    assert calls == [["biome", "--version"]]


def test_unknown_peer_is_rejected_before_pipe_becomes_a_stream(monkeypatch):
    opened = []
    closed = []

    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    class FakeKernel:
        CreateFileW = FakeFunction(lambda *args: 11)
        GetNamedPipeServerProcessId = FakeFunction(lambda handle, pointer: setattr(pointer._obj, "value", 42) or 1)
        CloseHandle = FakeFunction(lambda handle: closed.append(handle) or 1)

    monkeypatch.setattr(biome.ctypes, "WinDLL", lambda *args, **kwargs: FakeKernel(), raising=False)
    monkeypatch.setattr(biome, "os", types.SimpleNamespace(name="nt", O_RDWR=os.O_RDWR, O_BINARY=getattr(os, "O_BINARY", 0)))
    monkeypatch.setattr(biome, "msvcrt_open_osfhandle", lambda handle: opened.append(handle))
    with pytest.raises(biome.BiomeOwnershipError):
        biome._windows_pipe(r"\\.\pipe\biome-service-2.5.15", expected_pid=41)
    assert opened == []
    assert closed == [11]


def test_verified_client_session_reuses_pipe_and_versions_documents(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 55

        def __init__(self):
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def wait(self, timeout=None):
            self.alive = False
            return 0

    class FakePipe:
        def __init__(self):
            self.incoming = queue.Queue()
            self.sent = []
            self.closed = False

        def write(self, data):
            body = data.split(b"\r\n\r\n", 1)[1]
            message = json.loads(body)
            self.sent.append(message)
            method = message.get("method")
            if method == "initialize":
                self.incoming.put({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
            elif method in {"textDocument/didOpen", "textDocument/didChange"}:
                text_doc = message["params"]["textDocument"]
                self.incoming.put({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                                   "params": {"uri": text_doc["uri"], "version": text_doc["version"], "diagnostics": []}})
            return len(data)

        def flush(self):
            pass

        def close(self):
            self.closed = True
            self.incoming.put(None)

    process = FakeProcess()
    daemon = biome.OwnedBiomeDaemon("biome")
    daemon._proc, daemon._version = process, "2.5.15"
    monkeypatch.setattr(daemon, "_ensure_server", lambda deadline: (process, "2.5.15"))
    pipes = []

    def connect(path, expected_pid):
        assert expected_pid == process.pid
        pipe = FakePipe()
        pipes.append(pipe)
        return pipe

    monkeypatch.setattr(biome, "_windows_pipe", connect)
    monkeypatch.setattr(biome, "_read", lambda pipe: pipe.incoming.get(timeout=2))
    monkeypatch.setattr(biome, "terminate_tree", lambda *args, **kwargs: True)
    path = tmp_path / "app.ts"
    path.write_text("const answer = 42;\n", encoding="utf-8")

    for _ in range(2):
        assert daemon.diagnostics("tenant-a", str(tmp_path), [str(path)], timeout=1, should_stop=lambda: False) == []

    assert len(pipes) == 1
    methods = [item.get("method") for item in pipes[0].sent]
    assert methods.count("initialize") == 1
    assert methods.count("textDocument/didOpen") == 1
    assert methods.count("textDocument/didChange") == 1
    versions = [item["params"]["textDocument"]["version"] for item in pipes[0].sent
                if item.get("method") in {"textDocument/didOpen", "textDocument/didChange"}]
    assert versions == [1, 2]
    daemon.close()

