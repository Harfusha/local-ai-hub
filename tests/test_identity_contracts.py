from __future__ import annotations

from contextlib import closing
import json
import os
import subprocess
import sqlite3
import sys
import time
from pathlib import Path
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


def test_workspace_memos_are_shared_within_and_isolated_between_repositories(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    repo_a = tmp_path / "customer-a" / "repo"
    repo_b = tmp_path / "customer-b" / "repo"
    repo_a.mkdir(parents=True)
    repo_b.mkdir(parents=True)

    first = store.put(str(repo_a), "decision", "first")
    second = store.put(str(repo_a), "decision", "second")

    assert first["scope"] == "workspace-shared"
    assert second["scope"] == "workspace-shared"
    shared = store.get(str(repo_a), "decision")
    assert shared["success"] is True
    assert shared["value"] == "second"
    assert shared["scope"] == "workspace-shared"
    found = store.search(str(repo_a), "second")
    assert found["scope"] == "workspace-shared"
    assert found["results"][0]["scope"] == "workspace-shared"
    assert store.get(str(repo_b), "decision")["success"] is False
    deleted = store.delete(str(repo_a), "decision")
    assert deleted["deleted"] is True
    assert store.get(str(repo_a), "decision")["success"] is False
    assert store.get(str(repo_b), "decision")["success"] is False
    assert store.search(str(repo_b))["results"] == []


def test_workspace_memo_expected_version_rejects_stale_overwrite(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()

    created = store.put(str(root), "decision", "first", expected_version=0)
    assert created["version"] == 1
    assert store.get(str(root), "decision")["version"] == 1

    winning = store.put(str(root), "decision", "second", expected_version=1)
    assert winning["version"] == 2

    stale = store.put(str(root), "decision", "stale", expected_version=1)
    assert stale["success"] is False
    assert stale["version_conflict"] is True
    assert stale["expected_version"] == 1
    assert stale["current_version"] == 2
    current = store.get(str(root), "decision")
    assert current["value"] == "second"
    assert current["version"] == 2


def test_workspace_memo_expected_version_serializes_across_processes(tmp_path):
    state_dir = tmp_path / "state"
    root = tmp_path / "repo"
    root.mkdir()
    store = WorkspaceMemoryStore(state_dir)
    assert store.put(str(root), "decision", "initial", expected_version=0)["version"] == 1

    barrier = tmp_path / "release-writers"
    ready_paths = [tmp_path / f"writer-{index}-ready" for index in range(2)]
    write_script = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "source_dir, state_dir, root, barrier_path, ready_path, value = sys.argv[1:]\n"
        "sys.path.insert(0, source_dir)\n"
        "ready = Path(ready_path)\n"
        "ready.touch()\n"
        "deadline = time.monotonic() + 20\n"
        "while not Path(barrier_path).exists():\n"
        "    if time.monotonic() >= deadline:\n"
        "        raise TimeoutError('parent did not release memo writers')\n"
        "    time.sleep(0.01)\n"
        "import local_ai_hub.memory as loaded_module\n"
        "assert Path(loaded_module.__file__).resolve().is_relative_to(Path(source_dir).resolve())\n"
        "result = loaded_module.WorkspaceMemoryStore(Path(state_dir)).put(root, 'decision', value, expected_version=1)\n"
        "print(json.dumps(result, sort_keys=True))\n"
    )
    source_dir = os.environ.get("T05_ROOT_SOURCE_DIR", str(Path(__file__).resolve().parents[1] / "src"))
    worker_values = ["writer-a", "writer-b"]
    workers = []
    outputs = []
    try:
        for index, value in enumerate(worker_values):
            workers.append(subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    write_script,
                    source_dir,
                    str(state_dir),
                    str(root),
                    str(barrier),
                    str(ready_paths[index]),
                    value,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ))

        deadline = time.monotonic() + 15
        while not all(path.exists() for path in ready_paths):
            if any(worker.poll() is not None for worker in workers) or time.monotonic() >= deadline:
                barrier.touch()
                details = [worker.communicate(timeout=5) for worker in workers]
                raise AssertionError(f"memo writers failed to rendezvous: {details!r}")
            time.sleep(0.01)
        barrier.touch()
        outputs = [worker.communicate(timeout=20) for worker in workers]
        assert [worker.returncode for worker in workers] == [0, 0], outputs
    finally:
        barrier.touch()
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=5)

    results = [json.loads(stdout) for stdout, _stderr in outputs]
    assert sum(result["success"] is True for result in results) == 1
    assert sum(result.get("version_conflict") is True for result in results) == 1
    conflict = next(result for result in results if result.get("version_conflict") is True)
    winner = next(result for result in results if result["success"] is True)
    assert conflict["current_version"] == 2
    assert winner["version"] == 2
    current = store.get(str(root), "decision")
    assert current["version"] == 2
    assert current["value"] in {"writer-a", "writer-b"}


