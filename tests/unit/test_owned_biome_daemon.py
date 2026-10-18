"""Deferred tests for the owned Biome transport; intentionally not executed here."""
from __future__ import annotations

import io
import os
import sys
import types
import ctypes
import json
import queue
import threading
import time

import pytest

from local_ai_hub import biome_owned_ipc as biome


def test_pipe_peer_must_be_the_retained_child_before_stream_use():
    with pytest.raises(biome.BiomeOwnershipError, match="different process"):
        biome._assert_peer_pid(actual_pid=901, expected_pid=900)


def test_only_explicit_supported_biome_version_is_accepted():
    assert biome._VERSION.fullmatch("Version: 2.5.15")
    assert not biome._VERSION.fullmatch("Version: 2.3.8")
    assert not biome._VERSION.fullmatch("Version: 3.0.0")
    assert not biome._VERSION.fullmatch("biome 2.5.15")
    assert not biome._VERSION.fullmatch("Biome version unknown")


def test_version_capture_accepts_canonical_bpaf_output_and_releases_streams(monkeypatch):
    released = []

    class Process:
        pid = 78
        stdout = io.BytesIO(b"Version: 2.5.15\n")
        stderr = io.BytesIO()
        returncode = 0

        @staticmethod
        def poll():
            return 0

    process = Process()
    monkeypatch.setattr(biome, "popen_managed", lambda *args, **kwargs: process)
    monkeypatch.setattr(biome, "_release_process_job", lambda proc: released.append(proc) or True)
    daemon = biome.OwnedBiomeDaemon("biome")

    assert daemon._capture_version(time.monotonic() + 1) == "2.5.15"
    assert daemon._version_proc is None
    assert process.stdout.closed and process.stderr.closed
    assert released


def test_non_windows_owned_transport_is_typed_unsupported(tmp_path, monkeypatch):
    from local_ai_hub.lint_daemon import OwnedBiomeDaemonPool

    monkeypatch.setattr(biome.OwnedBiomeDaemon, "supported_here", staticmethod(lambda: False))
    pool = OwnedBiomeDaemonPool()
    result = pool.run(sys.executable, str(tmp_path), paths=["src/app.ts"])
    assert result["unsupported"] is True
    assert result["transport"] == "unsupported_unowned_platform"
    assert result["terminal"] is True and result["retryable"] is False


def test_lsp_framing_is_bounded_and_roundtrips_complete_json_object():
    wire = biome._frame({"jsonrpc": "2.0", "id": 1, "result": {"ready": True}})
    assert biome._read(io.BytesIO(wire)) == {"jsonrpc": "2.0", "id": 1, "result": {"ready": True}}
    with pytest.raises(ValueError, match="frame limit"):
        biome._frame({"payload": "x" * biome._MAX_FRAME})
    oversized_notification = biome._frame({"params": "x" * (biome._MAX_INBOUND_FRAME + 32)})
    with pytest.raises(ValueError, match="frame limit"):
        biome._read(io.BytesIO(oversized_notification), max_frame=biome._MAX_INBOUND_FRAME)
    assert biome._MAX_FRAME > biome._MAX_INBOUND_FRAME
    assert biome._INBOUND_SESSION_QUEUE_BUDGET == 2_048_000


def test_diagnostic_flood_and_malformed_envelopes_fail_instead_of_truncating():
    with pytest.raises(ValueError, match="response budget"):
        biome._normalize_diagnostics([{"message": "x"}] * 513, "app.ts")
    with pytest.raises(ValueError, match="severity"):
        biome._normalize_diagnostics([{"message": "x", "severity": True}], "app.ts")
    with pytest.raises(ValueError, match="range"):
        biome._normalize_diagnostics([{"message": "x", "range": {"start": {"line": True}}}], "app.ts")


def test_source_snapshot_rejects_path_retargeted_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    inside_file = root / "app.ts"
    outside_file = outside / "app.ts"
    inside_file.write_text("const inside = true;\n", encoding="utf-8")
    outside_file.write_text("const outside = true;\n", encoding="utf-8")
    candidate = root / "app.ts"
    original_resolve = biome.Path.resolve
    calls = 0

    def changing_resolve(path, *args, **kwargs):
        nonlocal calls
        if path == candidate:
            calls += 1
            return inside_file if calls == 1 else outside_file
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(biome.Path, "resolve", changing_resolve)
    with pytest.raises(ValueError):
        biome._read_source_snapshot(candidate, root.resolve())


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
    released = []

    class FakeVersionProcess:
        pid = 79
        stdout = io.BytesIO(b"Version: 2.5.16\n")
        stderr = io.BytesIO()
        returncode = 0

        @staticmethod
        def poll():
            return 0

    def launch(argv, **kwargs):
        calls.append(list(argv))
        return FakeVersionProcess()

    monkeypatch.setattr(biome, "popen_managed", launch)
    monkeypatch.setattr(biome, "_release_process_job", lambda proc: released.append(proc) or True)
    daemon = biome.OwnedBiomeDaemon("biome")
    monkeypatch.setattr(daemon, "supported_here", lambda: True)
    with pytest.raises(biome.BiomeOwnershipError, match="unsupported Biome version"):
        daemon._ensure_server(10**12)
    assert calls == [["biome", "--version"]]
    assert released and released[0].stdout.closed and released[0].stderr.closed


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
        WaitNamedPipeW = FakeFunction(lambda *args: 1)
        GetNamedPipeServerProcessId = FakeFunction(lambda handle, pointer: setattr(pointer._obj, "value", 42) or 1)
        CloseHandle = FakeFunction(lambda handle: closed.append(handle) or 1)

    monkeypatch.setattr(biome.ctypes, "WinDLL", lambda *args, **kwargs: FakeKernel(), raising=False)
    monkeypatch.setattr(biome, "os", types.SimpleNamespace(name="nt", O_RDWR=os.O_RDWR, O_BINARY=getattr(os, "O_BINARY", 0)))
    monkeypatch.setattr(biome, "msvcrt_open_osfhandle", lambda handle: opened.append(handle))
    with pytest.raises(biome.BiomeOwnershipError):
        biome._windows_pipe(r"\\.\pipe\biome-service-2.5.15", expected_pid=41, deadline=time.monotonic() + 1)
    assert opened == []
    assert closed == [11]


