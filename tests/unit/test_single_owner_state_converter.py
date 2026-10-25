import importlib.util
import hashlib
import json
import sqlite3
from pathlib import Path
from contextlib import closing

import pytest


_TOOL = Path(__file__).parents[2] / "tools" / "convert_single_owner_state.py"
_SPEC = importlib.util.spec_from_file_location("single_owner_state_converter", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
_converter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_converter)


def test_sqlite_generated_target_objects_use_registered_sql_normalization(monkeypatch):
    with closing(sqlite3.connect(":memory:")) as connection:
        for statement in _converter._STORE_DDL["agent_state"][0].values():
            connection.execute(statement)
        _converter._verify_generated_agent_objects(connection)
        identity = ("table", "agent_memory_fts_config", "agent_memory_fts_config")
        monkeypatch.setitem(_converter._GENERATED_AGENT_HASHES, identity, "0" * 64)
        with pytest.raises(_converter.ConversionError, match="generated Agent State object pin mismatch"):
            _converter._verify_generated_agent_objects(connection)


def test_converted_target_schema_is_accepted_by_current_event_store(tmp_path):
    from local_ai_hub.agent_events import AgentStateStore

    target = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(target)) as connection, connection:
        _converter._initialize_target_schema(connection, "agent_state")
        for statement in _converter._STORE_DDL["agent_state"][1]:
            connection.execute(statement)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == AgentStateStore._SCHEMA_VERSION
        AgentStateStore._classify_schema(connection)
    AgentStateStore(target)._ensure_schema()


def test_failed_conversion_closes_source_cursor_before_temporary_cleanup(tmp_path, monkeypatch):
    source = tmp_path / "memos.sqlite"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE memos (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1, tenant TEXT NOT NULL, PRIMARY KEY(tenant, workspace, memo_key))")
        connection.execute("CREATE TABLE memo_versions (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, version INTEGER NOT NULL, tenant TEXT NOT NULL, PRIMARY KEY(tenant, workspace, memo_key))")
        for statement in _converter._STORE_DDL["workspace_memos"][1]:
            connection.execute(statement)
        for key in ("first", "second"):
            connection.execute("INSERT INTO memos VALUES (?,?,?,?,?,?,?,?)", ("project", key, "preserve", "{}", 1.0, 0.0, 1, "retired"))
            connection.execute("INSERT INTO memo_versions VALUES (?,?,?,?)", ("project", key, 1, "retired"))
    original = source.read_bytes()
    monkeypatch.setattr(_converter, "_MAX_PROVENANCE_VALUE_CHARS", 1)
    target = tmp_path / "converted.sqlite"
    with pytest.raises(_converter.ConversionError, match="removed tenant field exceeds supported provenance size"):
        _converter.convert_sqlite_store(source, target)
    assert source.read_bytes() == original
    assert not target.exists()
    assert not list(tmp_path.glob("single-owner-conversion-*"))


def test_plan_refuses_provenance_budget_before_target_creation(tmp_path, monkeypatch):
    source = tmp_path / "memos.sqlite"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE memos (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1, tenant TEXT NOT NULL, PRIMARY KEY(tenant, workspace, memo_key))")
        connection.execute("CREATE TABLE memo_versions (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, version INTEGER NOT NULL, tenant TEXT NOT NULL, PRIMARY KEY(tenant, workspace, memo_key))")
        connection.execute("INSERT INTO memos VALUES ('project','key','value','{}',1,0,1,'retired')")
        connection.execute("INSERT INTO memo_versions VALUES ('project','key',1,'retired')")
    monkeypatch.setattr(_converter, "_MAX_PROVENANCE_ENTRIES", 1)
    plan = _converter.plan_sqlite_store(source, _converter.inventory_sqlite(source))
    assert plan["conversion_support"] == "unsupported_schema"
    assert "provenance exceeds supported record bound" in plan["conversion_reason"]


def test_json_conversion_removes_retired_keys_by_presence_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "settings.json"
    target = tmp_path / "converted.json"
    original = {"api_token": "kept", "security": {"api_token_tenant": None},
                "server": {"tenant": None, "port": 7312}, "task": {"tenant_scope": False}}
    source.write_text(json.dumps(original), encoding="utf-8")
    source_before = source.read_bytes()

    result = _converter.convert_config(source, target)

    assert source.read_bytes() == source_before
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "api_token": "kept", "security": {}, "server": {"tenant": None, "port": 7312},
        "task": {"tenant_scope": False}}
    assert result["removed_paths"] == ["$.security.api_token_tenant"]


def test_static_sqlite_contracts_load_without_importing_runtime_modules() -> None:
    assert {"async_jobs", "debug_traces", "telemetry", "work_orchestrator"} <= set(_converter._STORE_DDL)
    assert {"swarm", "leases", "work_fencing"} <= set(_converter._STORE_DDL)
    assert _converter._AGENT_CONTRACTS["AGENT_STATE_STORE_DDL"] == {}
    assert _converter._known_unsupported_store({"agent_events", "leases"}) is not None
    legacy_agent_tables = {
        name for kind, name, _table in (
            set(_converter._SOURCE_AGENT_HASHES) | set(_converter._GENERATED_AGENT_HASHES))
        if kind == "table" and not name.startswith("sqlite_")
    } | set(_converter._AGENT_ARCHIVE_TABLES)
    assert _converter._known_unsupported_store(legacy_agent_tables) is None
    partial = _converter._known_unsupported_store(legacy_agent_tables - {"agent_events"})
    assert partial is not None and partial["missing_objects"] == ("agent_events",)
    async_indexes = _converter._canonical_index_contract("async_jobs")
    request_index = async_indexes[("async_jobs", "idx_async_jobs_request_id")]
    assert "json_type" in request_index[0] and request_index[3] == 1
    trace_fks = _converter._canonical_foreign_keys("debug_traces", "trace_events")
    assert any(item[2] == "traces" and item[6] == "CASCADE" for item in trace_fks)


