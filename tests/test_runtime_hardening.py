from __future__ import annotations

import time
import os
import json
import threading

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub import client as client_module
from local_ai_hub import supervisor as supervisor_module
from local_ai_hub.cache import stable_hash
from local_ai_hub.client import HubClient
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.supervisor import Supervisor


class _Scheduler:
    def acquire_background_gpu(self, _idle_seconds: float) -> bool:
        return True

    def release_background_gpu(self) -> None:
        pass

    def foreground_busy(self) -> bool:
        return False

    def foreground_idle_seconds(self) -> float:
        return 999.0


class _OfflineRuntime:
    def is_online(self) -> bool:
        return False

    def ensure_running(self) -> bool:
        return False

    def stop_managed_server(self) -> None:
        pass


def test_background_gpu_failed_start_enters_exponential_cooldown(tmp_path):
    worker = IdleGPUWorker(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"background_code": "small"},
            "background_gpu": {
                "enabled": True,
                "start_failure_retry_initial_seconds": 30,
                "start_failure_retry_max_seconds": 120,
                "start_failure_max_attempts": 2,
            },
        },
        _Scheduler(),
    )
    worker.runtime = _OfflineRuntime()
    try:
        assert not worker._acquire_session()
        assert worker.status()["retry_after_seconds"] >= 29
        assert worker.status()["stats"]["start_failures"] == 1

        worker._retry_after = time.monotonic() - 1
        assert not worker._acquire_session()
        assert worker.status()["retry_after_seconds"] >= 59
        assert worker.status()["startup_circuit_open"] is True

        worker._retry_after = time.monotonic() - 1
        assert not worker._acquire_session()
        assert worker.status()["stats"]["start_failures"] == 2
    finally:
        worker.close()


def test_background_cpu_fallback_uses_its_own_serial_cpu_profile(tmp_path):
    worker = IdleGPUWorker(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"background_code": "small"},
            "model_execution": {"background": {"parallel": 8, "background_context_tokens": 16384}},
            "background_gpu": {
                "enabled": True,
                "parallel": 8,
                "cpu_fallback_enabled": True,
                "cpu_ollama_url": "http://127.0.0.1:11439",
                "cpu_context_tokens": 32768,
            },
        },
        _Scheduler(),
    )
    try:
        assert worker.cpu_runtime._configured_environment()["OLLAMA_LLM_LIBRARY"] == "cpu"
        assert worker.cpu_policy.profile("small", background=True).num_ctx == 32768
        assert worker.cpu_policy.profile("small", background=True).parallel_limit == 1
    finally:
        worker.close()


def test_client_does_not_spawn_when_hub_port_is_already_owned(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=11435\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n"
        "[headless]\nrespect_disabled_marker=true\n",
        encoding="utf-8",
    )
    client = HubClient(tenant="test", config_path=str(config))
    monkeypatch.setattr(client, "_online", lambda: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: os.getpid())
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")))
    assert client.ensure_server() is False


