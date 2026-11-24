from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.state_lifecycle import CURRENT_STATE_VERSION, read_state_version, write_state_version
from tools.state_migrations import StateMigrationError, run_state_migrations


def _state_with_v6_agent_schema(root: Path, *, old_embeddings: bool = False, version: int | None = 6) -> Path:
    root.mkdir()
    if version is not None:
        write_state_version(root, version=version)
    database = root / "agent_state.sqlite"
    with closing(sqlite3.connect(database)) as con:
        con.execute("PRAGMA user_version=1")
        con.execute(
            """CREATE TABLE agent_entity_relations (
                relation_id TEXT PRIMARY KEY,
                source_entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_entity TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        con.execute("CREATE INDEX idx_entity_rel_source ON agent_entity_relations(source_entity)")
        con.execute("CREATE INDEX idx_entity_rel_target ON agent_entity_relations(target_entity)")
        con.execute("CREATE INDEX idx_entity_rel_type ON agent_entity_relations(relation)")
        con.execute(
            "INSERT INTO agent_entity_relations VALUES(?,?,?,?,?,?,?,?)",
            (
                "relation-1", "source", "links", "target", 0.75,
                json.dumps({"root": "C:/repo", "provenance": {"repository_id": "repo-1"}}),
                1.0, 2.0,
            ),
        )
        if old_embeddings:
            con.execute(
                """CREATE TABLE agent_memory_embeddings (
                    record_id TEXT PRIMARY KEY, embedding TEXT NOT NULL, created_at REAL NOT NULL
                )"""
            )
            con.execute("INSERT INTO agent_memory_embeddings VALUES('memory-1','[0.1,0.2]',3.0)")
        else:
            con.execute(
                """CREATE TABLE agent_memory_embeddings (
                    record_id TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    embedding_space_id TEXT NOT NULL DEFAULT '',
                    model_name TEXT NOT NULL DEFAULT '',
                    dimension INTEGER NOT NULL DEFAULT 0
                )"""
            )
        con.commit()
    return database


def _create_v5_board_database(state: Path) -> Path:
    database = state / "agent_board.sqlite"
    with closing(sqlite3.connect(database)) as con:
        con.executescript("""
            CREATE TABLE agent_board_items (
                item_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium', labels_json TEXT NOT NULL DEFAULT '[]',
                assignee TEXT NOT NULL DEFAULT '', milestone TEXT NOT NULL DEFAULT '',
                linked_task_id TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE agent_milestones (
                name TEXT PRIMARY KEY, target_date TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
            );
            INSERT INTO agent_board_items VALUES
                ('item-1','Ship cleanup','active','medium','[]','','','','{}',1.0,2.0);
        """)
    return database


def _create_v8_endpoint_stats_database(state: Path, *, unknown_legacy_schema: bool = False) -> Path:
    database = state / "endpoint_stats.sqlite3"
    columns = [
        "scope_root TEXT NOT NULL DEFAULT ''",
        "item_type TEXT NOT NULL",
        "item_name TEXT NOT NULL",
        "calls INTEGER NOT NULL DEFAULT 0",
        "success_calls INTEGER NOT NULL DEFAULT 0",
        "fail_calls INTEGER NOT NULL DEFAULT 0",
        *(f"b{i} INTEGER NOT NULL DEFAULT 0" for i in range(14)),
        "last_used REAL NOT NULL DEFAULT 0",
        "PRIMARY KEY(scope_root, item_type, item_name)",
    ]
    with closing(sqlite3.connect(database)) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE endpoint_stats (" + ", ".join(columns) + ")")
        if not unknown_legacy_schema:
            con.execute("CREATE TABLE endpoint_stats_exact (" + ", ".join(columns) + ")")
            con.execute(
                "INSERT INTO endpoint_stats(scope_root,item_type,item_name,calls,success_calls,fail_calls,b0,b1,last_used) "
                "VALUES('shared','mcp','legacy-tool',3,2,1,2,1,123.0)"
            )
            con.execute(
                "INSERT INTO endpoint_stats_exact(scope_root,item_type,item_name,calls,success_calls,b0,last_used) "
                "VALUES('root:exact','mcp','current-tool',1,1,1,456.0)"
            )
            con.execute("CREATE INDEX idx_ep_stats_root ON endpoint_stats(scope_root)")
            con.execute("CREATE INDEX idx_ep_stats_item ON endpoint_stats(item_type, item_name)")
        else:
            con.execute("DROP TABLE endpoint_stats")
            con.execute("CREATE TABLE endpoint_stats(scope_root TEXT, item_type TEXT, item_name TEXT)")
            con.execute("INSERT INTO endpoint_stats VALUES('shared','mcp','legacy-tool')")
        con.commit()
    return database


def _create_incidents_table(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE agent_incidents (
        incident_id TEXT PRIMARY KEY, operation_class TEXT NOT NULL, error_class TEXT NOT NULL,
        signature_hash TEXT NOT NULL, redacted_message TEXT NOT NULL, state_revision TEXT NOT NULL,
        attempts INTEGER NOT NULL, evidence_ids TEXT NOT NULL, root_cause TEXT, verified_fix TEXT,
        confidence REAL NOT NULL, resolved INTEGER NOT NULL, created_at REAL NOT NULL,
        updated_at REAL NOT NULL, expires_at REAL, affected_paths TEXT NOT NULL DEFAULT '[]',
        ignored INTEGER NOT NULL DEFAULT 0, repository_key TEXT NOT NULL DEFAULT ''
    )""")


def test_v10_to_v11_normalizes_incident_placeholder(tmp_path: Path):
    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state)
    run_state_migrations(state, target_version=10)
    with closing(sqlite3.connect(database)) as con:
        _create_incidents_table(con)
        con.executemany(
            "INSERT INTO agent_incidents (incident_id,operation_class,error_class,signature_hash,"
            "redacted_message,state_revision,attempts,evidence_ids,root_cause,verified_fix,confidence,"
            "resolved,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("old", "command", "failure", "hash1", "message", "rev", 2, "[]", "cause", " ReSoLvEd ", 1.0, 1, 1.0, 2.0),
                ("open", "command", "failure", "hash2", "message", "rev", 1, "[]", None, None, 0.0, 0, 1.0, 2.0),
            ],
        )
        con.commit()

    result = run_state_migrations(state)

    assert result["status"] == "migrated"
    assert read_state_version(state) == 11
    with closing(sqlite3.connect(database)) as con:
        assert con.execute(
            "SELECT incident_id,verified_fix,resolved,root_cause FROM agent_incidents ORDER BY incident_id"
        ).fetchall() == [("old", None, 0, "cause"), ("open", None, 0, None)]


