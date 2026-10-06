from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import app as app_module
from local_ai_hub.agent_memory import MemoryRecord
from local_ai_hub.app import LocalAIApp


class SimulatedProcessCrash(BaseException):
    pass


class _CrashBeforeTransaction:
    def __init__(self, connection, error_type=SimulatedProcessCrash):
        self.connection = connection
        self.error_type = error_type

    def execute(self, sql, *args):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            raise self.error_type()
        return self.connection.execute(sql, *args)

    def close(self):
        self.connection.close()


def _app(config_dir: Path) -> tuple[LocalAIApp, Path]:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(
        f'[server]\nstate_dir = "{(config_dir / "state").as_posix()}"\n'
        "[preprocessing]\nenabled = false\nreject_temp_projects = false\n"
        "[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    return LocalAIApp(str(config_path)), config_path


def _source_bundle(tmp_path: Path, source_root: Path) -> bytes:
    source_app, _ = _app(tmp_path / "source-app")
    try:
        source_root_path = source_root.as_posix()
        source_workspace = source_app.rag.workspace_id(source_root_path)
        source_scope = source_app.rag._scope_key("__preprocess__")
        with closing(source_app.deterministic._connect()) as con:
            con.execute(
                "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
                (source_root_path, "new.py", "new-hash", "python", 0, time.time()),
            )
            con.commit()
        with closing(source_app.rag._connect()) as con:
            con.execute(
                "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                (source_scope, source_workspace, "new.py", 1, 8, "new-hash"),
            )
            con.execute(
                "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
                (source_scope, source_workspace, "new.py", 0, "new-hash", "new bundle text", ""),
            )
            con.commit()
        tenant = "bundle-fixture"
        records = []
        for index in (1, 2):
            task_id = f"bundle-task-{index}"
            records.append(
                source_app.agent_memory.record(
                    MemoryRecord.create(
                        kind="fact",
                        scope="task",
                        scope_id=task_id,
                        key=f"bundle-memory-{index}",
                        value={"index": index},
                        provenance={"root": source_root_path, "tenant": tenant, "task_id": task_id},
                    ),
                    actor="bundle_fixture",
                )
            )
        return source_app.export_bundle(
            source_root_path,
            tenant=tenant,
            agent_state_record_ids=[record.record_id for record in records],
            agent_state_contexts={
                record.record_id: {
                    "scope": record.scope,
                    "scope_id": record.scope_id,
                    "root": source_root_path,
                    "tenant": tenant,
                    "task_id": record.scope_id,
                }
                for record in records
            },
        )
    finally:
        source_app.close()


def _task_memory_context(record: MemoryRecord, tenant: str, root: str) -> dict[str, object]:
    return {
        "scope": record.scope,
        "scope_id": record.scope_id,
        "tenant": tenant,
        "task_id": record.scope_id,
        "root": root,
    }


def test_bundle_import_rejects_malformed_rag_embedding_before_staging(tmp_path: Path) -> None:
    source_root = tmp_path / "source-repo"
    target_root = tmp_path / "target-repo"
    source_root.mkdir()
    target_root.mkdir()
    source_bundle = _source_bundle(tmp_path, source_root)
    with zipfile.ZipFile(io.BytesIO(source_bundle)) as source_archive:
        bundle_data = json.loads(source_archive.read("bundle.json"))

    bundle_data["tables"]["rag_chunks"][0]["embedding"] = {"malformed": True}
    table_json = app_module.json_dumps(
        bundle_data["tables"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    bundle_data["tables_sha256"] = hashlib.sha256(table_json).hexdigest()
    raw_json = app_module.json_dumps(
        bundle_data, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    rewritten_bundle = io.BytesIO()
    with zipfile.ZipFile(rewritten_bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", raw_json)

    target_app, _config_path = _app(tmp_path / "target-app")
    root_path = target_root.as_posix()
    try:
        result = target_app.import_bundle(rewritten_bundle.getvalue(), root_path)

        assert result["success"] is False
        assert result.get("recovery_pending") is not True
        journal_dir = Path(target_app.config["server"]["state_dir"]) / "bundle-imports"
        assert not journal_dir.exists() or not list(journal_dir.glob("*.json"))
        with closing(target_app.deterministic._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM files WHERE root=?", (root_path,)).fetchone()[0] == 0
        workspace = target_app.rag.workspace_id(root_path)
        scope = target_app.rag._scope_key("__preprocess__")
        with closing(target_app.rag._connect()) as con:
            assert con.execute(
                "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=?", (scope, workspace)
            ).fetchone()[0] == 0
        with closing(sqlite3.connect(target_app.agent_state.db_path)) as con:
            imported_memory = con.execute(
                "SELECT key FROM agent_memory_records WHERE key IN (?, ?) ORDER BY key",
                ("bundle-memory-1", "bundle-memory-2"),
            ).fetchall()
            imported_events = con.execute(
                "SELECT COUNT(*) FROM agent_events WHERE idempotency_key LIKE 'bundle-import:%'"
            ).fetchone()[0]
        assert imported_memory == []
        assert imported_events == 0
    finally:
        target_app.close()


@pytest.mark.parametrize(
    "crash_point",
    ["after_preprocessor", "after_deterministic", "after_rag", "after_first_memory_record"],
)
def test_bundle_import_recovers_after_store_commit_crash(tmp_path: Path, monkeypatch, crash_point: str):
    source_root = tmp_path / "source-repo"
    target_root = tmp_path / "target-repo"
    source_root.mkdir()
    target_root.mkdir()
    bundle = _source_bundle(tmp_path, source_root)

    target_app, config_path = _app(tmp_path / "target-app")
    target_root_path = target_root.as_posix()
    target_workspace = target_app.rag.workspace_id(target_root_path)
    target_scope = target_app.rag._scope_key("__preprocess__")
    try:
        with closing(target_app.preprocessor._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at,next_check_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (target_root_path, target_workspace, "failed", "failed", time.time(), time.time(), 0),
            )
            con.commit()
        with closing(target_app.deterministic._connect()) as con:
            con.execute(
                "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
                (target_root_path, "old.py", "old-hash", "python", 0, time.time()),
            )
            con.commit()
        with closing(target_app.rag._connect()) as con:
            con.execute(
                "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                (target_scope, target_workspace, "old.py", 1, 8, "old-hash"),
            )
            con.commit()

        if crash_point == "after_preprocessor":
            original_connect = target_app.deterministic._connect
            monkeypatch.setattr(
                target_app.deterministic,
                "_connect",
                lambda: _CrashBeforeTransaction(original_connect()),
            )
        elif crash_point == "after_deterministic":
            original_connect = target_app.rag._connect
            monkeypatch.setattr(
                target_app.rag,
                "_connect",
                lambda: _CrashBeforeTransaction(original_connect()),
            )
        else:
            original_record = target_app.agent_memory.record
            calls = 0

            def crash_during_memory_records(*args, **kwargs):
                nonlocal calls
                calls += 1
                if crash_point == "after_rag" and calls == 1:
                    raise SimulatedProcessCrash()
                result = original_record(*args, **kwargs)
                if crash_point == "after_first_memory_record" and calls == 2:
                    raise SimulatedProcessCrash()
                return result

            monkeypatch.setattr(target_app.agent_memory, "record", crash_during_memory_records)
        with pytest.raises(SimulatedProcessCrash):
            target_app.import_bundle(bundle, target_root_path)
        with closing(target_app.preprocessor._connect()) as con:
            interrupted_project = con.execute(
                "SELECT status FROM projects WHERE root=?", (target_root_path,)
            ).fetchone()
        assert interrupted_project is not None and interrupted_project[0] == "complete"
        journal_files = list((Path(target_app.config["server"]["state_dir"]) / "bundle-imports").glob("*.json"))
        assert len(journal_files) == 1
        manifest = json.loads(journal_files[0].read_text(encoding="utf-8"))
        assert manifest["status"] == "incomplete"
        expected_phases = {
            "after_preprocessor": ["preprocessor"],
            "after_deterministic": ["preprocessor", "deterministic"],
            "after_rag": ["preprocessor", "deterministic", "rag"],
            "after_first_memory_record": ["preprocessor", "deterministic", "rag"],
        }
        assert manifest["completed_phases"] == expected_phases[crash_point]
    finally:
        target_app.close()

    recovered_app = LocalAIApp(str(config_path))
    try:
        with closing(recovered_app.preprocessor._connect()) as con:
            project = con.execute(
                "SELECT status FROM projects WHERE root=?", (target_root_path,)
            ).fetchone()
        with closing(recovered_app.deterministic._connect()) as con:
            files = con.execute(
                "SELECT path,content_hash FROM files WHERE root=?", (target_root_path,)
            ).fetchall()
        with closing(recovered_app.rag._connect()) as con:
            chunks = con.execute(
                "SELECT path,text FROM chunks WHERE tenant=? AND workspace=?",
                (target_scope, target_workspace),
            ).fetchall()
        with closing(sqlite3.connect(recovered_app.agent_state.db_path)) as con:
            memory_keys = con.execute(
                "SELECT key FROM agent_memory_records WHERE key IN (?, ?) ORDER BY key",
                ("bundle-memory-1", "bundle-memory-2"),
            ).fetchall()
            imported_events = con.execute(
                "SELECT COUNT(*) FROM agent_events WHERE idempotency_key LIKE 'bundle-import:%'"
            ).fetchone()[0]

        assert project is not None and project[0] == "complete"
        assert [(row[0], row[1]) for row in files] == [("new.py", "new-hash")]
        assert [(row[0], row[1]) for row in chunks] == [("new.py", "new bundle text")]
        assert [row[0] for row in memory_keys] == ["bundle-memory-1", "bundle-memory-2"]
        assert imported_events == 2
        assert recovered_app._bundle_import_recovery == {"status": "complete", "recovered": 1}
        assert not list((Path(recovered_app.config["server"]["state_dir"]) / "bundle-imports").glob("*.json"))
    finally:
        recovered_app.close()


def test_bundle_import_reports_incomplete_and_keeps_recovery_intent(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source-repo"
    target_root = tmp_path / "target-repo"
    source_root.mkdir()
    target_root.mkdir()
    bundle = _source_bundle(tmp_path, source_root)

    target_app, config_path = _app(tmp_path / "target-app")
    target_root_path = target_root.as_posix()
    original_connect = target_app.deterministic._connect
    monkeypatch.setattr(
        target_app.deterministic,
        "_connect",
        lambda: _CrashBeforeTransaction(original_connect(), RuntimeError),
    )
    try:
        result = target_app.import_bundle(bundle, target_root_path)
        assert result["success"] is False
        assert result["status"] == "incomplete"
        assert result["degraded"] is True
        assert result["recovery_pending"] is True
        journal_dir = Path(target_app.config["server"]["state_dir"]) / "bundle-imports"
        assert len(list(journal_dir.glob("*.json"))) == 1
    finally:
        target_app.close()

    recovered_app = LocalAIApp(str(config_path))
    try:
        assert recovered_app._bundle_import_recovery == {"status": "complete", "recovered": 1}
        with closing(recovered_app.deterministic._connect()) as con:
            files = con.execute(
                "SELECT path,content_hash FROM files WHERE root=?", (target_root_path,)
            ).fetchall()
        assert [(row[0], row[1]) for row in files] == [("new.py", "new-hash")]
    finally:
        recovered_app.close()


def test_agent_state_bundle_recovers_after_partial_memory_commit(tmp_path: Path, monkeypatch):
    source_app, _ = _app(tmp_path / "source-app")
    source_root = tmp_path / "source-repo"
    source_root.mkdir()
    source_root_path = source_root.as_posix()
    try:
        tenant = "bundle-fixture"
        records = []
        for index in (1, 2):
            task_id = f"standalone-task-{index}"
            records.append(
                source_app.agent_memory.record(
                    MemoryRecord.create(
                        kind="fact", scope="task", scope_id=task_id,
                        key=f"standalone-memory-{index}", value=index,
                        provenance={"root": source_root_path, "tenant": tenant, "task_id": task_id},
                    ),
                    actor="bundle_fixture",
                )
            )
        bundle = source_app.export_bundle(
            source_root_path,
            tenant=tenant,
            agent_state_record_ids=[record.record_id for record in records],
            agent_state_contexts={record.record_id: _task_memory_context(record, tenant, source_root_path) for record in records},
        )
    finally:
        source_app.close()

    target_app, config_path = _app(tmp_path / "target-app")
    original_record = target_app.agent_memory.record
    calls = 0

    def crash_after_first_record(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original_record(*args, **kwargs)
        if calls == 1:
            raise SimulatedProcessCrash()
        return result

    monkeypatch.setattr(target_app.agent_memory, "record", crash_after_first_record)
    try:
        with pytest.raises(SimulatedProcessCrash):
            target_app.import_bundle(bundle)
    finally:
        target_app.close()

    recovered_app = LocalAIApp(str(config_path))
    try:
        with closing(sqlite3.connect(recovered_app.agent_state.db_path)) as con:
            keys = con.execute(
                "SELECT key FROM agent_memory_records WHERE key LIKE 'standalone-memory-%' ORDER BY key"
            ).fetchall()
            imported_events = con.execute(
                "SELECT COUNT(*) FROM agent_events WHERE idempotency_key LIKE 'bundle-import:%'"
            ).fetchone()[0]
        assert [row[0] for row in keys] == ["standalone-memory-1", "standalone-memory-2"]
        assert imported_events == 2
        assert recovered_app._bundle_import_recovery == {"status": "complete", "recovered": 1}
    finally:
        recovered_app.close()


def test_invalid_pending_journal_fails_app_startup_closed(tmp_path: Path):
    config_dir = tmp_path / "target-app"
    journal_dir = config_dir / "state" / "bundle-imports"
    journal_dir.mkdir(parents=True)
    (journal_dir / "invalid.json").write_text('{"schema_version":1,"import_id":"bad"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="bundle import recovery incomplete"):
        _app(config_dir)


def test_startup_replays_bundle_imports_before_async_jobs(tmp_path: Path, monkeypatch):
    startup_order: list[str] = []
    original_recovery = LocalAIApp._recover_pending_bundle_imports

    def recover_bundles(app: LocalAIApp) -> None:
        startup_order.append("bundles")
        original_recovery(app)

    monkeypatch.setattr(LocalAIApp, "_recover_pending_bundle_imports", recover_bundles)
    monkeypatch.setattr(app_module.AsyncJobManager, "recover", lambda _jobs: startup_order.append("jobs"))

    app, _ = _app(tmp_path / "target-app")
    try:
        assert startup_order.index("bundles") < startup_order.index("jobs")
    finally:
        app.close()


def test_staging_journal_replays_and_orphan_payload_fails_closed(tmp_path: Path):
    source_root = tmp_path / "source-repo"
    source_root.mkdir()
    bundle = _source_bundle(tmp_path, source_root)
    target_dir = tmp_path / "target-app"
    target_app, config_path = _app(target_dir)
    target_app.close()

    bundle_hash = hashlib.sha256(bundle).hexdigest()
    import_id = hashlib.sha256(f"{bundle_hash}\0".encode("utf-8")).hexdigest()
    journal_dir = target_dir / "state" / "bundle-imports"
    journal_dir.mkdir(parents=True)
    (journal_dir / f"{import_id}.bundle").write_bytes(bundle)
    (journal_dir / f"{import_id}.json").write_text(
        json.dumps({
            "schema_version": 1,
            "import_id": import_id,
            "bundle_sha256": bundle_hash,
            "target_root": None,
            "status": "staging",
            "completed_phases": [],
            "updated_at": time.time(),
        }),
        encoding="utf-8",
    )

    recovered_app = LocalAIApp(str(config_path))
    try:
        assert recovered_app._bundle_import_recovery == {"status": "complete", "recovered": 1}
    finally:
        recovered_app.close()

    (journal_dir / "orphan.bundle").write_bytes(b"untracked staged payload")
    with pytest.raises(RuntimeError, match="untracked staged bundle payload"):
        LocalAIApp(str(config_path))


def test_staging_journal_without_payload_fails_startup_closed(tmp_path: Path):
    config_dir = tmp_path / "target-app"
    app, config_path = _app(config_dir)
    app.close()
    journal_dir = config_dir / "state" / "bundle-imports"
    journal_dir.mkdir(parents=True)
    import_id = "a" * 64
    (journal_dir / f"{import_id}.json").write_text(
        json.dumps({
            "schema_version": 1,
            "import_id": import_id,
            "bundle_sha256": "b" * 64,
            "target_root": None,
            "status": "staging",
            "completed_phases": [],
            "updated_at": time.time(),
        }),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="staged payload is missing"):
        LocalAIApp(str(config_path))


def test_payload_staging_failure_reports_pending_recovery(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source-repo"
    target_root = tmp_path / "target-repo"
    source_root.mkdir()
    target_root.mkdir()
    bundle = _source_bundle(tmp_path, source_root)
    target_app, config_path = _app(tmp_path / "target-app")
    original_temporary_file = tempfile.NamedTemporaryFile

    def fail_payload_staging(*args, **kwargs):
        if str(kwargs.get("prefix", "")).endswith(".bundle."):
            raise OSError("simulated payload staging failure")
        return original_temporary_file(*args, **kwargs)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", fail_payload_staging)
    try:
        result = target_app.import_bundle(bundle, target_root.as_posix())
        assert result["success"] is False
        assert result["status"] == "incomplete"
        assert result["degraded"] is True
        assert result["recovery_pending"] is True
    finally:
        target_app.close()

    with pytest.raises(RuntimeError, match="staged payload is missing"):
        LocalAIApp(str(config_path))


def test_agent_state_initial_journal_failure_reports_no_pending_recovery(tmp_path: Path, monkeypatch):
    source_app, _ = _app(tmp_path / "source-app")
    source_root = tmp_path / "source-repo"
    source_root.mkdir()
    source_root_path = source_root.as_posix()
    try:
        tenant = "bundle-fixture"
        task_id = "staging-failure-task"
        record = source_app.agent_memory.record(
            MemoryRecord.create(
                kind="fact", scope="task", scope_id=task_id, key="staging-failure", value=True,
                provenance={"root": source_root_path, "tenant": tenant, "task_id": task_id},
            ),
            actor="bundle_fixture",
        )
        bundle = source_app.export_bundle(
            source_root_path,
            tenant=tenant,
            agent_state_record_ids=[record.record_id],
            agent_state_contexts={record.record_id: _task_memory_context(record, tenant, source_root_path)},
        )
    finally:
        source_app.close()

    target_app, _ = _app(tmp_path / "target-app")
    original_temporary_file = tempfile.NamedTemporaryFile

    def fail_journal_staging(*args, **kwargs):
        if str(kwargs.get("prefix", "")).endswith(".json."):
            raise OSError("simulated initial journal failure")
        return original_temporary_file(*args, **kwargs)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", fail_journal_staging)
    try:
        result = target_app.import_bundle(bundle)
        assert result["success"] is False
        assert result["status"] == "not_started"
        assert result["degraded"] is False
        assert result["recovery_pending"] is False
    finally:
        target_app.close()


def test_dangling_journal_directory_symlink_fails_closed(tmp_path: Path, monkeypatch):
    app, _ = _app(tmp_path / "target-app")
    app.close()
    journal_dir = Path(app.config["server"]["state_dir"]) / "bundle-imports"
    original_exists = Path.exists
    original_is_symlink = Path.is_symlink

    def exists(path: Path) -> bool:
        if path == journal_dir:
            return False
        return original_exists(path)

    def is_symlink(path: Path) -> bool:
        if path == journal_dir:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    with pytest.raises(RuntimeError, match="journal path is not a regular directory"):
        app._recover_pending_bundle_imports()


def test_pending_bundle_recovery_rejects_target_root_identity_mismatch(
    tmp_path: Path, monkeypatch
):
    app, _ = _app(tmp_path / "target-app")
    payload = b"staged bundle payload"
    bundle_sha256 = hashlib.sha256(payload).hexdigest()
    recorded_root = str((tmp_path / "recorded-root").resolve(strict=False)).replace("\\", "/")
    forged_root = str((tmp_path / "forged-root").resolve(strict=False)).replace("\\", "/")
    import_id = hashlib.sha256(f"{bundle_sha256}\0{recorded_root}".encode("utf-8")).hexdigest()
    journal_dir = Path(app.config["server"]["state_dir"]) / "bundle-imports"
    journal_dir.mkdir(parents=True)
    (journal_dir / f"{import_id}.bundle").write_bytes(payload)
    (journal_dir / f"{import_id}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "import_id": import_id,
                "bundle_sha256": bundle_sha256,
                "target_root": forged_root,
                "status": "incomplete",
                "completed_phases": [],
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    replayed_roots: list[str | None] = []
    monkeypatch.setattr(
        app,
        "import_bundle",
        lambda _payload, root=None: replayed_roots.append(root) or {"success": True},
    )
    try:
        with pytest.raises(RuntimeError, match="target root does not match import identity"):
            app._recover_pending_bundle_imports()

        assert replayed_roots == []
    finally:
        app.close()