def test_worktree_memory_idempotency_isolated_by_scope_id(tmp_path):
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    worktree_a.mkdir()
    worktree_b.mkdir()

    first = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-a",
        key="decision",
        value="worktree A decision",
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance={"root": str(worktree_a), "repository_id": "repo-shared", "worktree_id": "worktree-a"},
    )
    second = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-b",
        key="decision",
        value="worktree B decision",
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance={"root": str(worktree_b), "repository_id": "repo-shared", "worktree_id": "worktree-b"},
    )

    recorded_a = store.record(first, actor="user", idempotency_key="same-request")
    recorded_b = store.record(second, actor="user", idempotency_key="same-request")

    assert recorded_a.record_id == first.record_id
    assert recorded_b.record_id == second.record_id
    assert recorded_b.scope_id == "worktree-b"
    assert recorded_b.value == "worktree B decision"


def test_worktree_memory_idempotency_stream_key_is_unambiguous(tmp_path):
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    first = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="a:b",
        key="c",
        provenance={"root": str(root), "worktree_id": "a:b"},
        value="scope delimiter pair",
        status=MemoryStatus.CONFIRMED,
        source="user",
    )
    second = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="a",
        key="b:c",
        provenance={"root": str(root), "worktree_id": "a"},
        value="key delimiter pair",
        status=MemoryStatus.CONFIRMED,
        source="user",
    )

    recorded_first = store.record(first, actor="user", idempotency_key="same-request")
    recorded_second = store.record(second, actor="user", idempotency_key="same-request")

    assert recorded_first.record_id == first.record_id
    assert recorded_second.record_id == second.record_id
    assert recorded_second.record_id != recorded_first.record_id
    assert store.get(first.record_id, scope=AgentScope.WORKTREE, scope_id="a:b", root=str(root), worktree_id="a:b").value == "scope delimiter pair"
    assert store.get(second.record_id, scope=AgentScope.WORKTREE, scope_id="a", root=str(root), worktree_id="a").value == "key delimiter pair"


def test_memory_delete_requires_matching_scope_identity(tmp_path):
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    record = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-delete",
        key="decision",
        value="remove exact record",
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance={"root": str(worktree), "repository_id": "repo-shared", "worktree_id": "worktree-delete"},
    )
    store.record(record, actor="user")
    related = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.WORKTREE,
            scope_id="worktree-delete",
            key="related",
            value="retain relation on denied deletion",
            source="user",
        ),
        actor="user",
    )
    store.record_relation(record.record_id, "relates_to", related.record_id)
    relations_before_denied_delete = store.find_relations(source_entity=record.record_id)
    assert any(relation["relation"] == "relates_to" for relation in relations_before_denied_delete)

    assert store.delete(record.record_id) is False
    assert store.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="another-worktree",
    ) is False
    assert store.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-delete",
        root=str(worktree),
        worktree_id="worktree-delete",
    ).value == "remove exact record"
    assert store.find_relations(source_entity=record.record_id) == relations_before_denied_delete

    assert store.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-delete",
        root=str(worktree),
        worktree_id="worktree-delete",
    ) is True
    assert store.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-delete",
        root=str(worktree),
        worktree_id="worktree-delete",
    ) is None
    assert store.find_relations(source_entity=record.record_id) == []

    legacy = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.SESSION,
            key="legacy-unscoped",
            value="must remain without verified scope id",
            source="user",
        ),
        actor="user",
    )
    assert store.delete(legacy.record_id, scope=AgentScope.SESSION) is False
    with closing(sqlite3.connect(store.state_store.db_path)) as con:
        assert con.execute(
            "SELECT 1 FROM agent_memory_records WHERE record_id = ?",
            (legacy.record_id,),
        ).fetchone() is not None


def test_workspace_memo_version_does_not_reset_after_delete_and_recreate(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()

    created = store.put(str(root), "decision", "first", expected_version=0)
    assert created["version"] == 1
    deleted = store.delete(str(root), "decision")
    assert deleted["deleted"] is True
    assert deleted["version"] == 2
    missing = store.get(str(root), "decision")
    assert missing["success"] is False
    assert missing["version"] == 2

    recreated = store.put(str(root), "decision", "recreated", expected_version=2)
    assert recreated["version"] == 3
    stale = store.put(str(root), "decision", "stale", expected_version=1)
    assert stale["version_conflict"] is True
    assert stale["current_version"] == 3
    assert store.get(str(root), "decision")["value"] == "recreated"


def test_workspace_memo_expiry_preserves_last_committed_generation(tmp_path):
    state_dir = tmp_path / "state"
    store = WorkspaceMemoryStore(state_dir)
    root = tmp_path / "repo"
    root.mkdir()
    created = store.put(str(root), "decision", "first", expected_version=0)
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
    recreated = store.put(str(root), "decision", "restored", expected_version=1)
    assert recreated["version"] == 2
    assert store.get(str(root), "decision")["value"] == "restored"


def test_workspace_memo_legacy_schema_refuses_runtime_conversion_without_writes(tmp_path):
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
    db_before = db_path.read_bytes()
    backup_path = db_path.with_name(db_path.name + ".pre-memo-version.bak")
    backup_path.write_bytes(b"operator-preserved backup")

    with pytest.raises(RuntimeError, match="explicit offline conversion"):
        WorkspaceMemoryStore(state_dir)

    assert db_path.read_bytes() == db_before
    assert backup_path.read_bytes() == b"operator-preserved backup"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (None, "valid"),
        (123, "valid"),
        ("valid", None),
        ("valid", 123),
    ],
)
def test_workspace_memo_rejects_malformed_key_or_value(tmp_path, key, value):
    store = WorkspaceMemoryStore(tmp_path / "state")

    with pytest.raises(ValueError):
        store.put(str(tmp_path), key, value)