def test_v10_to_v11_rejects_unknown_incident_schema_with_backup(tmp_path: Path):
    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state)
    run_state_migrations(state, target_version=10)
    with closing(sqlite3.connect(database)) as con:
        con.execute("CREATE TABLE agent_incidents (incident_id TEXT, verified_fix TEXT)")
        con.execute("INSERT INTO agent_incidents VALUES ('old','resolved')")
        con.commit()
    before = database.read_bytes()

    with pytest.raises(StateMigrationError) as failure:
        run_state_migrations(state)

    assert failure.value.backup_path.is_dir()
    assert read_state_version(state) == 10
    assert database.read_bytes() == before


def test_v8_to_v9_migration_archives_basename_stats_and_runtime_uses_exact_table_only(tmp_path: Path):
    from local_ai_hub.endpoint_stats import EndpointStatsStore

    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=8)
    database = _create_v8_endpoint_stats_database(state)

    result = run_state_migrations(state, target_version=9)

    assert result["status"] == "migrated"
    assert read_state_version(state) == 9
    with closing(sqlite3.connect(database)) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "endpoint_stats" not in tables
        assert "endpoint_stats_basename_archive" in tables
        assert con.execute(
            "SELECT scope_root,item_type,item_name,calls,success_calls,fail_calls,b0,b1,last_used "
            "FROM endpoint_stats_basename_archive"
        ).fetchone() == ("shared", "mcp", "legacy-tool", 3, 2, 1, 2, 1, 123.0)
        assert con.execute(
            "SELECT scope_root,item_type,item_name,calls,success_calls,b0,last_used FROM endpoint_stats_exact"
        ).fetchone() == ("root:exact", "mcp", "current-tool", 1, 1, 1, 456.0)
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    store = EndpointStatsStore(state)
    store.close()
    with closing(sqlite3.connect(database)) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "endpoint_stats" not in tables