def test_agent_state_sql_pin_hash_uses_runtime_normalization() -> None:
    import hashlib

    sql = "CREATE TABLE X (\n  a TEXT\n)"
    expected = hashlib.sha256("create table x ( a text )".encode("utf-8")).hexdigest()
    assert _converter._agent_object_sql_sha256(sql) == expected
    assert _converter._agent_object_sql_sha256("create   table x ( a text )") == expected


def test_legacy_source_sql_pin_accepts_only_registered_exact_variants(monkeypatch) -> None:
    accepted = {"e9a38812fd120d00228269c2e5f28f02172702355abd9127562ccf78a5c93612",
                "314dbe78e360c6c00133c85323b9349936d9cb2e87121e60c8ffb733b46d20aa"}
    monkeypatch.setattr(_converter, "_agent_object_sql_sha256", lambda _sql: next(iter(accepted)))
    assert _converter._matches_source_agent_sql_pin("pinned SQL", accepted)
    assert not _converter._matches_source_agent_sql_pin("unregistered SQL", {"0" * 64})
    assert not _converter._matches_source_agent_sql_pin("unregistered SQL", [])
    assert _converter._SOURCE_COMPONENTS_SHA256_SCOPE == _converter._WRITER_DISPOSITION_API.SOURCE_SHA256_SCOPE
    assert "task-row SHA-256 is separately pinned" in _converter._SOURCE_COMPONENTS_SHA256_SCOPE


def test_structured_store_preflight_uses_row_data_not_table_presence(request) -> None:
    async_reasons = _converter._transform_requirements("async_jobs", [
        {"table": "async_jobs"}, {"table": "async_job_progress"}])
    telemetry_reasons = _converter._transform_requirements("telemetry", [
        {"table": "snapshots"}, {"table": "events"}])
    trace_reasons = _converter._transform_requirements("debug_traces", [
        {"table": "traces"}, {"table": "trace_events"}])
    assert async_reasons == []
    assert telemetry_reasons == []
    assert trace_reasons == []
    assert _converter._transform_requirements("work_orchestrator", [{"table": "work_orders"}]) == []
    assert _converter._transform_requirements("swarm", [{"table": "agent_swarms"}]) == []

    database = sqlite3.connect(":memory:")
    request.addfinalizer(database.close)
    database.execute("CREATE TABLE async_jobs(job_id TEXT, payload_json TEXT, result_json TEXT)")
    database.execute("INSERT INTO async_jobs VALUES(?,?,?)", ("clean", '{"task":"tenant is prose"}', '{"captured":{"tenant":"opaque project data"}}'))
    async_tables = [{"table": "async_jobs", "columns": ["job_id", "payload_json", "result_json"]}]
    assert _converter._data_transform_requirements(database, "async_jobs", async_tables) == []
    database.execute("UPDATE async_jobs SET payload_json=? WHERE job_id='clean'", ('{"tasks":[{"tenant":null}]}',))
    assert any("async_jobs.payload_json" in item for item in
               _converter._data_transform_requirements(database, "async_jobs", async_tables))
    database.execute("UPDATE async_jobs SET payload_json=?, result_json=? WHERE job_id='clean'",
                     ('{"task":"clean"}', '{"metadata":{"tenant":null}}'))
    assert any("async_jobs.result_json" in item for item in
               _converter._data_transform_requirements(database, "async_jobs", async_tables))

    database.execute("CREATE TABLE snapshots(snapshot_id TEXT, metrics_json TEXT)")
    database.execute("INSERT INTO snapshots VALUES(?,?)", ("s1", '{"label":"tenant is prose"}'))
    telemetry_tables = [{"table": "snapshots", "columns": ["snapshot_id", "metrics_json"]}]
    assert _converter._data_transform_requirements(database, "telemetry", telemetry_tables) == []
    database.execute("UPDATE snapshots SET metrics_json=?", ('{"metadata":{"tenant_id":false}}',))
    assert any("snapshots.metrics_json" in item for item in
               _converter._data_transform_requirements(database, "telemetry", telemetry_tables))


def test_scope_and_workorder_preflight_only_blocks_invalid_rows(request) -> None:
    database = sqlite3.connect(":memory:")
    request.addfinalizer(database.close)
    database.execute("CREATE TABLE writer_fence_leases(scope_id TEXT)")
    database.execute("INSERT INTO writer_fence_leases VALUES(?)", ("project:repo",))
    table = [{"table": "writer_fence_leases", "columns": ["scope_id"]}]
    assert _converter._data_transform_requirements(database, "work_fencing", table) == []
    database.execute("UPDATE writer_fence_leases SET scope_id='' ")
    assert any("scope_id" in item for item in _converter._data_transform_requirements(database, "work_fencing", table))

    database.execute("CREATE TABLE work_orders(work_id TEXT, payload_json TEXT)")
    database.execute("INSERT INTO work_orders VALUES(?,?)", ("w1", '{"metadata":{"tenant":"opaque nested data"}}'))
    work_tables = [{"table": "work_orders", "columns": ["work_id", "payload_json"]}]
    assert _converter._data_transform_requirements(database, "work_orchestrator", work_tables) == []
    database.execute("UPDATE work_orders SET payload_json=?", ('{"tenant":""}',))
    assert any("work_orders.payload_json" in item for item in
               _converter._data_transform_requirements(database, "work_orchestrator", work_tables))


