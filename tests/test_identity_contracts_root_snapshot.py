from __future__ import annotations

from contextlib import closing
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
    assert store.get(str(repo_a), "decision")["value"] == "second"
    assert store.delete(str(repo_a), "decision")["deleted"] is True
    assert store.get(str(repo_a), "decision")["success"] is False
    assert store.get(str(repo_b), "decision")["success"] is False
    assert store.search(str(repo_b))["results"] == []


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


def test_workspace_memo_delete_rejects_non_string_tenant_label(tmp_path):
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
            scope_id="repo-a",
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
            scope_id="repo-b",
            key="shared-key",
            value="repo-b value",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(repo_b), "repository_id": "repo-b"},
        ),
        actor="user",
        idempotency_key="repo-b-record",
    )

    assert store.get(record_a.record_id, repository_id="repo-a").value == "repo-a value"
    assert store.get(record_a.record_id, repository_id="repo-b") is None
    assert store.get(record_b.record_id, repository_id="repo-a") is None
    assert store.get(record_b.record_id, repository_id="repo-b").value == "repo-b value"


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
        scope=AgentScope.REPOSITORY,
        scope_id="repo-a",
        root=str(tmp_path / "repo-a"),
        repository_id="repo-a",
    )
    records = store.find_for_context(root=str(tmp_path / "repo-b"))
    assert any(record.record_id == shared.record_id for record in records)


def test_tenant_label_does_not_authenticate_http_request(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"api_token": "expected-local-token"}}),
    )

    request = http_server.Handler.__new__(http_server.Handler)
    request.headers = {"X-LocalAI-Tenant": "administrator"}
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
    held = leases.claim("identity-a", root, ["src/shared.py"], purpose="inspect")

    conflict = leases.claim("identity-b", root, ["src/shared.py"], purpose="edit")

    assert conflict["success"] is False
    assert conflict["conflicts"][0]["owner"] == "identity-a"
    assert conflict["conflicts"][0]["lease_id"] == held["lease_id"]
    assert conflict["conflicts"][0]["held_path"] == "src/shared.py"


@pytest.mark.parametrize("label", ["http-default", "system", "admin", "*"])
def test_unknown_lease_owner_cannot_spoof_current_owner(tmp_path, label):
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
    first = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="a:b",
        key="c",
        value="scope delimiter pair",
        status=MemoryStatus.CONFIRMED,
        source="user",
    )
    second = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.WORKTREE,
        scope_id="a",
        key="b:c",
        value="key delimiter pair",
        status=MemoryStatus.CONFIRMED,
        source="user",
    )

    recorded_first = store.record(first, actor="user", idempotency_key="same-request")
    recorded_second = store.record(second, actor="user", idempotency_key="same-request")

    assert recorded_first.record_id == first.record_id
    assert recorded_second.record_id == second.record_id
    assert recorded_second.record_id != recorded_first.record_id
    assert store.get(first.record_id, scope=AgentScope.WORKTREE, scope_id="a:b").value == "scope delimiter pair"
    assert store.get(second.record_id, scope=AgentScope.WORKTREE, scope_id="a").value == "key delimiter pair"


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
    ).value == "remove exact record"
    assert store.find_relations(source_entity=record.record_id) == relations_before_denied_delete

    assert store.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-delete",
    ) is True
    assert store.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="worktree-delete",
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
        retained = con.execute(
            "SELECT 1 FROM agent_memory_records WHERE record_id = ?",
            (legacy.record_id,),
        ).fetchone()
    assert retained is not None
