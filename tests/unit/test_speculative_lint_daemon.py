"""Deferred protocol regressions; this slice starts no Ruff or child process."""
import io
import json

import pytest

from local_ai_hub.lint_daemon import read_lsp_message
from local_ai_hub import lint_daemon
from local_ai_hub.services import LocalAIServices
from local_ai_hub.speculative_lint import SpeculativeLintQueue


def _frame(message):
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def test_persistent_pipe_reads_multiple_unicode_frames_without_line_assumptions():
    first = {"jsonrpc": "2.0", "id": 1, "result": {"message": "žluťoučký 🚀"}}
    second = {"jsonrpc": "2.0", "id": 2, "result": {"items": []}}
    stream = io.BytesIO(_frame(first) + _frame(second))
    assert read_lsp_message(stream) == first
    assert read_lsp_message(stream) == second
    assert read_lsp_message(stream) is None


@pytest.mark.parametrize("raw", [
    b"Content-Length: 4000001\r\n\r\n",
    b"Content-Length: -1\r\n\r\n",
    b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
    b"Content-Length: 10\r\n\r\n{}",
    b"X" * 2049 + b"\r\n\r\n",
])
def test_invalid_or_oversized_frames_fail_without_unbounded_capture(raw):
    with pytest.raises((ValueError, EOFError)):
        read_lsp_message(io.BytesIO(raw))


def test_partial_pipe_reads_reconstruct_exact_frame():
    class Partial(io.BytesIO):
        def read(self, count=-1):
            return super().read(min(count, 3))
    message = {"id": 9, "result": {"kind": "full", "items": []}}
    assert read_lsp_message(Partial(_frame(message))) == message


def _fake_daemon(monkeypatch):
    created = []

    class FakeDaemon:
        def __init__(self, executable, root):
            self.calls, self.closed = [], False
            self.confirmed = True
            self.failure = None
            created.append(self)

        def diagnostics(self, paths, **kwargs):
            self.calls.append(paths)
            if self.failure:
                raise self.failure
            return []

        def close(self):
            self.closed = True

        def cleanup_confirmed(self, timeout=0):
            return self.confirmed

    monkeypatch.setattr(lint_daemon, "RuffLintDaemon", FakeDaemon)
    return created


def test_pool_reuses_session_but_separates_tenants_and_roots(tmp_path, monkeypatch):
    created = _fake_daemon(monkeypatch)
    other = tmp_path / "other"
    other.mkdir()
    pool = lint_daemon.RuffDaemonPool(max_sessions=3)
    for root, tenant in [(tmp_path, "a"), (tmp_path, "a"), (tmp_path, "b"), (other, "a")]:
        assert pool.run("ruff", str(root), tenant, ["x.py"])["success"]
    assert len(created) == 3
    assert len(created[0].calls) == 2
    pool.close()
    assert all(daemon.closed for daemon in created)
    assert not pool.run("ruff", str(tmp_path), "a", ["x.py"])["success"]


def test_unconfirmed_retirement_keeps_capacity_reserved(tmp_path, monkeypatch):
    created = _fake_daemon(monkeypatch)
    pool = lint_daemon.RuffDaemonPool(max_sessions=1, idle_ttl=1)
    assert pool.run("ruff", str(tmp_path), "a", ["x.py"])["success"]
    created[0].confirmed = False
    next(iter(pool._sessions.values()))["last_used"] = float("-inf")
    assert not pool.run("ruff", str(tmp_path), "b", ["x.py"])["success"]
    assert created[0].closed
    assert len(created) == 1
    created[0].confirmed = True
    assert pool.run("ruff", str(tmp_path), "b", ["x.py"])["success"]
    assert len(created) == 2


def test_pool_preserves_unknown_cleanup_without_fallback(tmp_path, monkeypatch):
    created = _fake_daemon(monkeypatch)
    pool = lint_daemon.RuffDaemonPool()
    pool.run("ruff", str(tmp_path), "a", ["x.py"])
    created[0].failure = TimeoutError("deadline")
    created[0].confirmed = False
    result = pool.run("ruff", str(tmp_path), "a", ["x.py"])
    assert result["outcome_unknown"] and result["cleanup_unconfirmed"]
    assert result["terminal"] and not result["retryable"]
    assert len(created) == 1


