from __future__ import annotations

from contextlib import closing
import os
import sqlite3
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.http_server import Handler, _resolve_memory_scope
import local_ai_hub.http_server as http_server
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.memory import WorkspaceMemoryStore
from local_ai_hub.rag import RAGStore


def test_workspace_memos_report_shared_scope_and_isolate_repositories(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    repo_a = tmp_path / "customer-a" / "repo"
    repo_b = tmp_path / "customer-b" / "repo"
    repo_a.mkdir(parents=True)
    repo_b.mkdir(parents=True)

    first = store.put(str(repo_a), "decision", "first", "identity-a")
    second = store.put(str(repo_a), "decision", "second", "identity-b")

    assert first["scope"] == "workspace-shared"
    assert second["scope"] == "workspace-shared"
    assert second["tenant"] == "identity-b"
    shared = store.get(str(repo_a), "decision")
    assert shared["success"] is True
    assert shared["value"] == "second"
    assert shared["tenant"] == "identity-b"
    assert shared["scope"] == "workspace-shared"
    found = store.search(str(repo_a), "second")
    assert found["scope"] == "workspace-shared"
    assert found["results"][0]["scope"] == "workspace-shared"
    wrong_label_delete = store.delete(str(repo_a), "decision", tenant="identity-a")
    assert wrong_label_delete["scope"] == "workspace-shared"
    assert wrong_label_delete["deleted"] is False
    assert store.get(str(repo_a), "decision")["value"] == "second"
    matching_label_delete = store.delete(str(repo_a), "decision", tenant="identity-b")
    assert matching_label_delete["deleted"] is True
    assert store.get(str(repo_a), "decision")["success"] is False
    assert store.get(str(repo_b), "decision")["success"] is False
    assert store.search(str(repo_b))["results"] == []


def test_workspace_memo_expected_version_rejects_stale_overwrite(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()

    created = store.put(str(root), "decision", "first", "identity-a", expected_version=0)
    assert created["version"] == 1
    assert store.get(str(root), "decision")["version"] == 1

    winning = store.put(str(root), "decision", "second", "identity-b", expected_version=1)
    assert winning["version"] == 2

    stale = store.put(str(root), "decision", "stale", "identity-c", expected_version=1)
    assert stale["success"] is False
    assert stale["version_conflict"] is True
    assert stale["expected_version"] == 1
    assert stale["current_version"] == 2
    current = store.get(str(root), "decision")
    assert current["value"] == "second"
    assert current["tenant"] == "identity-b"
    assert current["version"] == 2


def test_workspace_memo_version_does_not_reset_after_delete_and_recreate(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()

    created = store.put(str(root), "decision", "first", "identity-a", expected_version=0)
    assert created["version"] == 1
    deleted = store.delete(str(root), "decision")
    assert deleted["deleted"] is True
    assert deleted["version"] == 2
    missing = store.get(str(root), "decision")
    assert missing["success"] is False
    assert missing["version"] == 2

    recreated = store.put(str(root), "decision", "recreated", "identity-b", expected_version=2)
    assert recreated["version"] == 3
    stale = store.put(str(root), "decision", "stale", "identity-c", expected_version=1)
    assert stale["version_conflict"] is True
    assert stale["current_version"] == 3
    assert store.get(str(root), "decision")["value"] == "recreated"


def test_workspace_memo_expiry_preserves_last_committed_generation(tmp_path):
    state_dir = tmp_path / "state"
    store = WorkspaceMemoryStore(state_dir)
    root = tmp_path / "repo"
    root.mkdir()
    created = store.put(str(root), "decision", "first", "identity-a", expected_version=0)
    assert created["version"] == 1

    with closing(sqlite3.connect(state_dir / "workspace_memory.sqlite3")) as connection:
        connection.execute(
            "UPDATE memos SET expires_at=0 WHERE workspace=? AND memo_key=?",
            (WorkspaceMemoryStore.workspace_id(str(root)), "decision"),
        )
        connection.commit()

    expired = store.get(str(root), "decision")
    assert expired["success"] is False
    assert expired["version"] == 1
    recreated = store.put(str(root), "decision", "restored", "identity-b", expected_version=1)
    assert recreated["version"] == 2
    assert store.get(str(root), "decision")["value"] == "restored"


def test_workspace_memo_schema_upgrade_preserves_existing_rows(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    db_path = state_dir / "workspace_memory.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """CREATE TABLE memos (
                workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL,
                tenant TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL,
                expires_at REAL NOT NULL, PRIMARY KEY(workspace, memo_key)
            )"""
        )
        connection.execute(
            "INSERT INTO memos VALUES (?, ?, ?, ?, ?, ?, ?)",
            (WorkspaceMemoryStore.workspace_id(str(root)), "decision", "kept", "owner", "{}", 10.0, 9_999_999_999.0),
        )
        connection.commit()

    store = WorkspaceMemoryStore(state_dir)
    backup_path = db_path.with_name(db_path.name + ".pre-memo-version.bak")
    assert backup_path.is_file()
    with closing(sqlite3.connect(backup_path)) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        backup_columns = {str(row[1]) for row in backup.execute("PRAGMA table_info(memos)")}
        backup_row = backup.execute(
            "SELECT workspace, memo_key, value, tenant, metadata, updated_at, expires_at FROM memos"
        ).fetchone()
    assert "version" not in backup_columns
    assert backup_row == (WorkspaceMemoryStore.workspace_id(str(root)), "decision", "kept", "owner", "{}", 10.0, 9_999_999_999.0)
    backup_contents = backup_path.read_bytes()

    current = store.get(str(root), "decision")
    assert current["success"] is True
    assert current["value"] == "kept"
    assert current["version"] == 1
    WorkspaceMemoryStore(state_dir)
    assert backup_path.read_bytes() == backup_contents


def test_workspace_memo_migration_backup_refreshes_when_stale(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    db_path = state_dir / "workspace_memory.sqlite3"
    workspace = WorkspaceMemoryStore.workspace_id(str(root))
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """CREATE TABLE memos (
                workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL,
                tenant TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL,
                expires_at REAL NOT NULL, PRIMARY KEY(workspace, memo_key)
            )"""
        )
        connection.execute(
            "INSERT INTO memos VALUES (?, ?, ?, ?, ?, ?, ?)",
            (workspace, "decision", "kept", "owner", "{}", 10.0, 9_999_999_999.0),
        )
        connection.commit()

    store = WorkspaceMemoryStore(state_dir)
    backup_path = db_path.with_name(db_path.name + ".pre-memo-version.bak")
    store.put(str(root), "later", "new row", "writer")
    store._create_migration_backup()

    with closing(sqlite3.connect(backup_path)) as backup:
        rows = set(backup.execute("SELECT memo_key, value FROM memos"))
    assert rows == {("decision", "kept"), ("later", "new row")}


def test_workspace_memo_migration_backup_replaces_hard_link(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    store = WorkspaceMemoryStore(state_dir)
    store.put(str(root), "decision", "kept", "owner")
    backup_path = store.path.with_name(store.path.name + ".pre-memo-version.bak")
    os.link(store.path, backup_path)
    assert os.path.samefile(store.path, backup_path)

    store._create_migration_backup()

    assert not os.path.samefile(store.path, backup_path)
    with closing(sqlite3.connect(backup_path)) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert backup.execute(
            "SELECT value FROM memos WHERE memo_key='decision'"
        ).fetchone() == ("kept",)


def test_workspace_memo_migration_backup_replaces_symlink_to_matching_copy(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    store = WorkspaceMemoryStore(state_dir)
    store.put(str(root), "decision", "kept", "owner")
    backup_path = store.path.with_name(store.path.name + ".pre-memo-version.bak")
    external_copy = tmp_path / "external-copy.sqlite3"
    with closing(sqlite3.connect(store.path)) as source, closing(
        sqlite3.connect(external_copy)
    ) as destination:
        source.backup(destination)
        destination.commit()
    try:
        os.symlink(external_copy, backup_path)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks unavailable: {error}")
    assert backup_path.is_symlink()
    assert not backup_path.samefile(store.path)

    store._create_migration_backup()

    assert not backup_path.is_symlink()
    assert not backup_path.samefile(store.path)
    with closing(sqlite3.connect(backup_path)) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert backup.execute(
            "SELECT value FROM memos WHERE memo_key='decision'"
        ).fetchone() == ("kept",)

def test_workspace_memo_migration_backup_failure_leaves_schema_unchanged(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    db_path = state_dir / "workspace_memory.sqlite3"
    workspace = WorkspaceMemoryStore.workspace_id(str(root))
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """CREATE TABLE memos (
                workspace TEXT NOT NULL, memo_key TEXT NOT NULL, value TEXT NOT NULL,
                tenant TEXT NOT NULL, metadata TEXT NOT NULL, updated_at REAL NOT NULL,
                expires_at REAL NOT NULL, PRIMARY KEY(workspace, memo_key)
            )"""
        )
        connection.execute(
            "INSERT INTO memos VALUES (?, ?, ?, ?, ?, ?, ?)",
            (workspace, "decision", "kept", "owner", "{}", 10.0, 9_999_999_999.0),
        )
        connection.commit()
    db_path.with_name(db_path.name + ".pre-memo-version.bak").mkdir()

    with pytest.raises(sqlite3.DatabaseError, match="backup path is not a file"):
        WorkspaceMemoryStore(state_dir)

    with closing(sqlite3.connect(db_path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(memos)")}
        row = connection.execute("SELECT value FROM memos WHERE memo_key='decision'").fetchone()
    assert "memo_versions" not in tables
    assert "version" not in columns
    assert row == ("kept",)

@pytest.mark.parametrize(
    ("key", "value", "tenant"),
    [
        (None, "valid", "identity"),
        (123, "valid", "identity"),
        ("valid", None, "identity"),
        ("valid", 123, "identity"),
        ("valid", "value", None),
        ("valid", "value", 7),
        ("valid", "value", "t" * 129),
    ],
)
def test_workspace_memo_rejects_malformed_key_value_or_tenant(tmp_path, key, value, tenant):
    store = WorkspaceMemoryStore(tmp_path / "state")

    with pytest.raises(ValueError):
        store.put(str(tmp_path), key, value, tenant)


def test_workspace_memo_delete_rejects_non_string_tenant_label(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    store.put(str(tmp_path), "key", "value", "identity-a")

    with pytest.raises(ValueError):
        store.delete(str(tmp_path), "key", tenant=None)


def test_repository_memory_foreign_id_requires_matching_repository(tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))

    record_a = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="shared-key",
            value="repo-a value",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(repo_a), "repository_id": "repo-a"},
        ),
        actor="user",
        idempotency_key="repo-a-record",
    )
    record_b = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="shared-key",
            value="repo-b value",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(repo_b), "repository_id": "repo-b"},
        ),
        actor="user",
        idempotency_key="repo-b-record",
    )

    assert store.get(record_a.record_id, root=str(repo_a)).value == "repo-a value"
    assert store.get(record_a.record_id, root=str(repo_b)) is None
    assert store.get(record_b.record_id, root=str(repo_a)) is None
    assert store.get(record_b.record_id, root=str(repo_b)).value == "repo-b value"


def test_global_memory_store_requires_approval_marker_and_then_is_shared(tmp_path):
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    repository_record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.CONVENTION,
            scope=AgentScope.REPOSITORY,
            scope_id="repo-a",
            key="shared-convention",
            value="format with tool X",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(tmp_path / "repo-a"), "repository_id": "repo-a"},
        ),
        actor="user",
        idempotency_key="repository-convention",
    )

    with pytest.raises(PermissionError):
        store.promote(repository_record.record_id, AgentScope.GLOBAL, approver="agent")

    # This direct store test checks its approval marker only; it cannot authenticate a human actor.
    shared = store.promote(repository_record.record_id, AgentScope.GLOBAL, approver="user")
    records = store.find_for_context(root=str(tmp_path / "repo-b"))
    assert any(record.record_id == shared.record_id for record in records)


def test_tenant_label_does_not_authenticate_http_request(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"api_token": "expected-local-token"}}),
    )

    request = SimpleNamespace(headers={"X-LocalAI-Tenant": "administrator"})
    assert Handler._authorized(request) is False

    request.headers["X-LocalAI-Token"] = "wrong-token"
    assert Handler._authorized(request) is False

    request.headers["X-LocalAI-Token"] = "expected-local-token"
    assert Handler._authorized(request) is True


def test_lease_conflicts_keep_owner_details_visible(tmp_path):
    leases = ScopeLeaseStore(tmp_path / "state")
    root = str(tmp_path / "repo")
    held = leases.claim("identity-a", root, ["src/shared.py"], purpose="inspect")

    conflict = leases.claim("identity-b", root, ["src/shared.py"], purpose="edit")

    assert conflict["success"] is False
    assert conflict["conflicts"][0]["tenant"] == "identity-a"
    assert conflict["conflicts"][0]["lease_id"] == held["lease_id"]
    assert conflict["conflicts"][0]["held_path"] == "src/shared.py"


@pytest.mark.parametrize("label", ["http-default", "system", "admin", "*"])
def test_privileged_lease_tenant_label_cannot_spoof_owner(tmp_path, label):
    leases = ScopeLeaseStore(tmp_path / "state")
    root = str(tmp_path / "repo")
    held_for_release = leases.claim("identity-a", root, ["src/release.py"])
    held_for_renew = leases.claim("identity-a", root, ["src/renew.py"])

    released = leases.release(label, held_for_release["lease_id"])
    renewed = leases.renew(label, held_for_renew["lease_id"])

    assert released["released_rows"] == 0
    assert renewed["success"] is False


def test_mixed_memory_identity_context_is_rejected():
    scope, scope_id, ambiguous = _resolve_memory_scope(
        None,
        task_id="task-a",
        session_id="session-b",
    )

    assert (scope, scope_id, ambiguous) == (None, None, True)


def test_artifact_lookup_is_tenant_scoped_and_evidence_ids_are_repository_scoped(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact_id = artifacts.put("artifact payload", "identity-a", "text")
    assert artifacts.get(artifact_id, tenant="identity-b")["success"] is False

    evidence = EvidenceStore(tmp_path / "evidence")
    item = {"path": "src/module.py", "file_sha256": "a" * 64, "start_line": 1, "end_line": 1, "text": "value = 1"}
    repo_a = str(tmp_path / "repo-a")
    repo_b = str(tmp_path / "repo-b")
    evidence_a = evidence.put(repo_a, item)
    evidence_b = evidence.put(repo_b, item)

    assert evidence_a != evidence_b
    assert evidence.get(evidence_a, verify=False)["root"] == repo_a
    assert evidence.get(evidence_b, verify=False)["root"] == repo_b


def test_tenant_scoped_rag_search_cache_keeps_index_results_isolated(tmp_path):
    class QueryServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {"success": True, "embeddings": [[1.0, 0.0] for _ in texts]}

    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"scope": "tenant", "extensions": [".py"], "ignore_dirs": []},
            "features": {"reranker": False},
        },
        QueryServices(),
    )
    workspace = "shared-workspace"
    path = "src/data.py"
    with closing(store._connect()) as con:
        for tenant, content_hash, text in (
            ("identity-a", "hash-a", "identity a result"),
            ("identity-b", "hash-b", "identity b result"),
        ):
            scope_key = store._scope_key(tenant)
            con.execute(
                "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                (scope_key, workspace, path, 1, len(text), content_hash),
            )
            con.execute(
                "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
                (scope_key, workspace, path, 0, content_hash, text, "[1.0, 0.0]"),
            )
        con.commit()

    result_a = store.search("identity result", "identity-a", workspace, use_reranker=False)
    result_b = store.search("identity result", "identity-b", workspace, use_reranker=False)

    assert result_a["results"][0]["text"] == "identity a result"
    assert result_b["results"][0]["text"] == "identity b result"
    assert result_a["search_cache"]["revision"] != result_b["search_cache"]["revision"]