def test_v8_to_v9_unknown_endpoint_stats_schema_preserves_live_state_and_backup(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=8)
    database = _create_v8_endpoint_stats_database(state, unknown_legacy_schema=True)
    before = database.read_bytes()

    with pytest.raises(StateMigrationError) as failure:
        run_state_migrations(state)

    assert failure.value.backup_path.is_dir()
    assert database.read_bytes() == before
    with closing(sqlite3.connect(database)) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "endpoint_stats" in tables
    assert "endpoint_stats_basename_archive" not in tables


def _laya_pre_runtime_metadata() -> dict[str, object]:
    return {
        "decision_id": "decision-1", "success": True, "mode": "advisory", "status": "success",
        "category": "retrieval_strategy", "repository_id": "repo-1", "task_id": "task-1",
        "session_id": "session-1", "provider_label": "generic_mcp", "suggestion": "local",
        "reason_codes": [], "evidence_ids": [], "model_estimate": None, "uncertainty": None,
        "execution_verification": None,
    }


def _create_telemetry_database(state: Path, *, legacy: bool = True, bad_schema: bool = False) -> Path:
    database = state / "telemetry.sqlite3"
    with closing(sqlite3.connect(database)) as con:
        if bad_schema:
            con.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, metrics_json TEXT NOT NULL)")
            return database
        con.execute(
            "CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, "
            "name TEXT NOT NULL, metrics_json TEXT NOT NULL)"
        )
        metadata = _laya_pre_runtime_metadata()
        if not legacy:
            metadata.update({
                "runtime_latency_ms": 12.0, "inference_latency_ms": 8.0, "queue_wait_ms": 1.0,
                "backend": "onnx", "fallback_used": False, "fallback_reason": None,
            })
        con.execute(
            "INSERT INTO snapshots(created_at,name,metrics_json) VALUES(1.0,'laya_decision',?)",
            (json.dumps(metadata),),
        )
        con.commit()
    return database


def test_v9_to_v10_migrates_exact_legacy_laya_snapshot_and_preserves_values(tmp_path: Path):
    state = tmp_path / "state"
    _state_with_v6_agent_schema(state)
    # Bring the fixture to v9 first, then add an old-format telemetry record.
    run_state_migrations(state, target_version=9)
    database = _create_telemetry_database(state)

    result = run_state_migrations(state)

    assert result["status"] == "migrated"
    assert read_state_version(state) == 11
    with closing(sqlite3.connect(database)) as con:
        stored = json.loads(con.execute("SELECT metrics_json FROM snapshots WHERE name='laya_decision'").fetchone()[0])
    assert stored == {
        **_laya_pre_runtime_metadata(), "runtime_latency_ms": None, "inference_latency_ms": None,
        "queue_wait_ms": None, "backend": None, "fallback_used": None, "fallback_reason": None,
    }


def test_v9_to_v10_unsupported_snapshot_schema_preserves_state_and_backup(tmp_path: Path):
    state = tmp_path / "state"
    _state_with_v6_agent_schema(state)
    run_state_migrations(state, target_version=9)
    database = _create_telemetry_database(state, bad_schema=True)
    before = database.read_bytes()

    with pytest.raises(StateMigrationError) as failure:
        run_state_migrations(state)

    assert failure.value.backup_path.is_dir()
    assert read_state_version(state) == 9
    assert database.read_bytes() == before