def test_agent_state_contract_pins_archive_and_derived_index_policy(tmp_path: Path) -> None:
    assert len(_converter._EXPECTED_AGENT_HASHES) == 65
    assert len(_converter._SOURCE_AGENT_HASHES) + len(_converter._GENERATED_AGENT_HASHES) == 68
    assert "agent_memory_fts" in _converter._STORE_DDL["agent_state"][0]
    assert _converter._COMPLETE_AGENT["FTS_REBUILD_SOURCE"] == "agent_memory_records"
    context_contract = next(item for item in _converter._JSON_TRANSFORMS
                            if item.get("table") == "agent_tasks_projection" and item.get("column") == "context")
    assert "required_schema_version" not in context_contract
    archive_manifest = tmp_path / "archive-disposition.json"
    archive_manifest.write_text(json.dumps({
        "source_sha256": "a" * 64,
        "dispositions": [
            {"table": table, "disposition": "archive_external"}
            for table in _converter._AGENT_ARCHIVE_TABLES],
    }), encoding="utf-8")
    _converter.validate_archive_manifest("a" * 64, tuple(_converter._AGENT_ARCHIVE_TABLES), archive_manifest)
    reasons = _converter._transform_requirements("agent_state", [
        {"table": "agent_swarms"}, {"table": "leases"}, {"table": "agent_memory_records"}])
    assert not any("owner mapping" in item for item in reasons)
    assert not any("agent_memory_records.provenance" in item for item in reasons)


def test_async_result_preflight_matches_runtime_one_level_control_contract() -> None:
    assert _converter._async_result_retired_key({"captured": {"tenant": None}}) is None
    assert _converter._async_result_retired_key({"metadata": {"captured": {"tenant": None}}}) is None
    assert _converter._async_result_retired_key({"metadata": {"tenant": None}}) == "tenant"


def test_writer_mapping_requires_actual_task_rows_and_explicit_map(request) -> None:
    database = sqlite3.connect(":memory:")
    request.addfinalizer(database.close)
    database.execute("CREATE TABLE leases(lease_id, tenant, root_id, root_path, path, purpose, created_at, expires_at)")
    database.execute("INSERT INTO leases VALUES('l1','old','r1','C:/repo','C:/repo/a','write',1,2)")
    tables = [
        {"table": "leases", "columns": ["lease_id", "tenant", "root_id", "root_path", "path", "purpose", "created_at", "expires_at"], "rows": 1},
        {"table": "agent_tasks_projection", "columns": ["task_id", "owner", "checkpoint"], "rows": 0},
    ]
    with __import__("pytest").raises(_converter.ConversionError, match="--writer-map"):
        _converter._preflight_writer_rows(database, tables, "a" * 64, None, {})
    without_task = [tables[0]]
    with __import__("pytest").raises(_converter.ConversionError, match="same source snapshot"):
        _converter._preflight_writer_rows(database, without_task, "a" * 64, None, {})


def test_writer_map_rejects_task_fact_drift_even_when_lease_row_is_unchanged(tmp_path: Path) -> None:
    helper = _converter._WRITER_DISPOSITION_API
    source_sha = "a" * 64
    pinned_task_row_sha = "b" * 64
    row = {"lease_id": "lease-1", "tenant": "legacy", "root_id": "root-1",
           "root_path": str(tmp_path), "path": str(tmp_path / "file"), "purpose": "write",
           "created_at": 1.0, "expires_at": 2.0}
    manifest_path = tmp_path / "writer-map.json"
    manifest_path.write_text(json.dumps({
        "schema": helper.WRITER_MAP_SCHEMA,
        "source_sha256": source_sha,
        "dispositions": [{
            "table": "leases", "primary_key": {"lease_id": "lease-1", "path": row["path"]},
            "row_sha256": helper.typed_row_sha256("leases", row), "task_id": "task-1",
            "task_row_sha256": pinned_task_row_sha,
        }],
    }), encoding="utf-8")
    manifest = helper.load_writer_map(manifest_path, source_sha256=source_sha)
    changed_root = tmp_path / "other-root"
    changed_root.mkdir()
    for facts in (
        {"task_id": "task-1", "owner": "changed-owner", "repo_root": str(tmp_path),
         "source_sha256": source_sha, "task_row_sha256": "c" * 64},
        {"task_id": "task-1", "owner": "owner", "repo_root": str(changed_root),
         "source_sha256": source_sha, "task_row_sha256": "c" * 64},
    ):
        with __import__("pytest").raises(ValueError, match="task row changed"):
            helper.transform_writer_row(table="leases", row=row, manifest=manifest,
                                        task_lookup=lambda _task_id, facts=facts: facts,
                                        root_lookup=lambda _root_id: None)


