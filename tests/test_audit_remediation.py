"""Audit remediation regressions. Real functions; temporary state, no network.
Assertions describe the repaired contracts.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import tomllib
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from local_ai_hub.agent_policy import PolicyEngine, BudgetCost
import local_ai_hub.config as config_module
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.external_tools import ExternalCodeIntelligence
from local_ai_hub.deterministic import DeterministicEngine

@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    config = tmp_path / "isolated.toml"
    config.write_text('[server]\nstate_dir = ' + json.dumps(str(tmp_path / "state")) + '\n', encoding="utf-8")
    monkeypatch.setenv("LOCAL_AI_CONFIG", str(config))

def test_budget_consumption_retains_both_concurrent_increments(monkeypatch):
    engine = PolicyEngine()
    persist = engine._persist_budget
    def slow_persist(budget):
        time.sleep(0.005)
        return persist(budget)
    monkeypatch.setattr(engine, "_persist_budget", slow_persist)
    start = threading.Barrier(4)
    def consume():
        start.wait(timeout=3)
        for _ in range(5):
            engine.consume("audit-budget", BudgetCost(external_calls=1))
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(consume) for _ in range(4)]
        for future in futures:
            future.result(timeout=5)
    assert engine.get_budget("audit-budget").used_external_calls == 20


def test_runtime_updates_preserve_both_changes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    target = config_module.runtime_override_path(config_path)
    target.write_text("", encoding="utf-8")
    replace = os.replace
    start = threading.Barrier(2)
    def slow_replace(source, destination):
        time.sleep(0.01)
        return replace(source, destination)
    monkeypatch.setattr(config_module.os, "replace", slow_replace)
    def update(patch):
        start.wait(timeout=3)
        config_module.save_runtime_overrides(config_path, patch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update, patch) for patch in ({"first": True}, {"second": True})]
        for future in futures:
            future.result(timeout=5)
    assert tomllib.loads(target.read_text(encoding="utf-8")) == {"first": True, "second": True}


def test_reference_fallback_returns_references_not_definitions():
    class Index:
        def find_symbol(self, *args, **kwargs):
            return {"success": True, "symbols": [{"name": "target", "path": "defs.py", "line": 10}]}
        def find_referencing_symbols(self, *args, **kwargs):
            return {"success": True, "references": [{"symbol": "target", "path": "calls.py", "line": 20}]}
    service = object.__new__(ExternalCodeIntelligence)
    service.code_index = Index()
    actual = service._fallback_code_index(str(REPO), "references", "target", "defs.py")
    assert actual["references"] == [{"symbol": "target", "path": "calls.py", "line": 20}], actual

class _Artifacts:
    def put(self, content, *, kind):
        return "audit-result"
    def get(self, artifact_id, *, offset=0, max_chars=256):
        return {"success": True, "text": "{}"}

class _Scheduler:
    config = {"models": {"heavy_code": "audit-no-model"}}

def manager_for(tmp_path, executor):
    return AsyncJobManager({"server": {"state_dir": str(tmp_path / "state")}}, _Scheduler(), _Artifacts(), executor)

def test_old_async_attempt_cannot_overwrite_new_result(tmp_path, monkeypatch):
    started = threading.Event()
    release_old = threading.Event()
    new_finished = threading.Event()
    lock = threading.Lock()
    calls = 0
    def execute(action, payload):
        nonlocal calls
        with lock:
            calls += 1
            invocation = calls
        if invocation == 1:
            started.set()
            assert release_old.wait(5), "bounded test release missing"
            return {"success": True, "value": "old"}
        new_finished.set()
        return {"success": True, "value": "new"}
    manager = manager_for(tmp_path, execute)
    anchor = None
    try:
        memory_uri = f"file:async-race-{uuid.uuid4().hex}?mode=memory&cache=shared"

        def connect_shared_memory():
            con = sqlite3.connect(
                memory_uri, uri=True, timeout=0.75, isolation_level="DEFERRED"
            )
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=750")
            con.execute("PRAGMA synchronous=NORMAL")
            return con

        anchor = connect_shared_memory()
        with closing(sqlite3.connect(str(manager.path), timeout=0.75)) as initialized_disk_db:
            initialized_disk_db.backup(anchor)
        monkeypatch.setattr(manager, "_connect", connect_shared_memory)

        submission = manager.submit("reason", {"task": "audit", "request_id": "audit-isolated-stale"})
        assert submission["success"] is True, submission
        job_id = submission["job_id"]
        assert started.wait(3), "first attempt did not start"
        with manager._lock, closing(manager._connect()) as con:
            con.execute("UPDATE async_jobs SET lease_until=? WHERE job_id=?", (time.time() - 1, job_id))
            con.commit()
        manager.tick()
        assert new_finished.wait(3), "replacement attempt did not start"
        assert manager._event(job_id).wait(3), "replacement attempt did not finalize"
        before = manager.result(job_id)
        assert before.get("result", {}).get("value") == "new", before
        with manager._lock:
            workers = list(manager._workers)
        release_old.set()
        for worker in workers:
            worker.join(timeout=3)
            assert not worker.is_alive(), "bounded worker cleanup failed"
        after = manager.result(job_id)
        assert after.get("result", {}).get("value") == "new", {"before": before, "after": after}
    finally:
        release_old.set()
        with manager._lock:
            owned_threads = list(manager._dispatchers | manager._workers | set(manager._resource_release_workers.values()))
        try:
            manager.close()
        finally:
            try:
                for worker in owned_threads:
                    worker.join(timeout=5)
                    assert not worker.is_alive(), "bounded stale-attempt worker cleanup failed"
            finally:
                if anchor is not None:
                    anchor.close()


def test_default_manager_persists_running_claim_and_terminal_result_on_disk(tmp_path, monkeypatch):
    observed_running_rows = []
    manager = None
    try:
        def execute(_action, _payload):
            with closing(sqlite3.connect(str(manager.path), timeout=0.75)) as observer:
                row = observer.execute(
                    "SELECT state,attempts,lease_until FROM async_jobs WHERE job_id=?",
                    (job_id,),
                ).fetchone()
            assert row is not None, "executor must observe its committed job claim"
            assert row[0] == "running", row
            assert row[1] == 1, row
            assert row[2] > time.time(), row
            observed_running_rows.append(tuple(row))
            return {"success": True, "value": "durable-result"}

        manager = manager_for(tmp_path, execute)
        monkeypatch.setattr(manager, "_dispatch", lambda *_args, **_kwargs: None)
        submission = manager.submit("reason", {"task": "durable claim acceptance"})
        assert submission["success"] is True, submission
        job_id = submission["job_id"]

        manager._execute(job_id)

        assert len(observed_running_rows) == 1
        with closing(sqlite3.connect(str(manager.path), timeout=0.75)) as independent_reader:
            row = independent_reader.execute(
                "SELECT state,attempts,result_json FROM async_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == "done", row
        assert row[1] == 1, row
        assert json.loads(row[2])["value"] == "durable-result", row
    finally:
        if manager is not None:
            manager.close()

def test_async_success_requires_boolean_true(tmp_path):
    manager = manager_for(tmp_path, lambda action, payload: {"success": "false", "text": "invalid envelope"})
    try:
        job = manager.submit("reason", {"task": "audit malformed success"})
        status = manager.wait(job["job_id"], 3)
        assert status["state"] != "done", status
    finally:
        manager.close()


def test_old_async_attempt_does_not_clean_new_attempt_processes(tmp_path):
    class Process:
        stopped = False
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    old_process, new_process = Process(), Process()
    old_started, new_started = threading.Event(), threading.Event()
    release_old, release_new = threading.Event(), threading.Event()
    guard = threading.Lock()
    calls = 0
    def execute(action, payload):
        nonlocal calls
        with guard:
            calls += 1
            attempt = calls
        manager.register_process(payload["job_id"], old_process if attempt == 1 else new_process)
        (old_started if attempt == 1 else new_started).set()
        assert (release_old if attempt == 1 else release_new).wait(5)
        return {"success": True}
    manager = manager_for(tmp_path, execute)
    try:
        # Dispatch is controlled until the submitted ID is available to the executor.
        dispatch = manager._dispatch_background
        manager._dispatch_background = lambda job_id: None
        job = manager.submit("reason", {"task": "attempt process ownership", "request_id": "process-scope"})
        job_id = job["job_id"]
        with manager._lock, closing(manager._connect()) as con:
            row = con.execute("SELECT payload_json FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
            payload = json.loads(row[0]); payload["job_id"] = job_id
            con.execute("UPDATE async_jobs SET payload_json=? WHERE job_id=?", (json.dumps(payload), job_id))
            con.commit()
        manager._dispatch_background = dispatch
        dispatch(job_id)
        assert old_started.wait(3)
        with manager._lock, closing(manager._connect()) as con:
            con.execute("UPDATE async_jobs SET lease_until=? WHERE job_id=?", (time.time() - 1, job_id))
            con.commit()
        manager.tick()
        assert new_started.wait(3)
        release_old.set()
        deadline = time.monotonic() + 3
        while not old_process.stopped and time.monotonic() < deadline:
            time.sleep(0.005)
        assert old_process.stopped
        assert not new_process.stopped
    finally:
        release_old.set(); release_new.set()
        manager.close()

def test_close_cleans_local_resources_despite_database_error(tmp_path, monkeypatch):
    manager = manager_for(tmp_path, lambda action, payload: {"success": True})
    class Timer:
        cancelled = False
        def cancel(self):
            self.cancelled = True
    timer = Timer()
    event = threading.Event()
    manager._delayed_dispatch["audit-dummy"] = timer
    manager._events["audit-dummy"] = event
    def fail_connection():
        raise sqlite3.OperationalError("audit controlled DB failure")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(manager, "_connect", fail_connection)
            try:
                manager.close()
            except sqlite3.OperationalError:
                pass
        assert timer.cancelled and event.is_set(), {"timer_cancelled": timer.cancelled, "waiter_signalled": event.is_set(), "shutdown_set": manager._shutdown.is_set()}
    finally:
        manager._shutdown.clear()
        manager.close()

def test_unparsed_lockfile_is_not_reported_clean(tmp_path):
    (tmp_path / "Cargo.lock").write_text('version = 3\n[[package]]\nname = "audit-fixture"\nversion = "1.0.0"\n', encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    result = engine.package_audit(str(tmp_path))
    assert result.get("status") != "clean", result

def test_package_manifest_cannot_escape_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest = outside / "requirements.txt"
    manifest.write_text("requests==2.30.0\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    try:
        result = engine.package_audit(str(repo), str(manifest))
    except (ValueError, PermissionError):
        return
    assert result.get("success") is False, {"repository": str(repo), "result": result}



def test_budget_updates_are_atomic_across_engines(tmp_path):
    from types import SimpleNamespace
    store = SimpleNamespace(enabled=True, db_path=str(tmp_path / "budget.sqlite3"))
    engines = [PolicyEngine(store), PolicyEngine(store)]
    engines[0].set_budget("shared", max_external_calls=200)
    start = threading.Barrier(2)
    def consume(engine):
        start.wait(timeout=3)
        for _ in range(10):
            engine.consume("shared", BudgetCost(tokens=2, external_calls=1))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(consume, engine) for engine in engines]
        for future in futures:
            future.result(timeout=10)
    budget = engines[0].get_budget("shared")
    assert (budget.used_tokens, budget.used_external_calls, budget.max_external_calls) == (40, 20, 200)


def test_budget_storage_failure_never_creates_fresh_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import local_ai_hub.agent_policy as policy
    engine = PolicyEngine(SimpleNamespace(enabled=True, db_path=str(tmp_path / "budget.sqlite3")))
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("private path: unavailable")
    monkeypatch.setattr(policy, "connect_sqlite", unavailable)
    with pytest.raises(RuntimeError, match="budget state unavailable"):
        engine.get_budget("uncached")
    assert "uncached" not in engine._budgets