def test_v9_to_v10_preserves_ambiguous_duplicate_key_record(tmp_path: Path):
    state = tmp_path / "state"
    _state_with_v6_agent_schema(state)
    run_state_migrations(state, target_version=9)
    database = _create_telemetry_database(state)
    with closing(sqlite3.connect(database)) as con:
        raw = con.execute("SELECT metrics_json FROM snapshots WHERE name='laya_decision'").fetchone()[0]
        ambiguous = raw.replace('"decision_id": "decision-1"', '"decision_id": "shadowed", "decision_id": "decision-1"')
        con.execute("UPDATE snapshots SET metrics_json=? WHERE name='laya_decision'", (ambiguous,))
        con.commit()

    run_state_migrations(state)

    with closing(sqlite3.connect(database)) as con:
        stored = con.execute("SELECT metrics_json FROM snapshots WHERE name='laya_decision'").fetchone()[0]
    assert stored == ambiguous


def test_v6_to_v7_migration_converts_exact_agent_schema_and_preserves_rows(tmp_path: Path):
    database = _state_with_v6_agent_schema(tmp_path / "state")

    result = run_state_migrations(tmp_path / "state")

    assert CURRENT_STATE_VERSION == 11
    assert result["status"] == "migrated"
    assert read_state_version(tmp_path / "state") == 11
    with closing(sqlite3.connect(database)) as con:
        relation = con.execute(
            "SELECT relation_id,source_entity,relation,target_entity,weight,metadata,created_at,updated_at,repository_id "
            "FROM agent_entity_relations"
        ).fetchone()
        assert relation == (
            "relation-1", "source", "links", "target", 0.75,
            json.dumps({"root": "C:/repo", "provenance": {"repository_id": "repo-1"}}),
            1.0, 2.0, "",
        )
        assert con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_entity_rel_%' ORDER BY name").fetchall() == [
            ("idx_entity_rel_source",), ("idx_entity_rel_target",), ("idx_entity_rel_type",),
        ]
        assert [row[1] for row in con.execute("PRAGMA table_info(agent_memory_embeddings)")] == [
            "record_id", "embedding", "created_at", "embedding_space_id", "model_name", "dimension",
        ]


def test_v6_to_v7_migration_upgrades_exact_older_embedding_table(tmp_path: Path):
    database = _state_with_v6_agent_schema(tmp_path / "state", old_embeddings=True)

    run_state_migrations(tmp_path / "state")

    with closing(sqlite3.connect(database)) as con:
        assert con.execute(
            "SELECT record_id,embedding,created_at,embedding_space_id,model_name,dimension "
            "FROM agent_memory_embeddings"
        ).fetchone() == ("memory-1", "[0.1,0.2]", 3.0, "", "", 0)


def test_v6_to_v7_migration_is_idempotent_for_canonical_agent_schema(tmp_path: Path):
    database = _state_with_v6_agent_schema(tmp_path / "state")
    with closing(sqlite3.connect(database)) as con:
        con.execute("ALTER TABLE agent_entity_relations ADD COLUMN repository_id TEXT NOT NULL DEFAULT ''")
        con.commit()

    result = run_state_migrations(tmp_path / "state")

    assert result["status"] == "migrated"
    assert read_state_version(tmp_path / "state") == 11
    with closing(sqlite3.connect(database)) as con:
        assert con.execute("SELECT repository_id FROM agent_entity_relations WHERE relation_id='relation-1'").fetchone() == ("",)


def test_v6_to_v7_migration_rejects_unknown_agent_schema_without_mutating_source(tmp_path: Path):
    database = _state_with_v6_agent_schema(tmp_path / "state")
    with closing(sqlite3.connect(database)) as con:
        con.execute("ALTER TABLE agent_entity_relations ADD COLUMN retired_tenant TEXT")
        con.commit()
    original = database.read_bytes()

    with pytest.raises(StateMigrationError, match="unsupported agent_entity_relations schema"):
        run_state_migrations(tmp_path / "state")

    assert database.read_bytes() == original
    assert read_state_version(tmp_path / "state") == 6