def test_client_does_not_bypass_live_managed_supervisor(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    state = tmp_path / "state"
    state.mkdir()
    config.write_text(
        "[server]\nport=11435\nstate_dir='" + state.as_posix() + "'\n"
        "[headless]\nrespect_disabled_marker=true\n",
        encoding="utf-8",
    )
    (state / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
    client = HubClient(tenant="test", config_path=str(config))
    monkeypatch.setattr(client, "_online", lambda: False)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")))
    assert client.ensure_server() is False


def test_client_does_not_direct_spawn_during_managed_restart(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    state = tmp_path / "state"
    state.mkdir()
    config.write_text(
        "[server]\nport=11435\nstate_dir='" + state.as_posix() + "'\n"
        "[headless]\nrespect_disabled_marker=true\n",
        encoding="utf-8",
    )
    (state / "service.managed").write_text("managed", encoding="utf-8")
    client = HubClient(tenant="test", config_path=str(config))
    monkeypatch.setattr(client, "_online", lambda: False)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")))
    assert client.ensure_server() is False


def test_supervisor_status_replaces_stale_hub_pid_with_owned_child(tmp_path):
    class _Child:
        pid = os.getpid()

        def poll(self):
            return None

    supervisor = Supervisor.__new__(Supervisor)
    supervisor.state_dir = tmp_path
    supervisor.status_path = tmp_path / "supervisor.status.json"
    supervisor.child = _Child()
    supervisor.config = {"server": {"port": 11435}}
    supervisor.started_at = 0.0
    supervisor.restarts = 1
    (tmp_path / "hub.pid").write_text("999999", encoding="utf-8")
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(supervisor_module, "find_listening_pid", lambda _port: os.getpid())
    supervisor.write_status("running")
    monkeypatch.undo()
    assert int((tmp_path / "hub.pid").read_text(encoding="utf-8")) == os.getpid()
    assert json.loads(supervisor.status_path.read_text(encoding="utf-8"))["hub_pid"] == os.getpid()


def test_supervisor_terminate_child_reaps_orphaned_pid_and_unlinks_file(tmp_path, monkeypatch):
    terminated: list[int] = []
    monkeypatch.setattr(supervisor_module, "terminate_tree", lambda pid, grace_seconds=5.0: terminated.append(pid))
    monkeypatch.setattr(supervisor_module, "find_listening_pid", lambda _port: 55555)
    monkeypatch.setattr(supervisor_module, "pid_alive", lambda pid: True)

    supervisor = Supervisor.__new__(Supervisor)
    supervisor.state_dir = tmp_path
    supervisor.child = None
    supervisor.config = {"server": {"port": 11435}}
    pid_file = tmp_path / "hub.pid"
    pid_file.write_text("66666", encoding="utf-8")

    supervisor.terminate_child()

    assert 55555 in terminated
    assert 66666 in terminated
    assert not pid_file.exists()


def test_embedding_first_batch_uses_persistent_cache(tmp_path, monkeypatch):
    model_name = "BAAI/bge-small-en-v1.5"
    embeddings = EmbeddingModel(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"embedding": model_name, "embedding_backend": "sentence-transformers"},
            "cache": {"embeddings": True},
        }
    )
    monkeypatch.setattr(embeddings, "_ensure_model", lambda: True)
    identity = f"sentence-transformers:{model_name}"
    key = stable_hash({"v": 2, "identity": identity, "query": False, "text": "shared content"})
    embeddings.cache.set(key, {"identity": identity, "dimension": 2, "vector": [0.2, 0.8]})

    result = embeddings.encode(["shared content"])

    assert result["cache_hits"] == 1
    assert result["computed"] == 0


def test_registry_repair_reactivates_the_selected_project(tmp_path):
    processor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    processor.db_path = tmp_path / "preprocess.sqlite3"
    processor._db_lock = threading.RLock()
    processor._sqlite_busy_seconds = 0.5
    processor.install_root = tmp_path / "install"
    processor.state_dir = tmp_path / "state"
    processor.cfg = {"ignore_internal_install": True}
    processor.max_preprocessing_projects = 1
    processor.reject_temp_projects = False
    processor._init_db()

    now = time.time()
    older = str(tmp_path / "older-project")
    newest = str(tmp_path / "newest-project")
    con = processor._connect()
    try:
        for root, requested_at in ((older, now - 10), (newest, now)):
            con.execute(
                """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (root, root, "waiting", "inventory", 0, 0, now, now, 0, 0, requested_at, "test"),
            )
        con.commit()
    finally:
        con.close()

    processor._repair_registry()

    con = processor._connect()
    try:
        rows = {row[0]: (row[1], row[2]) for row in con.execute("SELECT root,paused,status FROM projects")}
    finally:
        con.close()
    assert rows[newest] == (0, "queued")
    assert rows[older] == (0, "waiting")


def test_processing_slot_limit_waits_without_pausing_projects(tmp_path):
    processor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    processor.db_path = tmp_path / "preprocess.sqlite3"
    processor._db_lock = threading.RLock()
    processor._sqlite_busy_seconds = 0.5
    processor.install_root = tmp_path / "install"
    processor.state_dir = tmp_path / "state"
    processor.cfg = {"ignore_internal_install": True}
    processor.max_preprocessing_projects = 3
    processor.reject_temp_projects = False
    processor._init_db()

    now = time.time()
    con = processor._connect()
    try:
        for index in range(5):
            root = str(tmp_path / f"project-{index}")
            con.execute(
                """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (root, root, "queued", "inventory", 0, 0, now, now, 0, 0, now - index, "test"),
            )
        con.commit()
    finally:
        con.close()

    con = processor._connect()
    try:
        processor._rebalance_processing_slots(con)
        con.commit()
    finally:
        con.close()

    con = processor._connect()
    try:
        rows = con.execute("SELECT paused,status FROM projects ORDER BY root").fetchall()
    finally:
        con.close()
    assert all(row[0] == 0 for row in rows)
    assert [row[1] for row in rows].count("queued") == 3
    assert [row[1] for row in rows].count("waiting") == 2

    manual_root = str(tmp_path / "manual-paused")
    con = processor._connect()
    try:
        con.execute(
            """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (manual_root, manual_root, "paused", "inventory", 0, 0, now, now, 0, 1, now, "test"),
        )
        processor._rebalance_processing_slots(con)
        con.commit()
    finally:
        con.close()
    con = processor._connect()
    try:
        manual = con.execute("SELECT paused,status FROM projects WHERE root=?", (manual_root,)).fetchone()
    finally:
        con.close()
    assert tuple(manual) == (1, "paused")