def test_workspace_memo_delete_rejects_retired_tenant_keyword(tmp_path):
    store = WorkspaceMemoryStore(tmp_path / "state")
    store.put(str(tmp_path), "key", "value")

    with pytest.raises(TypeError, match="unexpected keyword"):
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

    assert store.get(record_a.record_id, root=str(repo_a), repository_id="repo-a").value == "repo-a value"
    assert store.get(record_a.record_id, root=str(repo_b), repository_id="repo-b") is None
    assert store.get(record_b.record_id, root=str(repo_a), repository_id="repo-a") is None
    assert store.get(record_b.record_id, root=str(repo_b), repository_id="repo-b").value == "repo-b value"


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
    shared = store.promote(
        repository_record.record_id,
        AgentScope.GLOBAL,
        approver="user",
        root=str(tmp_path / "repo-a"),
        repository_id="repo-a",
    )
    records = store.find_for_context(root=str(tmp_path / "repo-b"))
    assert any(record.record_id == shared.record_id for record in records)


def test_api_token_authentication_requires_a_valid_token(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"api_token": "expected-local-token"}}),
    )

    request = http_server.Handler.__new__(http_server.Handler)
    request.headers = {}
    request.client_address = ("127.0.0.1", 1234)
    request.path = "/api/test"
    request.command = "GET"
    assert Handler._authorized(request) is False

    request.headers["X-LocalAI-Token"] = "wrong-token"
    assert Handler._authorized(request) is False

    request.headers["X-LocalAI-Token"] = "expected-local-token"
    assert Handler._authorized(request) is True


def test_lease_conflicts_keep_owner_details_visible(tmp_path):
    leases = ScopeLeaseStore(tmp_path / "state")
    root = str(tmp_path / "repo")
    held = leases.claim(owner="identity-a", root=root, paths=["src/shared.py"], purpose="inspect")

    conflict = leases.claim(owner="identity-b", root=root, paths=["src/shared.py"], purpose="edit")

    assert conflict["success"] is False
    assert conflict["conflicts"][0]["owner"] == "identity-a"
    assert conflict["conflicts"][0]["lease_id"] == held["lease_id"]
    assert conflict["conflicts"][0]["held_path"] == "src/shared.py"


@pytest.mark.parametrize("label", ["http-default", "system", "admin", "*"])
def test_unknown_lease_owner_cannot_spoof_current_owner(tmp_path, label):
    leases = ScopeLeaseStore(tmp_path / "state")
    root = str(tmp_path / "repo")
    held_for_release = leases.claim(owner="identity-a", root=root, paths=["src/release.py"])
    held_for_renew = leases.claim(owner="identity-a", root=root, paths=["src/renew.py"])

    released = leases.release(owner=label, lease_id=held_for_release["lease_id"])
    renewed = leases.renew(owner=label, lease_id=held_for_renew["lease_id"])

    assert released["released_rows"] == 0
    assert renewed["success"] is False


def test_mixed_memory_identity_context_is_rejected():
    scope, scope_id, ambiguous = _resolve_memory_scope(
        None,
        task_id="task-a",
        session_id="session-b",
    )

    assert (scope, scope_id, ambiguous) == (None, None, True)


def test_artifacts_are_owner_global_and_evidence_ids_are_repository_scoped(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact_id = artifacts.put("artifact payload", kind="text")
    assert artifacts.get(artifact_id)["success"] is True

    evidence = EvidenceStore(tmp_path / "evidence")
    item = {"path": "src/module.py", "file_sha256": "a" * 64, "start_line": 1, "end_line": 1, "text": "value = 1"}
    repo_a = str(tmp_path / "repo-a")
    repo_b = str(tmp_path / "repo-b")
    evidence_a = evidence.put(repo_a, item)
    evidence_b = evidence.put(repo_b, item)

    assert evidence_a != evidence_b
    assert evidence.get(evidence_a, verify=False)["root"] == repo_a
    assert evidence.get(evidence_b, verify=False)["root"] == repo_b


def test_retired_rag_tenant_scope_is_rejected():
    from local_ai_hub.config import ConfigError, validate_config

    with pytest.raises(ConfigError, match="rag.scope was removed"):
        validate_config({"rag": {"scope": "tenant"}})