def test_unversioned_v5_state_is_recognized_and_migrated_through_registered_chain(tmp_path: Path):
    from local_ai_hub.legacy_board_archive import ARCHIVE_NAME, read_legacy_board_archive
    from tools.state_migrations import inspect_state_migration_path

    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state, old_embeddings=True, version=None)
    _create_v5_board_database(state)

    plan = inspect_state_migration_path(state)
    result = run_state_migrations(state)

    assert plan == {"status": "migratable", "version": 6, "backups": [], "migration_count": 5}
    assert result["status"] == "migrated"
    assert read_state_version(state) == 11
    assert not (state / "agent_board.sqlite").exists()
    assert read_legacy_board_archive(state) == [{
        "item_id": "item-1", "title": "Ship cleanup", "status": "active", "priority": "medium",
        "assignee": "", "milestone": "", "linked_task_id": "", "created_at": 1.0,
        "updated_at": 2.0, "labels": [], "details": {},
    }]
    assert (state / ARCHIVE_NAME).is_file()
    with closing(sqlite3.connect(database)) as con:
        assert con.execute("SELECT repository_id FROM agent_entity_relations WHERE relation_id='relation-1'").fetchone() == ("",)


def test_unversioned_state_with_retired_memory_tenant_fails_before_migration(tmp_path: Path):
    from tools.state_migrations import inspect_state_migration_path

    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state, old_embeddings=True, version=None)
    with closing(sqlite3.connect(database)) as con:
        con.execute("CREATE TABLE agent_memory_records (record_id TEXT, provenance TEXT)")
        con.execute("INSERT INTO agent_memory_records VALUES ('memory-1', '{\"tenant_key\":\"old\"}')")
        con.commit()
    _create_v5_board_database(state)
    original = database.read_bytes()

    with pytest.raises(RuntimeError, match="retired tenant identity"):
        inspect_state_migration_path(state)

    assert database.read_bytes() == original
    assert not (state / "state_version.json").exists()
    assert not list(tmp_path.glob("state.backup-v*"))


def test_unversioned_state_with_unrecognized_core_schema_is_not_guessed(tmp_path: Path):
    from tools.state_migrations import inspect_state_migration_path

    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state, version=None)
    _create_v5_board_database(state)
    original = database.read_bytes()

    with pytest.raises(RuntimeError, match="unsupported data"):
        inspect_state_migration_path(state)

    assert database.read_bytes() == original
    assert not (state / "state_version.json").exists()
    assert not list(tmp_path.glob("state.backup-v*"))


def test_unversioned_v5_with_unknown_board_layout_preserves_live_state_and_backup(tmp_path: Path):
    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state, old_embeddings=True, version=None)
    board = state / "agent_board.sqlite"
    with closing(sqlite3.connect(board)) as con:
        con.execute("CREATE TABLE unknown_board_rows (value TEXT)")
        con.commit()
    original_agent = database.read_bytes()
    original_board = board.read_bytes()

    with pytest.raises(StateMigrationError, match="unsupported table set") as error:
        run_state_migrations(state)

    assert database.read_bytes() == original_agent
    assert board.read_bytes() == original_board
    assert not (state / "state_version.json").exists()
    assert error.value.backup_path.is_dir()