def test_admission_timeout_does_not_close_another_requests_session(tmp_path, monkeypatch):
    created = _fake_daemon(monkeypatch)
    pool = lint_daemon.RuffDaemonPool()
    pool.run("ruff", str(tmp_path), "a", ["x.py"])
    created[0].failure = lint_daemon.LintDaemonAdmissionTimeout("busy")
    result = pool.run("ruff", str(tmp_path), "a", ["x.py"])
    assert not result["success"] and not result.get("outcome_unknown")
    assert not created[0].closed


def test_debounce_only_cancels_same_tenant_and_project(tmp_path):
    class Jobs:
        def __init__(self):
            self.cancelled, self.number = [], 0

        def cancel(self, tenant, job_id):
            self.cancelled.append((tenant, job_id))

        def submit(self, tenant, action, payload, **kwargs):
            self.number += 1
            return {"success": True, "job_id": str(self.number)}

    jobs = Jobs()
    queue = SpeculativeLintQueue(jobs, {"speculative_lint": {"enabled": True}})
    queue.submit("a", str(tmp_path), ["x.py"])
    queue.submit("b", str(tmp_path), ["x.py"])
    queue.submit("a", str(tmp_path), ["x.py"])
    assert jobs.cancelled == [("a", "1")]


class _LintCommands:
    def __init__(self):
        self.calls = []

    def classify(self, command):
        return {"allowed": True, "class": "read_only"}

    def run(self, command, root, **kwargs):
        self.calls.append((command, root, kwargs))
        return {"success": True, "exit_code": 0}


def _lint_service(monkeypatch, tmp_path, *, daemon_mode):
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"speculative_lint": {"daemon_mode": daemon_mode}}
    service.commands = _LintCommands()

    class NoDaemon:
        def run(self, *args, **kwargs):
            raise AssertionError("Biome must not enter the Ruff daemon pool")

    service._lint_daemons = NoDaemon()
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda name: {"ruff": None, "biome": "biome.exe", "eslint": "eslint.exe"}.get(name))
    return service


def test_biome_daemon_mode_uses_owned_provider_contract(tmp_path, monkeypatch):
    service = _lint_service(monkeypatch, tmp_path, daemon_mode=True)
    calls = []

    class FakeOwnedBiomePool:
        def run(self, executable, root, tenant, paths, **kwargs):
            calls.append((executable, root, tenant, paths, kwargs))
            return {"success": True, "provider": "biome", "daemon_mode": True,
                    "transport": "owned_foreground_lsp", "read_only": True, "auto_fix": False,
                    "diagnostics": [], "diagnostic_count": 0}

    service._biome_daemons = FakeOwnedBiomePool()

    result = service.speculative_lint({"root": str(tmp_path), "paths": ["src/app.ts"]}, "tenant-a")

    assert result["success"]
    assert result["provider"] == "biome"
    assert result["daemon_mode"] is True
    assert result["transport"] == "owned_foreground_lsp"
    assert result["read_only"] and not result["auto_fix"]
    assert not service.commands.calls
    assert len(calls) == 1
    executable, root, tenant, paths, kwargs = calls[0]
    assert (executable, root, tenant, paths) == ("biome.exe", str(tmp_path), "tenant-a", ["src/app.ts"])
    assert kwargs["timeout"] == 120.0 and callable(kwargs["should_stop"])


def test_biome_non_daemon_mode_uses_explicit_read_only_one_shot_ci(tmp_path, monkeypatch):
    service = _lint_service(monkeypatch, tmp_path, daemon_mode=False)

    result = service.speculative_lint({"root": str(tmp_path), "paths": ["src/app.ts"]}, "tenant-a")

    assert result["success"]
    assert result["provider"] == "biome"
    assert result["daemon_mode"] is False and result["transport"] == "one_shot"
    assert service.commands.calls[0][0] == "biome.exe ci src/app.ts"
    assert service.commands.calls[0][2]["auto_fix"] is False