def test_agent_state_legacy_writer_schema_classifies_and_maps_rows(tmp_path: Path, monkeypatch, request) -> None:
    helper = _converter._WRITER_DISPOSITION_API
    source_sha = "a" * 64
    root = str(tmp_path.resolve())
    row = {"lease_id": "lease-1", "tenant": "legacy", "root_id": "root-1",
           "root_path": root, "path": str(tmp_path / "file"), "purpose": "write",
           "created_at": 1.0, "expires_at": 2.0}
    checkpoint = json.dumps({"state_data": {"_agent_task_scope": {"version": 2, "repo_root": root}}})
    task_columns = ["task_id", "owner", "checkpoint"]
    task_values = ("task-1", "actual-owner", checkpoint)
    task_row_sha = _converter._task_row_digest(task_columns, task_values)
    manifest_path = tmp_path / "writer-map.json"
    manifest_path.write_text(json.dumps({
        "schema": helper.WRITER_MAP_SCHEMA, "source_sha256": source_sha,
        "dispositions": [{
            "table": "leases", "primary_key": {"lease_id": row["lease_id"], "path": row["path"]},
            "row_sha256": helper.typed_row_sha256("leases", row), "task_id": "task-1",
            "task_row_sha256": task_row_sha,
        }],
    }), encoding="utf-8")
    target_ddl = {
        "leases": "CREATE TABLE leases (lease_id TEXT NOT NULL, owner TEXT NOT NULL, root_id TEXT NOT NULL, root_path TEXT NOT NULL, path TEXT NOT NULL, purpose TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY(lease_id,path))",
        "lease_waits": "CREATE TABLE lease_waits (owner TEXT NOT NULL, blocked_by TEXT NOT NULL, root_id TEXT NOT NULL, requested_path TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(root_id,owner,blocked_by,requested_path))",
        "agent_tasks_projection": "CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, checkpoint TEXT NOT NULL)",
    }
    monkeypatch.setitem(_converter._STORE_DDL, "agent_state", (target_ddl, ()))
    monkeypatch.setattr(_converter, "_AGENT_ARCHIVE_TABLES", ())
    monkeypatch.setattr(_converter, "_GENERATED_AGENT_HASHES", {})
    monkeypatch.setattr(_converter, "_SOURCE_AGENT_HASHES", {})
    database = sqlite3.connect(":memory:")
    request.addfinalizer(database.close)
    database.execute("PRAGMA user_version=1")
    database.execute("CREATE TABLE leases (lease_id TEXT NOT NULL, tenant TEXT NOT NULL, root_id TEXT NOT NULL, root_path TEXT NOT NULL, path TEXT NOT NULL, purpose TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY(lease_id,path))")
    database.execute("CREATE TABLE lease_waits (tenant TEXT NOT NULL, blocked_by TEXT NOT NULL, root_id TEXT NOT NULL, requested_path TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(root_id,tenant,blocked_by,requested_path))")
    database.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, checkpoint TEXT NOT NULL)")
    database.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?)", tuple(row[column] for column in helper._TABLE_COLUMNS["leases"]))
    database.execute("INSERT INTO agent_tasks_projection VALUES(?,?,?)", task_values)
    pins = {}
    for kind, name, table, sql in database.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('table','index')"):
        if sql is not None:
            pins[(kind, name, table)] = _converter._agent_object_sql_sha256(sql)
    monkeypatch.setattr(_converter, "_SOURCE_AGENT_HASHES", pins)
    monkeypatch.setattr(_converter, "_canonical_foreign_keys", lambda _store, _table: [])

    store, removed, source_tables = _converter._source_store_shape(database)
    assert store == "agent_state"
    assert removed["leases"] == ["tenant"]
    assert removed["lease_waits"] == ["tenant"]
    assert next(item for item in source_tables if item["table"] == "lease_waits")["rows"] == 0
    mapped, proofs = _converter._preflight_writer_rows(database, source_tables, source_sha,
                                                       manifest_path, {})
    assert mapped[("leases", ("lease-1", row["path"]))]["owner"] == "actual-owner"
    assert "tenant" not in mapped[("leases", ("lease-1", row["path"]))]
    assert proofs[0]["task"]["task_row_sha256"] == task_row_sha


def test_json_dispositions_transform_only_exact_registered_provenance_row(tmp_path: Path, request) -> None:
    import hashlib

    raw = '{"tenant_key":"retired","content":"tenant_key is opaque prose"}'
    source_sha = "a" * 64
    manifest = tmp_path / "json-dispositions.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "source_sha256": source_sha,
        "entries": [{
            "store": "agent_state", "table": "agent_memory_records", "column": "provenance",
            "key": "memory-1", "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "operations": [{"op": "remove_json_pointer", "pointer": "/tenant_key"}],
        }],
    }), encoding="utf-8")
    database = sqlite3.connect(":memory:")
    request.addfinalizer(database.close)
    database.execute("CREATE TABLE agent_memory_records(record_id TEXT PRIMARY KEY, provenance TEXT NOT NULL)")
    database.execute("INSERT INTO agent_memory_records VALUES(?, ?)", ("memory-1", raw))
    inventory = [{"table": "agent_memory_records", "columns": ["record_id", "provenance"], "primary_key": ["record_id"]}]

    changes, proofs = _converter._preflight_agent_json(database, inventory, source_sha, manifest)

    converted = changes[("agent_memory_records", ("memory-1",), "provenance")]
    assert json.loads(converted) == {"content": "tenant_key is opaque prose"}
    assert proofs[0]["old_raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert proofs[0]["new_raw_sha256"] == hashlib.sha256(converted.encode("utf-8")).hexdigest()
    assert "tenant_key is opaque prose" in raw


def test_json_disposition_preflight_requires_manifest_for_retired_contract_keys(request) -> None:
    database = sqlite3.connect(":memory:")
    request.addfinalizer(database.close)
    database.execute("CREATE TABLE agent_memory_records(record_id TEXT PRIMARY KEY, provenance TEXT NOT NULL)")
    database.execute("INSERT INTO agent_memory_records VALUES(?, ?)", ("memory-1", '{"tenant":null}'))
    inventory = [{"table": "agent_memory_records", "columns": ["record_id", "provenance"], "primary_key": ["record_id"]}]

    with __import__("pytest").raises(_converter.ConversionError, match="--json-dispositions"):
        _converter._preflight_agent_json(database, inventory, "a" * 64, None)


def test_agent_json_preflight_validates_structured_context_and_receipt_without_scanning_prose() -> None:
    context = json.dumps({"repository_id": "repo-7", "session_id": "session-2"})
    assert not _converter._json_contract_needs_disposition(context, "agent_tasks_projection", "context")
    with __import__("pytest").raises(_converter.ConversionError, match="retired"):
        _converter._json_contract_needs_disposition('{"tenant":null}', "agent_tasks_projection", "context")

    details = json.dumps({
        "summary": "tenant value is project content",
        "_verification_receipt": {
            "schema": "verification_receipt_metadata.v1", "owner": "codex",
            "mutation_generation": 0, "evidence_type": "test",
        },
    })
    assert not _converter._json_contract_needs_disposition(details, "agent_verification_receipts", "details")
    empty_owner = details.replace('"owner": "codex"', '"owner": ""')
    assert not _converter._json_contract_needs_disposition(empty_owner, "agent_verification_receipts", "details")
    invalid = details.replace('"mutation_generation": 0', '"mutation_generation": true')
    with __import__("pytest").raises(_converter.ConversionError, match="noncanonical"):
        _converter._json_contract_needs_disposition(invalid, "agent_verification_receipts", "details")


def test_json_conversion_refuses_overwrite_and_stale_source(tmp_path: Path) -> None:
    source = tmp_path / "settings.json"
    target = tmp_path / "converted.json"
    source.write_text('{"safe": true}', encoding="utf-8")
    with __import__("pytest").raises(_converter.ConversionError, match="source changed"):
        _converter.convert_config(source, target, expected_sha256="0" * 64)
    target.write_text("preserved", encoding="utf-8")
    with __import__("pytest").raises(_converter.ConversionError, match="already exists"):
        _converter.convert_config(source, target)
    assert target.read_text(encoding="utf-8") == "preserved"


def test_sqlite_inventory_is_read_only_and_reports_collisions(tmp_path: Path) -> None:
    source = tmp_path / "state.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE records (tenant TEXT, id TEXT, payload TEXT)")
    connection.executemany("INSERT INTO records VALUES (?, ?, ?)", [("a", "same", "one"), ("b", "same", "one")])
    connection.commit()
    connection.close()
    before = source.read_bytes()

    inventory = _converter.inventory_sqlite(source)

    assert inventory["collision_count"] == 1
    assert inventory["tables"][0]["collisions"][0]["key"] == ["same"]
    assert source.read_bytes() == before
    manifest = tmp_path / "collisions.json"
    manifest.write_text(json.dumps({
        "source_sha256": inventory["source_sha256"],
        "dispositions": [
            {"table": "records", "tenant_column": "tenant", "key": ["same"], "tenant_value": "a", "disposition": "preserve"},
            {"table": "records", "tenant_column": "tenant", "key": ["same"], "tenant_value": "b", "disposition": "preserve"},
        ],
    }), encoding="utf-8")
    _converter.validate_collision_manifest(inventory, manifest)
    manifest.write_text(json.dumps({"source_sha256": inventory["source_sha256"], "dispositions": []}), encoding="utf-8")
    with __import__("pytest").raises(_converter.ConversionError, match="every and only"):
        _converter.validate_collision_manifest(inventory, manifest)