@pytest.mark.parametrize("centrality_order", ["added", "before_updated_at"])
def test_v6_to_v7_migration_converts_preprocess_schema_and_legacy_fts(tmp_path: Path, centrality_order: str):
    from local_ai_hub.preprocess_lexical import SHARED_FTS_ROWS, fts_layout, has_retired_fts

    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)
    database = state / "preprocess.sqlite3"
    with closing(sqlite3.connect(database)) as con:
        con.executescript("""
            CREATE TABLE source_index (
                root TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
                text TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(root,path)
            );
            CREATE INDEX idx_source_index_hash ON source_index(content_hash);
            CREATE TABLE file_refs (
                root TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
                size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL DEFAULT 0,
                needs_hash INTEGER NOT NULL DEFAULT 0, rag_hash TEXT,
                last_accessed_at REAL NOT NULL DEFAULT 0, generation INTEGER NOT NULL,
                card_key TEXT,
                {centrality_column}
                updated_at REAL NOT NULL, PRIMARY KEY(root,path)
            );
            CREATE TABLE external_index_state (
                root TEXT NOT NULL, backend TEXT NOT NULL, revision_hash TEXT NOT NULL,
                status TEXT NOT NULL, updated_at REAL NOT NULL, error TEXT,
                PRIMARY KEY(root,backend)
            );
            CREATE TABLE file_card_enrichment (
                content_hash TEXT NOT NULL, model TEXT NOT NULL, pipeline_version TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                retry_after REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
                last_error TEXT, updated_at REAL NOT NULL,
                PRIMARY KEY(content_hash,model,pipeline_version)
            );
            CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content);
            INSERT INTO source_index VALUES('w','a.py','h1','source A',1.0);
            INSERT INTO source_index VALUES('w','b.py','h2','source B',2.0);
            INSERT INTO file_refs VALUES({file_refs_values});
            INSERT INTO external_index_state VALUES('w','faiss','rev','error',14,'retry me');
            INSERT INTO file_card_enrichment VALUES('h1','model','v1','ready',2,0,0,NULL,3.0);
            INSERT INTO source_fts(root,path,content) VALUES('w','a.py','duplicate shared text');
            INSERT INTO source_fts(root,path,content) VALUES('w','b.py','duplicate shared text');
        """.format(
            centrality_column="centrality_score REAL NOT NULL DEFAULT 0.0, " if centrality_order == "before_updated_at" else "",
            file_refs_values=(
                "'w','a.py','h1',10,11,0,NULL,12,1,NULL,0.25,13"
                if centrality_order == "before_updated_at"
                else "'w','a.py','h1',10,11,0,NULL,12,1,NULL,13"
            ),
        ))

    result = run_state_migrations(state)

    assert result["status"] == "migrated"
    assert read_state_version(state) == 11
    with closing(sqlite3.connect(database)) as con:
        assert [row[1] for row in con.execute("PRAGMA table_info(source_index)")] == [
            "root", "path", "content_hash", "text", "updated_at", "text_origin",
        ]
        assert con.execute("SELECT path,text_origin FROM source_index ORDER BY path").fetchall() == [
            ("a.py", "unknown"), ("b.py", "unknown"),
        ]
        columns = [row[1] for row in con.execute("PRAGMA table_info(file_refs)")]
        expected_columns = [
            "root", "path", "content_hash", "size", "mtime_ns", "needs_hash", "rag_hash",
            "last_accessed_at", "generation", "card_key",
        ]
        expected_columns += (["centrality_score", "updated_at"] if centrality_order == "before_updated_at" else ["updated_at", "centrality_score"])
        assert columns == expected_columns
        assert con.execute("SELECT root,path,centrality_score FROM file_refs").fetchone() == (
            "w", "a.py", 0.25 if centrality_order == "before_updated_at" else 0.0,
        )
        assert [row[1] for row in con.execute("PRAGMA table_info(external_index_state)")][-1] == "retry_count"
        assert con.execute("SELECT root,backend,revision_hash,status,updated_at,error,retry_count FROM external_index_state").fetchone() == (
            "w", "faiss", "rev", "error", 14.0, "retry me", 0,
        )
        assert [row[1] for row in con.execute("PRAGMA table_info(file_card_enrichment)")] == [
            "content_hash", "model", "pipeline_version", "status", "attempts",
            "retry_after", "lease_until", "claim_id", "last_error", "updated_at",
        ]
        assert con.execute(
            "SELECT content_hash,model,pipeline_version,status,attempts,claim_id,last_error,updated_at "
            "FROM file_card_enrichment"
        ).fetchone() == ("h1", "model", "v1", "ready", 2, None, None, 3.0)
        assert fts_layout(con) == SHARED_FTS_ROWS
        assert not has_retired_fts(con)
        assert con.execute("SELECT COUNT(*) FROM source_fts_bindings").fetchone() == (2,)
        assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone() == (1,)
        assert con.execute("SELECT path FROM source_fts WHERE source_fts MATCH 'duplicate' ORDER BY path").fetchall() == [
            ("a.py",), ("b.py",),
        ]