def test_blocked_fake_pipe_write_times_out_and_cleanup_closes_only_owned_stream(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 56

        def __init__(self):
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def wait(self, timeout=None):
            self.alive = False
            return 0

    class BlockingPipe:
        def __init__(self):
            self.release = threading.Event()
            self.incoming = queue.Queue()
            self.closed = False

        def write(self, data):
            self.release.wait()
            return len(data)

        def flush(self):
            pass

        def close(self):
            self.closed = True
            self.release.set()
            self.incoming.put(None)

    process = FakeProcess()
    pipe = BlockingPipe()
    daemon = biome.OwnedBiomeDaemon("biome")
    daemon._proc, daemon._version = process, "2.5.15"
    monkeypatch.setattr(daemon, "_ensure_server", lambda deadline: (process, "2.5.15"))
    monkeypatch.setattr(biome, "_windows_pipe", lambda path, expected_pid, *, deadline: pipe)
    monkeypatch.setattr(biome, "_read", lambda stream, **kwargs: stream.incoming.get(timeout=2))
    monkeypatch.setattr(biome, "terminate_tree", lambda *args, **kwargs: True)
    source = tmp_path / "src" / "app.ts"
    source.parent.mkdir()
    source.write_text("const value = 1;\n", encoding="utf-8")
    stop = threading.Event()
    timer = threading.Timer(0.05, stop.set)
    timer.start()

    with pytest.raises(TimeoutError, match="write timed out or cancelled"):
        daemon.diagnostics(str(tmp_path), paths=["src/app.ts"],
                           deadline=time.monotonic() + 2, should_stop=stop.is_set)
    timer.join()
    assert pipe.closed
    assert daemon.close() is True


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
            self.buffer = bytearray()

        def write(self, data):
            count = min(13, len(data))
            self.buffer.extend(data[:count])
            while b"\r\n\r\n" in self.buffer:
                header, body = bytes(self.buffer).split(b"\r\n\r\n", 1)
                length = int(header.split(b":", 1)[1].strip())
                if len(body) < length:
                    break
                del self.buffer[:len(header) + 4 + length]
                message = json.loads(body[:length])
                self.sent.append(message)
                method = message.get("method")
                if method == "initialize":
                    self.incoming.put({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "ready"}})
                    self.incoming.put({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
                elif method in {"textDocument/didOpen", "textDocument/didChange"}:
                    text_doc = message["params"]["textDocument"]
                    self.incoming.put({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                                       "params": {"uri": text_doc["uri"], "version": text_doc["version"], "diagnostics": []}})
            return count

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

    def connect(path, expected_pid, *, deadline):
        assert deadline > time.monotonic()
        assert expected_pid == process.pid
        pipe = FakePipe()
        pipes.append(pipe)
        return pipe

    monkeypatch.setattr(biome, "_windows_pipe", connect)
    monkeypatch.setattr(biome, "_read", lambda pipe, **_kwargs: pipe.incoming.get(timeout=2))
    monkeypatch.setattr(biome, "terminate_tree", lambda *args, **kwargs: True)
    path = tmp_path / "app.ts"
    path.write_text("const answer = 42;\n", encoding="utf-8")

    call_deadlines = [time.monotonic() + 1, time.monotonic() + 2]
    for call_deadline in call_deadlines:
        assert daemon.diagnostics(str(tmp_path), paths=[str(path)], deadline=call_deadline,
                                  should_stop=lambda: False) == []
    session_key = os.path.normcase(str(tmp_path.resolve()))
    assert daemon._sessions[session_key]["deadline"] == call_deadlines[-1]

    assert len(pipes) == 1
    methods = [item.get("method") for item in pipes[0].sent]
    assert methods.count("initialize") == 1
    assert methods.count("textDocument/didOpen") == 1
    assert methods.count("textDocument/didChange") == 1
    versions = [item["params"]["textDocument"]["version"] for item in pipes[0].sent
                if item.get("method") in {"textDocument/didOpen", "textDocument/didChange"}]
    assert versions == [1, 2]

    sent_before_invalid = len(pipes[0].sent)
    path.write_bytes(b"const invalid = '\xff';\n")
    with pytest.raises(UnicodeDecodeError):
        daemon.diagnostics(str(tmp_path), paths=[str(path)], deadline=time.monotonic() + 1,
                           should_stop=lambda: False)
    assert len(pipes[0].sent) == sent_before_invalid

    path.write_bytes(b"x" * 2_000_001)
    with pytest.raises(ValueError, match="source budget"):
        daemon.diagnostics(str(tmp_path), paths=[str(path)], deadline=time.monotonic() + 1,
                           should_stop=lambda: False)
    methods_after_oversized_change = [item.get("method") for item in pipes[0].sent]
    assert methods_after_oversized_change.count("textDocument/didChange") == 1
    daemon.close()