def test_supported_request_journal_conversion_preserves_source_and_rows(tmp_path: Path) -> None:
    source = tmp_path / "state.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("""CREATE TABLE requests (
        tenant TEXT, request_id TEXT PRIMARY KEY, identity TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
        payload_fingerprint TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, detail TEXT NOT NULL DEFAULT '',
        status_code INTEGER NOT NULL DEFAULT 0, response_json TEXT NOT NULL DEFAULT '')""")
    connection.execute("CREATE INDEX idx_recovery_state ON requests(state, updated_at)")
    connection.execute("CREATE INDEX idx_recovery_updated ON requests(updated_at DESC)")
    connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("old-owner", "req-1", "old-identity", "search", "fingerprint", "complete", 10.0, 11.0, "detail", 200, "{}"))
    connection.commit()
    connection.close()
    before = source.read_bytes()
    target = tmp_path / "converted.sqlite"

    result = _converter.convert_sqlite_store(source, target)

    assert result["store"] == "request_journal"
    assert target.exists()
    assert source.read_bytes() == before
    converted = sqlite3.connect(target)
    try:
        assert [row[1] for row in converted.execute("PRAGMA table_info(requests)")] == [
            "request_id", "action", "payload_fingerprint", "state", "created_at",
            "updated_at", "detail", "status_code", "response_json",
        ]
        assert converted.execute("SELECT request_id, action, response_json FROM requests").fetchone() == ("req-1", "search", "{}")
    finally:
        converted.close()
    provenance = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
    assert provenance["removed_retired_fields"][0]["removed_value"] == "old-owner"
    assert any(item["removed_field"] == "identity" and item["removed_value"] == "old-identity"
               for item in provenance["removed_retired_fields"])


def test_toml_config_converts_exact_retired_paths_and_keeps_scope_and_tokens(tmp_path: Path) -> None:
    source = tmp_path / "settings.toml"
    target = tmp_path / "converted.toml"
    source.write_text(
        '[rag]\nscope = "tenant"\nchunk_chars = 4000\n\n'
        '[security]\napi_token = "keep-token"\napi_token_tenant = "old-tenant"\n'
        'api_token_principal = "private-principal"\ntenant_derivation_key = "secret-key"\n'
        'users = [{ name = "operator", token = "keep-in-provenance" }]\n'
        '[scheduler]\nmax_queued_per_tenant = 5\nmax_queued = 20\n\n'
        '[browser_bridge]\ntenant = "old"\nallowed_origins = ["http://localhost"]\n\n'
        '[repository]\nscope = "worktree"\n',
        encoding="utf-8",
    )

    result = _converter.convert_toml_config(source, target)

    converted = target.read_text(encoding="utf-8")
    assert 'api_token = "keep-token"' in converted
    assert 'chunk_chars = 4000' in converted
    assert 'max_queued = 20' in converted
    assert 'scope = "worktree"' in converted
    assert "max_queued_per_tenant" not in converted
    assert "api_token_tenant" not in converted
    assert "scope = \"tenant\"" not in converted
    assert "users =" not in converted
    provenance = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
    assert "secret-key" in json.dumps(provenance)
    assert "keep-token" not in json.dumps(result)


def test_toml_removes_users_table_block_and_preserves_other_sections(tmp_path: Path) -> None:
    source = tmp_path / "settings.toml"
    target = tmp_path / "converted.toml"
    source.write_text(
        '# keep this leading comment\n[security]\napi_token = "keep"\n\n'
        '[security.users]\noperator = "alice"\n# private user note\n\n'
        '[scheduler]\nmax_queued = 20\n', encoding="utf-8")

    result = _converter.convert_toml_config(source, target)

    output = target.read_text(encoding="utf-8")
    assert "# keep this leading comment" in output
    assert 'api_token = "keep"' in output
    assert "[security.users]" not in output
    assert "operator =" not in output
    assert "[scheduler]" in output and "max_queued = 20" in output
    provenance = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
    users = next(item for item in provenance["removed_fields"] if item["path"] == "$.security.users")
    assert users["value"] == {"operator": "alice"}


def test_provenance_publish_failure_preserves_published_target(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "settings.json"
    target = tmp_path / "converted.json"
    source.write_text('{"security":{"api_token_tenant":"old"}}', encoding="utf-8")
    publish = _converter._publish_new_file
    calls = 0

    def fail_second_publish(temporary: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected provenance failure")
        publish(temporary, destination)

    monkeypatch.setattr(_converter, "_publish_new_file", fail_second_publish)
    with __import__("pytest").raises(_converter.ConversionError, match="target published"):
        _converter.convert_config(source, target)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"security": {}}


def test_artifact_store_conversion_preserves_content_and_paging(tmp_path: Path) -> None:
    source = tmp_path / "artifacts.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("""CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL,
    tenant TEXT NOT NULL, tenant_identity TEXT, kind TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '', mime_type TEXT, encoding TEXT, blob BLOB,
    size_bytes INTEGER, checksum TEXT, identity_json TEXT
)""")
    connection.execute("CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO artifact_schema_meta VALUES ('tenant_storage', 'sha256-v1')")
    connection.execute("CREATE INDEX idx_artifacts_created ON artifacts(created_at)")
    connection.execute("""CREATE TABLE artifact_paging_metadata (
                artifact_id TEXT PRIMARY KEY,
                char_count INTEGER NOT NULL,
                section_names TEXT NOT NULL,
                page_text TEXT,
                nul_mask BLOB
            )""")
    connection.execute("INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("artifact-1", 1.0, "former", "a" * 64, "report", "text", "text/plain", "utf-8", b"\x00data", 5, "sum", "{}"))
    connection.execute("INSERT INTO artifact_paging_metadata VALUES (?, ?, ?, ?, ?)", (
        "artifact-1", 4, json.dumps({"names": ["heading"], "truncated": True}), "text", None))
    connection.commit()
    connection.close()
    source_before = source.read_bytes()
    target = tmp_path / "artifacts-converted.sqlite"

    result = _converter.convert_sqlite_store(source, target)

    assert result["store"] == "artifacts"
    assert source.read_bytes() == source_before
    converted = sqlite3.connect(target)
    try:
        assert converted.execute("SELECT artifact_id, text, blob FROM artifacts").fetchone() == ("artifact-1", "text", b"\x00data")
        assert converted.execute("SELECT artifact_id, page_text FROM artifact_paging_metadata").fetchone() == ("artifact-1", "text")
        metadata, checksum = converted.execute(
            "SELECT section_json,section_checksum FROM artifact_paging_metadata").fetchone()
        assert json.loads(metadata) == {
            "artifact_id": "artifact-1", "names": ["heading"], "truncated": True}
        assert checksum == hashlib.sha256(metadata.encode("utf-8")).hexdigest()
        assert "tenant" not in {row[1] for row in converted.execute("PRAGMA table_info(artifacts)")}
    finally:
        converted.close()
    provenance = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
    assert provenance["removed_artifact_schema_markers"] == [
        {"table": "artifact_schema_meta", "key": "tenant_storage", "value": "sha256-v1"}]

def test_workspace_memo_conversion_preserves_project_scopes_and_versions(tmp_path: Path) -> None:
    source = tmp_path / "memos.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("""CREATE TABLE memos (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1, tenant TEXT NOT NULL, PRIMARY KEY(tenant, workspace, memo_key))""")
    connection.execute("""CREATE TABLE memo_versions (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, version INTEGER NOT NULL, tenant TEXT NOT NULL, PRIMARY KEY(tenant, workspace, memo_key))""")
    connection.execute("CREATE INDEX idx_memos_expiry ON memos(expires_at)")
    connection.execute("INSERT INTO memos VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("repo-a", "key", "value", "{}", 1.0, 99.0, 4, "former"))
    connection.execute("INSERT INTO memo_versions VALUES (?, ?, ?, ?)", ("repo-a", "key", 4, "former"))
    connection.commit()
    connection.close()
    target = tmp_path / "memos-converted.sqlite"

    result = _converter.convert_sqlite_store(source, target)

    assert result["store"] == "workspace_memos"
    converted = sqlite3.connect(target)
    try:
        assert converted.execute("SELECT workspace, memo_key, value, version FROM memos").fetchone() == ("repo-a", "key", "value", 4)
        assert converted.execute("SELECT workspace, memo_key, version FROM memo_versions").fetchone() == ("repo-a", "key", 4)
    finally:
        converted.close()


def test_legacy_memory_context_requires_explicit_conversion_and_coordination_proof() -> None:
    old = {"schema_version": 1, "instruction": "keep", "items": [{"memory_id": "m"}],
           "warnings": [], "estimated_tokens": 2}
    legacy = {"task_id": "task-1", "state_data": {"memory_context": old}}
    assert _converter._json_contract_needs_disposition(
        json.dumps(legacy), "agent_tasks_projection", "checkpoint") is True

    root = str(Path.cwd().resolve())
    current_context = {"root": root, "coordination_id": "coord-1", "task_id": "task-1",
                       "session_id": "session-1", "clone_id": "", "worktree_id": "", "branch": "main"}
    current = {"task_id": "task-1", "context": {"repository_id": "repo-1", "task_id": "task-1", "session_id": "session-1",
               "clone_id": "", "worktree_id": "", "branch": "main"},
               "coordination_id": "coord-1", "state_data": {"_agent_task_scope": {"version": 2, "repo_root": root},
               "memory_context": {"schema_version": 2, "context": current_context, "instruction": "i",
                                  "items": [], "warnings": [], "estimated_tokens": 0}}}
    raw = json.dumps(current)
    assert _converter._json_contract_needs_disposition(raw, "agent_tasks_projection", "checkpoint") is False
    _converter._validate_memory_context_identity(raw, "agent_tasks_projection", "task-1")

    del current["coordination_id"]
    with __import__("pytest").raises(_converter.ConversionError, match="coordination_id proof"):
        _converter._validate_memory_context_identity(json.dumps(current), "agent_tasks_projection", "task-1")


def test_integrated_memory_archive_requires_manifest_and_preserves_full_snapshot(tmp_path: Path, request) -> None:
    memory = {"schema_version": 1, "tenant_key": "retired", "instruction": "full instruction",
              "items": [{"memory_id": "m-1", "payload": {"count": 5, "valid": False}}],
              "warnings": [{"code": "warning", "detail": "retain"}], "estimated_tokens": 31}
    checkpoint = {"phase": "active", "next_action": "continue", "affected_paths": [],
                  "evidence_ids": [], "blockers": [],
                  "state_data": {"_agent_task_scope": {"version": 2, "repo_root": str(tmp_path.resolve())},
                                 "memory_context": memory}}
    raw = json.dumps(checkpoint, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    connection = sqlite3.connect(":memory:")
    request.addfinalizer(connection.close)
    connection.execute("CREATE TABLE agent_tasks_projection(task_id TEXT, checkpoint TEXT)")
    connection.execute("INSERT INTO agent_tasks_projection VALUES (?, ?)", ("task-1", raw))
    table_contract = [{"table": "agent_tasks_projection", "columns": ["task_id", "checkpoint"]}]
    with __import__("pytest").raises(_converter.ConversionError, match="--json-dispositions"):
        _converter._preflight_agent_json(connection, table_contract, "a" * 64, None)

    manifest_path = tmp_path / "memory-archive.json"
    manifest = {"version": 1, "source_sha256": "a" * 64, "entries": [{
        "store": "agent_state", "table": "agent_tasks_projection", "column": "checkpoint",
        "key": "task-1", "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "operations": [{"op": "archive_memory_context", "pointer": "/state_data/memory_context",
                        "expected_old": memory, "reason": "source has no coordination_id proof"}],
    }]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    changes, proofs = _converter._preflight_agent_json(
        connection, table_contract, "a" * 64, manifest_path)
    assert changes[("agent_tasks_projection", ("task-1",), "checkpoint")]
    archived = next(proof for proof in proofs if proof.get("archive_reason"))
    assert archived["archive_reason"] == "source has no coordination_id proof"
    assert archived["removed_values"] == ({"pointer": "/state_data/memory_context", "value": memory},)
    connection.close()


def test_empty_v2_warning_context_is_allowed_only_without_items(tmp_path: Path) -> None:
    envelope = {"phase": "active", "next_action": "continue", "affected_paths": [],
                "evidence_ids": [], "blockers": [], "state_data": {
                    "_agent_task_scope": {"version": 2, "repo_root": str(tmp_path.resolve())},
                    "memory_context": {"schema_version": 2, "context": {}, "instruction": "unavailable",
                                       "items": [], "warnings": [{"code": "memory_context_unavailable"}],
                                       "estimated_tokens": 0}}}
    raw = json.dumps(envelope)
    assert _converter._json_contract_needs_disposition(raw, "agent_tasks_projection", "checkpoint") is False
    _converter._validate_memory_context_identity(raw, "agent_tasks_projection", "task-1")

    envelope["state_data"]["memory_context"]["items"] = [{"memory_id": "unexpected"}]
    with __import__("pytest").raises(_converter.ConversionError, match="current v2 envelope"):
        _converter._json_contract_needs_disposition(json.dumps(envelope), "agent_tasks_projection", "checkpoint")


def test_task_scope_v2_requires_exact_integer_and_exact_fields() -> None:
    root = str(Path.cwd().resolve())
    for version in (2.0, True):
        raw = json.dumps({"state_data": {"_agent_task_scope": {"version": version, "repo_root": root}}})
        with __import__("pytest").raises(_converter.ConversionError, match="version is malformed"):
            _converter._json_contract_needs_disposition(raw, "agent_tasks_projection", "checkpoint")

    raw = json.dumps({"state_data": {"_agent_task_scope": {
        "version": 2, "repo_root": root, "unexpected": "must not be copied"}}})
    with __import__("pytest").raises(_converter.ConversionError, match="unsupported fields"):
        _converter._json_contract_needs_disposition(raw, "agent_tasks_projection", "checkpoint")


def test_historical_store_registry_is_finite_and_source_fingerprinted() -> None:
    contracts = _converter._HISTORICAL_STORE_CONTRACTS
    hashes = contracts["HISTORICAL_SOURCE_OBJECT_HASHES"]
    for store in ("artifacts", "async_jobs", "work_orchestrator", "telemetry"):
        store_hashes = {identity: value for identity, value in hashes.items() if identity[0] == store}
        assert store_hashes
        assert all(len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)
                   for value in store_hashes.values())
    assert contracts["HISTORICAL_INDEX_ACTIONS"]["async_jobs"]["idx_async_jobs_request_id"][0] == "map"
    assert contracts["HISTORICAL_INDEX_ACTIONS"]["work_orchestrator"]["idx_work_orders_tenant_updated"] == (
        "map", "idx_work_orders_updated", "tenant")


def test_canonical_store_shapes_do_not_require_historical_pins() -> None:
    for store in ("debug_traces", "workspace_memos", "work_fencing", "async_jobs"):
        database = sqlite3.connect(":memory:")
        try:
            tables, indexes = _converter._STORE_DDL[store]
            for ddl in tables.values():
                database.execute(ddl)
            for ddl in indexes:
                database.execute(ddl)
            assert _converter._source_store_shape(database)[0] == store
        finally:
            database.close()


def test_historical_index_predicate_tampering_fails_exact_source_pin(monkeypatch) -> None:
    database = sqlite3.connect(":memory:")
    try:
        tables, indexes = _converter._STORE_DDL["work_orchestrator"]
        for ddl in tables.values():
            database.execute(ddl)
        for ddl in indexes:
            database.execute(ddl)
        database.execute("ALTER TABLE work_orders ADD COLUMN tenant TEXT")
        database.execute("DROP INDEX idx_work_orders_updated")
        database.execute(
            "CREATE INDEX idx_work_orders_tenant_updated "
            "ON work_orders(tenant, updated_at DESC)")
        hashes = _converter._HISTORICAL_STORE_CONTRACTS["HISTORICAL_SOURCE_OBJECT_HASHES"]
        for kind, name, sql in database.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "AND type IN ('table','index')"):
            monkeypatch.setitem(hashes, ("work_orchestrator", kind, name),
                                _converter._agent_object_sql_sha256(sql))
        database.execute("DROP INDEX idx_work_orders_tenant_updated")
        database.execute(
            "CREATE INDEX idx_work_orders_tenant_updated "
            "ON work_orders(tenant, updated_at DESC) WHERE tenant IS NOT NULL")
        with __import__("pytest").raises(_converter.ConversionError, match="source object fingerprints"):
            _converter._source_store_shape(database)
    finally:
        database.close()


def test_telemetry_autoincrement_high_water_survives_deleted_rows(tmp_path: Path) -> None:
    source = tmp_path / "telemetry.sqlite3"
    original = sqlite3.connect(source)
    try:
        tables, indexes = _converter._STORE_DDL["telemetry"]
        for ddl in tables.values():
            original.execute(ddl)
        for ddl in indexes:
            original.execute(ddl)
        original.execute("INSERT INTO events(id,created_at) VALUES(9000,1.0)")
        original.execute("DELETE FROM events WHERE id=9000")
        original.commit()
    finally:
        original.close()

    target = tmp_path / "telemetry-converted.sqlite3"
    result = _converter.convert_sqlite_store(source, target)
    assert result["store"] == "telemetry"
    converted = sqlite3.connect(target)
    try:
        assert converted.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone() == (9000,)
        converted.execute("INSERT INTO events(created_at) VALUES(2.0)")
        assert converted.execute("SELECT last_insert_rowid()").fetchone() == (9001,)
    finally:
        converted.close()


def test_historical_artifact_section_metadata_preserves_full_value_and_truncation() -> None:
    database = sqlite3.connect(":memory:")
    try:
        database.execute("CREATE TABLE artifact_paging_metadata(artifact_id TEXT PRIMARY KEY,char_count INTEGER NOT NULL,section_names TEXT NOT NULL,page_text TEXT,nul_mask BLOB)")
        raw = json.dumps({"names": ["json:κ", "heading"], "truncated": True}, ensure_ascii=False)
        database.execute("INSERT INTO artifact_paging_metadata VALUES(?,?,?,?,?)",
                         ("artifact-1", 9, raw, "page", b"\x01"))
        rows = [{"table": "artifact_paging_metadata", "columns": [
            "artifact_id", "char_count", "section_names", "page_text", "nul_mask"]}]

        replacements, provenance, expected_hashes = _converter._historical_store_row_transforms(
            database, "artifacts", rows)

        mapped = replacements[("artifact_paging_metadata", ("artifact-1",))]
        assert json.loads(mapped["section_json"]) == {
            "artifact_id": "artifact-1", "names": ["json:κ", "heading"], "truncated": True}
        assert mapped["section_checksum"] == hashlib.sha256(mapped["section_json"].encode("utf-8")).hexdigest()
        assert provenance[0]["removed_value"] == {"type": "text", "value": raw}
        assert provenance[0]["source_row_sha256"]
        assert provenance[0]["target_section_json_sha256"] == hashlib.sha256(mapped["section_json"].encode("utf-8")).hexdigest()
        assert len(expected_hashes["artifact_paging_metadata"]) == 64
    finally:
        database.close()


def test_historical_artifact_section_metadata_refuses_malformed_or_missing_truncation() -> None:
    for raw in ('{"names":[],"truncated":"false"}', '{"names":[]}'):
        database = sqlite3.connect(":memory:")
        try:
            database.execute("CREATE TABLE artifact_paging_metadata(artifact_id TEXT PRIMARY KEY,char_count INTEGER NOT NULL,section_names TEXT NOT NULL,page_text TEXT,nul_mask BLOB)")
            database.execute("INSERT INTO artifact_paging_metadata VALUES(?,?,?,?,?)",
                             ("artifact-1", 0, raw, None, None))
            rows = [{"table": "artifact_paging_metadata", "columns": [
                "artifact_id", "char_count", "section_names", "page_text", "nul_mask"]}]
            with __import__("pytest").raises(_converter.ConversionError, match="unsupported historical section_names"):
                _converter._historical_store_row_transforms(database, "artifacts", rows)
        finally:
            database.close()