def test_operator_migration_can_run_in_place_without_creating_backup(tmp_path: Path):
    state = tmp_path / "state"
    database = _state_with_v6_agent_schema(state)

    result = run_state_migrations(state, target_version=7, create_backup=False)

    assert result["status"] == "migrated"
    assert result["backups"] == []
    assert read_state_version(state) == 7
    assert not list(tmp_path.glob("state.backup-v*"))
    with closing(sqlite3.connect(database)) as con:
        assert [row[1] for row in con.execute("PRAGMA table_info(agent_entity_relations)")][-1] == "repository_id"


def test_v7_to_v8_archives_global_board_and_removes_active_database(tmp_path: Path):
    from local_ai_hub.legacy_board_archive import ARCHIVE_NAME, read_legacy_board_archive

    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=7)
    database = state / "agent_board.sqlite"
    with closing(sqlite3.connect(database)) as con:
        con.executescript("""
            CREATE TABLE agent_board_items (
                item_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium', labels_json TEXT NOT NULL DEFAULT '[]',
                assignee TEXT NOT NULL DEFAULT '', milestone TEXT NOT NULL DEFAULT '',
                linked_task_id TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE agent_milestones (
                name TEXT PRIMARY KEY, target_date TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
            );
            INSERT INTO agent_board_items VALUES
                ('item-1','Ship cleanup','blocked','high','["hub"]','adam','v1','task_old','{"reason":"review"}',1.0,2.0);
            INSERT INTO agent_milestones VALUES ('v1','2026-12-01','First release',1.0);
        """)

    result = run_state_migrations(state)

    assert result["status"] == "migrated"
    assert read_state_version(state) == 11
    assert not database.exists()
    assert (state / ARCHIVE_NAME).is_file()
    assert read_legacy_board_archive(state) == [{
        "item_id": "item-1", "title": "Ship cleanup", "status": "blocked", "priority": "high",
        "assignee": "adam", "milestone": "v1", "linked_task_id": "task_old",
        "created_at": 1.0, "updated_at": 2.0, "labels": ["hub"], "details": {"reason": "review"},
    }]
    document = json.loads((state / ARCHIVE_NAME).read_text(encoding="utf-8"))
    assert document["milestones"] == [{
        "name": "v1", "target_date": "2026-12-01", "description": "First release", "created_at": 1.0,
    }]


def test_v7_to_v8_rejects_unknown_global_board_schema_and_preserves_source(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=7)
    database = state / "agent_board.sqlite"
    with closing(sqlite3.connect(database)) as con:
        con.execute("CREATE TABLE unknown_legacy_data (value TEXT)")
        con.execute("INSERT INTO unknown_legacy_data VALUES ('keep')")
    original = database.read_bytes()

    with pytest.raises(StateMigrationError, match="unsupported table set"):
        run_state_migrations(state)

    assert database.read_bytes() == original
    assert read_state_version(state) == 7


def test_v7_to_v8_rejects_orphaned_board_wal_sidecar(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=7)
    sidecar = state / "agent_board.sqlite-wal"
    sidecar.write_bytes(b"unmatched WAL data")

    with pytest.raises(StateMigrationError, match="sidecar exists without its database"):
        run_state_migrations(state)

    assert sidecar.read_bytes() == b"unmatched WAL data"
    assert read_state_version(state) == 7


def test_runtime_fts_initialization_rejects_legacy_layout(tmp_path: Path):
    from local_ai_hub.preprocess_lexical import LEGACY_FTS, fts_layout, initialize_fts_rows

    database = tmp_path / "preprocess.sqlite3"
    with closing(sqlite3.connect(database)) as con:
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        with pytest.raises(sqlite3.DatabaseError, match="update-time lexical-index migration"):
            initialize_fts_rows(con)
        assert fts_layout(con) == LEGACY_FTS
        assert con.execute("SELECT name FROM sqlite_master WHERE name='source_fts_migration'").fetchone() is None
