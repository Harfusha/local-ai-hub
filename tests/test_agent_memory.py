from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import (
    ApprovalRequiredError,
    MemoryKind,
    MemoryRecord,
    MemoryStatus,
    MemoryStore,
)
from local_ai_hub.sqlite_support import connect_sqlite


def memory_event_stream_id(scope: AgentScope, scope_id: str | None, key: str) -> str:
    return "memory:" + "".join(
        f"{len(part)}:{part}" for part in (scope.value, scope_id or "", key)
    )


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return MemoryStore(state_store)


def test_memory_store_falls_back_when_sqlite_lacks_fts5(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    original_connect = sqlite3.connect

    class Fts5UnavailableConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            normalized_sql = " ".join(sql.split()).casefold()
            if normalized_sql.startswith("create virtual table") and "using fts5" in normalized_sql:
                raise sqlite3.OperationalError("no such module: fts5")
            return super().execute(sql, parameters)

    def connect_without_fts5(*args, **kwargs):
        kwargs["factory"] = Fts5UnavailableConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_without_fts5)
    store_without_fts5 = MemoryStore(state_store)
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="ftsless-note",
        value="needleword remains searchable without full text indexing",
    )

    store_without_fts5.record(record, actor="user")
    found = store_without_fts5.find(
        scope=AgentScope.GLOBAL,
        query="needleword",
        semantic=False,
    )

    assert {item.record_id for item in found} == {record.record_id}


def _repository_identity(record: MemoryRecord) -> dict[str, object]:
    return {
        "scope": AgentScope.REPOSITORY,
        "scope_id": record.scope_id or "",
        "root": str(record.provenance["root"]),
        "repository_id": record.provenance.get("repository_id"),
        "tenant": record.provenance["tenant"],
    }


def _seed_memory_projection(store: MemoryStore, record: MemoryRecord, **_kwargs) -> MemoryRecord:
    """Seed projection for lookup-only assertions; event publication is T08-owned."""
    store._save_record(record)
    return record


def model_conclusion(scope: AgentScope = AgentScope.TASK) -> MemoryRecord:
    return MemoryRecord.create(
        kind=MemoryKind.HYPOTHESIS,
        scope=scope,
        key="parser_behavior",
        value={"issue": "unexpected token"},
        confidence=0.75,
        source="model",
    )


def confirmed_repository_record(store: MemoryStore) -> MemoryRecord:
    provenance = {"root": "C:/repository", "repository_id": "repository-a", "tenant": "tenant-a"}
    rec = MemoryRecord.create(
        kind=MemoryKind.CONVENTION,
        scope=AgentScope.REPOSITORY,
        key="style",
        value="black",
        confidence=0.95,
        source="user",
        status=MemoryStatus.CONFIRMED,
        provenance=provenance,
    )
    return store.record(rec, actor="user", idempotency_key="rec-repo-1")


def test_model_conclusion_is_candidate_not_repository_memory(store: MemoryStore):
    record = store.record(model_conclusion(scope=AgentScope.TASK), actor="agent", idempotency_key="m1")
    assert record.status is MemoryStatus.CANDIDATE


def test_scoped_lookup_excludes_unscoped_task_and_session_records(store: MemoryStore):
    task_root = "C:/repo"
    legacy_task = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        key="legacy-task",
        value="must not leak",
    )
    scoped_task = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-1",
        key="scoped-task",
        value="task value",
        provenance={"root": task_root, "tenant": "tenant-1"},
    )
    legacy_session = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        key="legacy-session",
        value="must not leak",
    )
    scoped_session = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="scoped-session",
        value="session value",
        provenance={"tenant": "tenant-1"},
    )
    for record in (legacy_task, scoped_task, legacy_session, scoped_session):
        _seed_memory_projection(store, record, actor="user")

    assert store.find(scope=AgentScope.TASK) == []
    assert store.find(scope=AgentScope.SESSION) == []
    assert [record.value for record in store.find(task_id="task-1", root=task_root, tenant="tenant-1")] == ["task value"]
    assert [record.value for record in store.find(session_id="session-1", tenant="tenant-1")] == ["session value"]
    assert store.find(scope=AgentScope.TASK, root="C:/repo") == []
    assert store.find(scope=AgentScope.SESSION, tenant="tenant-1") == []
    assert store.get(legacy_task.record_id, task_id="task-1") is None
    assert store.get(scoped_task.record_id, task_id="task-1", root=task_root, tenant="tenant-1").value == "task value"


def test_unscoped_memory_find_only_returns_global_records(store: MemoryStore):
    repository_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="unscoped-repository",
        value="repository value",
        provenance={"root": "C:/repo", "repository_id": "repo-id", "tenant": "tenant-a"},
    ))
    global_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="unscoped-global",
        value="global value",
    ))

    assert store.find(key="unscoped-repository", semantic=False) == []
    assert store.find(record_id=repository_record.record_id, semantic=False) == []
    assert store.get(repository_record.record_id) is None
    assert store.find(key="unscoped-global", semantic=False) == [global_record]


def test_memory_find_enforces_root_repository_and_tenant_identity(store: MemoryStore):
    repo_a = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="shared-repo",
        value="repo-a",
        provenance={"root": "C:/repo-a", "repository_id": "repo-a", "tenant": "tenant-1"},
    ))
    repo_b = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="shared-repo",
        value="repo-b",
        provenance={"root": "C:/repo-b", "repository_id": "repo-b", "tenant": "tenant-1"},
    ))
    repo_missing_id = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="shared-repo",
        value="repo-missing-id",
        provenance={"root": "C:/repo-a", "tenant": "tenant-1"},
    ))
    tenant_one = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="shared-tenant",
        value="tenant-1",
        provenance={"tenant": "tenant-1"},
    ))
    tenant_two = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-2",
        key="shared-tenant",
        value="tenant-2",
        provenance={"tenant": "tenant-2"},
    ))
    rich_task = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-rich",
        key="rich-task",
        value="rich",
        provenance={
            "root": "C:/repo-rich",
            "repository_id": "repo-rich",
            "tenant": "tenant-1",
            "clone_id": "clone-rich",
            "worktree_id": "worktree-rich",
            "branch": "branch-rich",
            "tenant": "tenant-1",
        },
    ))

    assert store.find(scope=AgentScope.REPOSITORY, root="C:/repo-a", tenant="tenant-1", key="shared-repo") == []
    assert [record.record_id for record in store.find(scope=AgentScope.REPOSITORY, root="C:/repo-a", repository_id="repo-a", tenant="tenant-1", key="shared-repo")] == [repo_a.record_id]
    assert [record.record_id for record in store.find(scope=AgentScope.REPOSITORY, root="C:/repo-b", repository_id="repo-b", tenant="tenant-1", key="shared-repo")] == [repo_b.record_id]
    assert [record.record_id for record in store.find(scope=AgentScope.REPOSITORY, repository_id="repo-a", tenant="tenant-1", key="shared-repo")] == [repo_a.record_id]
    # A tenant ID is not a session ID, even when both strings happen to match.
    assert store.find(scope=AgentScope.SESSION, scope_id="tenant-1", tenant="tenant-1", key="shared-tenant") == []
    assert store.find(scope=AgentScope.SESSION, scope_id="tenant-2", tenant="tenant-2", key="shared-tenant") == []
    assert [record.record_id for record in store.find(
        scope=AgentScope.TASK,
        task_id="task-rich",
        tenant="tenant-1",
        clone_id="clone-rich",
        worktree_id="worktree-rich",
        branch="branch-rich",
        root="C:/repo-rich",
        repository_id="repo-rich",
        key="rich-task",
    )] == [rich_task.record_id]
    assert store.find(
        scope=AgentScope.TASK,
        task_id="task-rich",
        tenant="tenant-1",
        clone_id="wrong-clone",
        worktree_id="worktree-rich",
        branch="branch-rich",
        root="C:/repo-rich",
        repository_id="repo-rich",
        key="rich-task",
    ) == []


def test_task_memory_find_requires_matching_root_tenant_and_provenance(store: MemoryStore, tmp_path: Path):
    task_id = "shared-task-id"
    root_a = str(tmp_path / "repo-a")
    root_b = str(tmp_path / "repo-b")
    records = {
        "root_a": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key="shared-task",
            value="root-a tenant-a",
            provenance={"root": root_a, "repository_id": "repo-a", "tenant": "tenant-a"},
        ),
        "root_b": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key="shared-task",
            value="root-b tenant-b",
            provenance={"root": root_b, "repository_id": "repo-b", "tenant": "tenant-b"},
        ),
        "missing_root": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key="shared-task",
            value="missing root",
            provenance={"tenant": "tenant-a"},
        ),
        "missing_tenant": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key="shared-task",
            value="missing tenant",
            provenance={"root": root_a},
        ),
        "corrupt_provenance": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key="shared-task",
            value="corrupt provenance",
            provenance={"root": root_a, "repository_id": "repo-a", "tenant": "tenant-a"},
        ),
    }
    for record in records.values():
        _seed_memory_projection(store, record, actor="user")
    with closing(connect_sqlite(store.state_store.db_path, isolation_level=None)) as con:
        con.execute(
            "UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?",
            ("not-json", records["corrupt_provenance"].record_id),
        )

    def find_ids(*, root: str | None, tenant: str | None, task: str | None = task_id) -> list[str]:
        return [
            record.record_id
            for record in store.find(
                scope=AgentScope.TASK,
                task_id=task,
                root=root,
                repository_id="repo-a" if root == root_a else "repo-b" if root == root_b else None,
                tenant=tenant,
                key="shared-task",
            )
        ]

    assert find_ids(root=root_a, tenant="tenant-a") == [records["root_a"].record_id]
    assert find_ids(root=root_b, tenant="tenant-b") == [records["root_b"].record_id]
    assert find_ids(root=root_a, tenant="tenant-b") == []
    assert find_ids(root=None, tenant="tenant-a") == []
    assert find_ids(root=root_a, tenant=None) == []
    assert find_ids(root=root_a, tenant="tenant-a", task=None) == []


def test_get_requires_identity_scope_for_non_global_records(store: MemoryStore, tmp_path: Path):
    root_a = str(tmp_path / "repo-a")
    root_b = str(tmp_path / "repo-b")
    task_a = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="shared-task-id",
        key="task-a",
        value="tenant-a task memory",
        provenance={"root": root_a, "repository_id": "repo-a", "tenant": "tenant-a"},
    )
    task_b = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="shared-task-id",
        key="task-b",
        value="tenant-b task memory",
        provenance={"root": root_b, "repository_id": "repo-b", "tenant": "tenant-b"},
    )
    task_missing_provenance = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="shared-task-id",
        key="task-missing-provenance",
        value="task memory without provenance",
        provenance={},
    )
    task_corrupt_provenance = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="shared-task-id",
        key="task-corrupt-provenance",
        value="task memory with corrupt provenance",
        provenance={"root": root_a, "repository_id": "repo-a", "tenant": "tenant-a"},
    )
    global_record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.GLOBAL,
        key="global-direct-get",
        value="global memory",
    )
    global_tenant_a = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.GLOBAL,
        key="global-tenant-a-direct-get",
        value="tenant-a global memory",
        provenance={"tenant": "tenant-a"},
    )
    repository_missing_root = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="repository-missing-root-direct-get",
        value="repository memory without root",
        provenance={"tenant": "tenant-a"},
    )
    repository_a = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="repository-a-direct-get",
        value="tenant-a repository memory",
        provenance={"root": root_a, "repository_id": "repo-a", "tenant": "tenant-a"},
    )
    for record in (
        task_a,
        task_b,
        task_missing_provenance,
        task_corrupt_provenance,
        global_record,
        global_tenant_a,
        repository_missing_root,
        repository_a,
    ):
        _seed_memory_projection(store, record, actor="user")
    with closing(connect_sqlite(store.state_store.db_path, isolation_level=None)) as con:
        con.execute(
            "UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?",
            ("not-json", task_corrupt_provenance.record_id),
        )

    assert store.get(task_a.record_id) is None
    assert store.get(task_missing_provenance.record_id) is None
    assert store.get(
        task_missing_provenance.record_id,
        task_id="shared-task-id",
        root=root_a,
        tenant="tenant-a",
    ) is None
    assert store.get(
        task_corrupt_provenance.record_id,
        task_id="shared-task-id",
        root=root_a,
        tenant="tenant-a",
    ) is None
    assert store.get(
        task_b.record_id,
        task_id="shared-task-id",
        root=root_a,
        tenant="tenant-a",
    ) is None
    assert store.get(
        task_a.record_id,
        task_id="shared-task-id",
        root=root_a,
        tenant="tenant-a",
    ) == task_a
    assert store.get(global_tenant_a.record_id) is None
    assert store.get(global_tenant_a.record_id, scope=AgentScope.GLOBAL) is None
    assert store.get(
        global_tenant_a.record_id,
        scope=AgentScope.GLOBAL,
        tenant="tenant-b",
    ) is None
    assert store.get(
        global_tenant_a.record_id,
        scope=AgentScope.GLOBAL,
        tenant="tenant-a",
    ) == global_tenant_a
    assert store.get(
        repository_missing_root.record_id,
        scope=AgentScope.REPOSITORY,
        tenant="tenant-a",
    ) is None
    assert store.get(
        repository_a.record_id,
        scope=AgentScope.REPOSITORY,
        root=root_a,
        repository_id="repo-a",
        tenant="tenant-a",
    ) == repository_a
    assert store.get(global_record.record_id) == global_record


def test_task_lookup_rejects_rootless_and_tenantless_memory(store: MemoryStore, tmp_path: Path):
    root = str(tmp_path / "repo")
    rootless = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-identity",
        key="task-rootless-identity",
        value="task memory without a root",
        provenance={"tenant": "tenant-a"},
    )
    tenantless = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-identity",
        key="task-tenantless-identity",
        value="task memory without a tenant",
        provenance={"root": root},
    )
    rooted_and_tenant_bound = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-identity",
        key="task-complete-identity",
        value="task memory with complete identity",
        provenance={"root": root, "repository_id": "repo", "tenant": "tenant-a"},
    )
    for record in (rootless, tenantless, rooted_and_tenant_bound):
        _seed_memory_projection(store, record, actor="user")

    assert store.get(
        rootless.record_id,
        scope=AgentScope.TASK,
        task_id="task-identity",
        root=root,
        tenant="tenant-a",
    ) is None
    assert store.get(
        tenantless.record_id,
        scope=AgentScope.TASK,
        task_id="task-identity",
        root=root,
        tenant="tenant-a",
    ) is None
    assert store.find_for_context(root=root, task_id="task-identity", tenant="tenant-a") == [
        rooted_and_tenant_bound
    ]


def test_repository_memory_lookup_requires_root(store: MemoryStore, tmp_path: Path):
    root = str(tmp_path / "repo")
    rootless = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="rootless-repository",
        value="repository memory without root",
        provenance={"tenant": "tenant-a"},
    )
    rooted = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="rooted-repository",
        value="repository memory with root",
        provenance={"root": root, "repository_id": "repo", "tenant": "tenant-a"},
    )
    _seed_memory_projection(store, rootless, actor="user")
    _seed_memory_projection(store, rooted, actor="user")

    assert store.find(scope=AgentScope.REPOSITORY, tenant="tenant-a") == []
    assert store.get(
        rootless.record_id,
        scope=AgentScope.REPOSITORY,
        tenant="tenant-a",
    ) is None
    assert rootless.record_id not in {
        record.record_id
        for record in store.find_for_context(tenant="tenant-a")
    }
    assert store.find(scope=AgentScope.REPOSITORY, root=root, repository_id="repo", tenant="tenant-a") == [rooted]
    assert store.get(
        rooted.record_id,
        scope=AgentScope.REPOSITORY,
        root=root,
        repository_id="repo",
        tenant="tenant-a",
    ) == rooted


def test_find_for_context_enforces_repository_tenant_and_task_identity(store: MemoryStore, tmp_path: Path):
    repo_a = str(tmp_path / "repo-a")
    repo_b = str(tmp_path / "repo-b")
    records = {
        "repo_tenant_a": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="tenant-repo-a",
            value="tenant-a repository memory",
            provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-a"},
        ),
        "repo_tenant_b": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="tenant-repo-b",
            value="tenant-b repository memory",
            provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-b"},
        ),
        "repo_shared": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="shared-repo",
            value="tenantless repository memory",
            provenance={"root": repo_a},
        ),
        "repo_other_root": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="other-root",
            value="other repository memory",
            provenance={"root": repo_b, "repository_id": "repo-b", "tenant": "tenant-b"},
        ),
        "task_tenant_a": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="shared-task-id",
            key="task-tenant-a",
            value="tenant-a task memory",
            provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-a"},
        ),
        "task_tenant_b": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="shared-task-id",
            key="task-tenant-b",
            value="tenant-b task memory",
            provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-b"},
        ),
        "task_other_root": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="shared-task-id",
            key="task-other-root",
            value="other repository task memory",
            provenance={"root": repo_b, "repository_id": "repo-b", "tenant": "tenant-b"},
        ),
        "task_other_id": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="other-task-id",
            key="task-other-id",
            value="other task memory",
            provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-b"},
        ),
        "task_missing_root": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="shared-task-id",
            key="task-missing-root",
            value="task memory without root provenance",
            provenance={"tenant": "tenant-b"},
        ),
        "global_shared": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.GLOBAL,
            key="intentional-global",
            value="explicit global memory",
            provenance={"root": repo_b, "repository_id": "repo-b", "tenant": "tenant-a"},
        ),
        "global_tenant_b": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.GLOBAL,
            key="tenant-b-global",
            value="global within tenant-b",
            provenance={"root": repo_b, "repository_id": "repo-b", "tenant": "tenant-b"},
        ),
        "global_unowned": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.GLOBAL,
            key="unowned-global",
            value="genuinely global memory",
        ),
    }
    for record in records.values():
        _seed_memory_projection(store, record, actor="user")

    found = store.find_for_context(root=repo_a, task_id="shared-task-id", tenant="tenant-b", coordination_id="repo-a")
    found_ids = {record.record_id for record in found}
    assert found_ids == {
        records["repo_tenant_b"].record_id,
        records["task_tenant_b"].record_id,
        records["global_tenant_b"].record_id,
        records["global_unowned"].record_id,
    }

    unscoped_tenant_ids = {
        record.record_id
        for record in store.find_for_context(root=repo_a, task_id="shared-task-id")
    }
    assert records["repo_tenant_a"].record_id not in unscoped_tenant_ids
    assert records["repo_tenant_b"].record_id not in unscoped_tenant_ids
    assert records["task_tenant_a"].record_id not in unscoped_tenant_ids
    assert records["task_tenant_b"].record_id not in unscoped_tenant_ids

    missing_root_ids = {
        record.record_id
        for record in store.find_for_context(task_id="shared-task-id", tenant="tenant-b")
    }
    assert records["task_missing_root"].record_id not in missing_root_ids
    assert records["global_shared"].record_id not in unscoped_tenant_ids
    assert records["global_tenant_b"].record_id not in unscoped_tenant_ids
    assert records["repo_shared"].record_id not in unscoped_tenant_ids
    assert records["global_unowned"].record_id in unscoped_tenant_ids


def test_find_for_context_excludes_stale_expired_and_corrupt_rows(store: MemoryStore, tmp_path: Path):
    repo = str(tmp_path / "repo")
    records = {
        "valid": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="valid",
            value="safe current memory",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "expired": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="expired",
            value="expired memory",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
            expires_at=0.0,
        ),
        "stale": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="stale",
            value="stale memory",
            status=MemoryStatus.STALE,
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "quarantined": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="quarantined",
            value="quarantined memory",
            status=MemoryStatus.QUARANTINED,
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "bad_value": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="bad-value",
            value="well-formed before corruption",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "bad_provenance": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.GLOBAL,
            key="bad-provenance",
            value="global with corrupt provenance",
        ),
        "bad_evidence": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="bad-evidence",
            value="memory with corrupt evidence ids",
            evidence_ids=("evidence-1",),
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
    }
    for record in records.values():
        store.record(record, actor="user")
    with closing(connect_sqlite(store.state_store.db_path, isolation_level=None)) as con:
        con.execute(
            "UPDATE agent_memory_records SET value = ? WHERE record_id = ?",
            ("not-json", records["bad_value"].record_id),
        )
        con.execute(
            "UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?",
            ("not-json", records["bad_provenance"].record_id),
        )
        con.execute(
            "UPDATE agent_memory_records SET evidence_ids = ? WHERE record_id = ?",
            ("not-json", records["bad_evidence"].record_id),
        )

    found = store.find_for_context(root=repo, coordination_id="repo", tenant="tenant-a")
    assert [record.record_id for record in found] == [records["valid"].record_id]
    unscoped = store.find_for_context(root=repo)
    assert records["bad_provenance"].record_id not in {record.record_id for record in unscoped}


def test_find_filters_global_and_repository_rows_by_tenant_and_root(store: MemoryStore, tmp_path: Path):
    repo_a = str(tmp_path / "repo-a")
    repo_b = str(tmp_path / "repo-b")
    records = (
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.GLOBAL, key="global-a", value="a", provenance={"tenant": "tenant-a"}),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.GLOBAL, key="global-b", value="b", provenance={"tenant": "tenant-b"}),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.GLOBAL, key="global-shared", value="shared"),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key="repo-a", value="a", provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-a"}),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key="repo-b", value="b", provenance={"root": repo_a, "repository_id": "repo-a", "tenant": "tenant-b"}),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key="repo-shared", value="shared", provenance={"root": repo_a, "repository_id": "repo-a"}),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key="repo-other-root", value="other", provenance={"root": repo_b, "repository_id": "repo-b", "tenant": "tenant-a"}),
        MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key="repo-rootless", value="legacy", provenance={"tenant": "tenant-a"}),
    )
    for record in records:
        _seed_memory_projection(store, record, actor="user")

    global_for_a = store.find(scope=AgentScope.GLOBAL, tenant="tenant-a", semantic=False)
    assert {record.key for record in global_for_a} == {"global-a", "global-shared"}
    global_without_tenant = store.find(scope=AgentScope.GLOBAL, semantic=False)
    assert {record.key for record in global_without_tenant} == {"global-shared"}
    assert {record.key for record in store.find(semantic=False)} == {"global-shared"}

    repo_for_a = store.find(scope=AgentScope.REPOSITORY, root=repo_a, repository_id="repo-a", tenant="tenant-a", semantic=False)
    assert {record.key for record in repo_for_a} == {"repo-a"}
    repo_without_tenant = store.find(scope=AgentScope.REPOSITORY, root=repo_a, repository_id="repo-a", semantic=False)
    assert repo_without_tenant == []
    repo_without_root = store.find(scope=AgentScope.REPOSITORY, tenant="tenant-a", semantic=False)
    assert repo_without_root == []


def test_find_skips_corrupt_rows_without_aborting_scoped_read(store: MemoryStore, tmp_path: Path):
    repo = str(tmp_path / "repo")
    records = {
        "good": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="good",
            value="safe",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "bad_value": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="bad-value",
            value="replace with invalid JSON",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "bad_evidence": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="bad-evidence",
            value="safe value",
            evidence_ids=("evidence-1",),
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
        "scalar_evidence": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="scalar-evidence",
            value="safe value",
            evidence_ids=("evidence-scalar",),
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
        ),
    }
    for record in records.values():
        store.record(record, actor="user")
    with closing(connect_sqlite(store.state_store.db_path, isolation_level=None)) as con:
        con.execute("UPDATE agent_memory_records SET value = ? WHERE record_id = ?", ("not-json", records["bad_value"].record_id))
        con.execute("UPDATE agent_memory_records SET evidence_ids = ? WHERE record_id = ?", ("not-json", records["bad_evidence"].record_id))
        con.execute("UPDATE agent_memory_records SET evidence_ids = ? WHERE record_id = ?", ('"evidence-scalar"', records["scalar_evidence"].record_id))

    found = store.find(scope=AgentScope.REPOSITORY, root=repo, repository_id="repo", tenant="tenant-a", semantic=False)
    assert [record.record_id for record in found] == [records["good"].record_id]


def test_memory_record_from_dict_rejects_scalar_evidence_ids():
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="evidence-shape",
        value="safe",
    ).to_dict()
    record["evidence_ids"] = "evidence-scalar"

    with pytest.raises(ValueError, match="sequence of strings"):
        MemoryRecord.from_dict(record)


def test_memory_write_redacts_private_fields_and_blocks_sensitive_records(store: MemoryStore, tmp_path: Path):
    repo = str(tmp_path / "repo")
    prompt = "private prompt payload unique-prompt-7c3a"
    source_text = "private source payload unique-source-9d2b"
    raw_text = "private raw payload unique-raw-52af"
    secret = "token=unique-secret-4e1f"
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="safe-key",
        value={
            "safe": "keep this",
            "prompt": prompt,
            "source": source_text,
            "source_text": source_text,
            "raw": raw_text,
            "source_root": source_text,
            "api_key": "unique-api-secret-2f91",
            "nested": {"text": source_text, "stable": secret},
        },
        source="user",
        provenance={
            "root": repo,
            "repository_id": "repo",
            "source_root": repo,
            "tenant": "tenant-a",
            "prompt": prompt,
            "source": source_text,
            "source_text": source_text,
            "raw": raw_text,
            "nested": {"source_root": source_text},
        },
    )
    stored = store.record(record, actor="user", idempotency_key="privacy-record")
    assert stored.value == {"safe": "keep this", "nested": {"stable": "token=[redacted]"}}
    assert stored.provenance == {"root": repo, "repository_id": "repo", "source_root": repo, "tenant": "tenant-a"}

    sensitive = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="sensitive-key",
        value="unique-sensitive-payload-f01a",
        sensitivity="secret",
        provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a"},
    )
    with pytest.raises(ValueError, match="sensitive memory"):
        store.record(sensitive, actor="user", idempotency_key="sensitive-record")

    clean = store.get(stored.record_id, scope=AgentScope.REPOSITORY, root=repo, repository_id="repo", tenant="tenant-a")
    assert clean is not None
    assert clean.value == stored.value
    assert store.find(scope=AgentScope.REPOSITORY, root=repo, repository_id="repo", tenant="tenant-a", semantic=False) == [clean]
    assert store.find_for_context(root=repo, coordination_id="repo", tenant="tenant-a") == [clean]

    with closing(connect_sqlite(store.state_store.db_path, isolation_level=None)) as con:
        con.execute("UPDATE agent_memory_records SET sensitivity = ? WHERE record_id = ?", ("secret", stored.record_id))
        row = con.execute(
            "SELECT value, provenance FROM agent_memory_records WHERE record_id = ?",
            (stored.record_id,),
        ).fetchone()
        event = con.execute("SELECT payload FROM agent_events WHERE idempotency_key = ?", ("privacy-record",)).fetchone()
        fts = con.execute("SELECT key, value FROM agent_memory_fts WHERE record_id = ?", (stored.record_id,)).fetchone()
        sensitive_rows = con.execute(
            "SELECT record_id, key, value, sensitivity, provenance FROM agent_memory_records "
            "WHERE record_id = ? OR key = ? OR value LIKE ?",
            (sensitive.record_id, sensitive.key, "%unique-sensitive-payload-f01a%"),
        ).fetchall()
        sensitive_fts = con.execute(
            "SELECT record_id, key, value FROM agent_memory_fts WHERE key = ? OR value LIKE ?",
            (sensitive.key, "%unique-sensitive-payload-f01a%"),
        ).fetchall()
        sensitive_event_rows = con.execute(
            "SELECT payload FROM agent_events WHERE idempotency_key = ?",
            ("sensitive-record",),
        ).fetchall()
        sensitive_events = con.execute("SELECT COUNT(*) FROM agent_events WHERE idempotency_key = ?", ("sensitive-record",)).fetchone()[0]
    durable_text = json.dumps([row, event, fts, sensitive_rows, sensitive_fts, sensitive_event_rows], sort_keys=True)
    assert prompt not in durable_text
    assert source_text not in durable_text
    assert raw_text not in durable_text
    assert "unique-api-secret-2f91" not in durable_text
    assert "unique-secret-4e1f" not in durable_text
    assert "unique-sensitive-payload-f01a" not in durable_text
    assert sensitive_rows == []
    assert sensitive_fts == []
    assert sensitive_event_rows == []
    assert sensitive_events == 0
    assert store.get(stored.record_id, scope=AgentScope.REPOSITORY, root=repo, repository_id="repo", tenant="tenant-a") is None
    assert store.find(scope=AgentScope.REPOSITORY, root=repo, repository_id="repo", tenant="tenant-a", semantic=False) == []
    assert store.find_for_context(root=repo, coordination_id="repo", tenant="tenant-a") == []


def test_memory_correction_lineage_and_delete_survive_reopen(store: MemoryStore, tmp_path: Path):
    repo = str(tmp_path / "repo")
    previous = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="old-value",
            value="old",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a", "repository_revision": "rev-old"},
        ),
        actor="user",
        idempotency_key="previous-record",
    )
    corrected = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="corrected-value",
            value="new",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": repo, "repository_id": "repo", "tenant": "tenant-a", "repository_revision": "rev-new"},
            expires_at=4102444800.0,
        ),
        actor="user",
        idempotency_key="corrected-record",
    )
    store._save_record(previous.with_superseded_by(corrected.record_id))
    store.record_relation(previous.record_id, "superseded_by", corrected.record_id)

    reopened = MemoryStore(AgentStateStore(store.state_store.db_path))
    restored_previous = reopened.get(
        previous.record_id,
        include_expired=True,
        **_repository_identity(previous),
    )
    restored_corrected = reopened.get(
        corrected.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id="",
        root=repo,
        repository_id="repo",
        tenant="tenant-a",
    )
    assert restored_previous is not None
    assert restored_previous.status is MemoryStatus.SUPERSEDED
    assert restored_previous.supersedes_record_id == corrected.record_id
    assert restored_corrected is not None
    serialized = restored_corrected.to_dict()
    assert serialized["scope"] == AgentScope.REPOSITORY.value
    assert serialized["source"] == "user"
    assert serialized["expires_at"] == 4102444800.0
    assert serialized["provenance"]["repository_revision"] == "rev-new"
    assert reopened.find_for_context(root=repo, coordination_id="repo", tenant="tenant-a") == [restored_corrected]
    assert reopened.find_relations(entity=previous.record_id, relation="superseded_by")

    assert reopened.delete(
        corrected.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id="",
        root=repo,
        repository_id="repo",
        tenant="tenant-a",
    )
    assert reopened.get(
        corrected.record_id,
        include_expired=True,
        scope=AgentScope.REPOSITORY,
        scope_id="",
        root=repo,
        repository_id="repo",
        tenant="tenant-a",
    ) is None
    assert reopened.find_relations(entity=previous.record_id, relation="superseded_by") == []
    with closing(connect_sqlite(reopened.state_store.db_path)) as con:
        event_count = con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE idempotency_key = ?",
            ("corrected-record",),
        ).fetchone()[0]
    assert event_count == 1


def test_scoped_memory_delete_still_enforces_tenant(store: MemoryStore):
    session_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        key="session-delete-tenant",
        value="scoped value",
        provenance={"tenant": "codex"},
    ), actor="user")

    assert store.delete(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        tenant="other-tenant",
    ) is False
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
    ) is None
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        tenant="other-tenant",
    ) is None
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        tenant="codex",
    ) == session_record


def test_global_memory_delete_ignores_transport_tenant_but_keeps_scope(store: MemoryStore, tmp_path: Path):
    repo = tmp_path / "repo-a"
    other_repo = tmp_path / "repo-b"
    repo.mkdir()
    other_repo.mkdir()
    global_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="global-delete-tenant",
        value="global value",
        provenance={"root": str(repo), "repository_id": "repo-a"},
    ), actor="user")

    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        root=str(repo),
        repository_id="repo-a",
        tenant="codex",
    ) == global_record
    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        root=str(repo),
        repository_id="repo-a",
        tenant="other-tenant",
    ) == global_record
    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        root=str(other_repo),
        repository_id="repo-a",
        tenant="codex",
    ) is None
    assert store.delete(
        global_record.record_id,
        scope=global_record.scope,
        scope_id=global_record.scope_id,
        root=str(repo),
        repository_id="repo-a",
        tenant="other-tenant",
    ) is True

    session_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        key="tenant-delete-guard",
        value="tenant value",
        provenance={"tenant": "codex"},
    ), actor="user")
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        tenant="other-tenant",
    ) is None
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="session-codex",
        tenant="codex",
    ) == session_record


def test_scoped_memory_delete_requires_matching_tenant(store: MemoryStore):
    record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.SESSION,
        scope_id="session-owner",
        key="tenant-delete-identity",
        value="tenant private value",
        provenance={"tenant": "owner-tenant"},
    ), actor="user")

    assert store.delete(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
    ) is False
    assert store.delete(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        tenant="other-tenant",
    ) is False
    assert store.get(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        tenant="owner-tenant",
    ) == record
    assert store.delete(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        tenant="owner-tenant",
    ) is True
    assert store.get(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        tenant="owner-tenant",
    ) is None


def test_global_memory_get_enforces_tenant_and_other_identity(store: MemoryStore, tmp_path: Path):
    repo = tmp_path / "repo"
    global_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.GLOBAL,
        key="global-codex-contract",
        value="global value",
        provenance={"root": str(repo), "repository_id": "repo-global", "tenant": "tenant-a"},
    ))

    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        tenant="tenant-a",
        root=str(repo),
        repository_id="repo-global",
    ) == global_record
    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        tenant="codex",
        root=str(repo),
        repository_id="repo-global",
    ) is None
    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        tenant="codex",
        root=str(tmp_path / "other-repo"),
        repository_id="repo-global",
    ) is None
    assert store.get(
        global_record.record_id,
        scope=AgentScope.GLOBAL,
        tenant="codex",
        root=str(repo),
        repository_id="other-repository",
    ) is None

    session_record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.SESSION,
        scope_id="codex",
        key="tenant-scoped-contract",
        value="tenant value",
        provenance={"tenant": "codex"},
    ))
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="codex",
        tenant="codex",
    ) == session_record
    assert store.get(
        session_record.record_id,
        scope=AgentScope.SESSION,
        scope_id="codex",
        tenant="other-tenant",
    ) is None


def test_memory_identity_indexes_exist_for_bounded_filtered_queries(store: MemoryStore):
    con = connect_sqlite(store.state_store.db_path)
    try:
        names = {str(row[1]) for row in con.execute("PRAGMA index_list(agent_memory_records)").fetchall()}
    finally:
        con.close()
    assert {
        "idx_agent_memory_scope_identity",
        "idx_agent_memory_provenance_root",
        "idx_agent_memory_provenance_repository",
        "idx_agent_memory_provenance_tenant",
        "idx_agent_memory_provenance_clone_id",
        "idx_agent_memory_provenance_worktree_id",
        "idx_agent_memory_provenance_branch",
    } <= names


def test_memory_query_limit_is_hard_capped(store: MemoryStore):
    for index in range(101):
        store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.GLOBAL,
                key=f"bounded-{index}",
                value=index,
            ),
            idempotency_key=f"bounded-{index}",
        )

    store.max_query_limit = 10_000
    assert len(store.find(scope=AgentScope.GLOBAL, limit=100_000)) == 100
    with pytest.raises(ValueError, match="memory limit"):
        store.find(scope=AgentScope.GLOBAL, limit="invalid")


def test_global_promotion_requires_user_approval(store: MemoryStore):
    record = confirmed_repository_record(store)
    with pytest.raises(KeyError):
        store.promote(record.record_id, AgentScope.GLOBAL, approver="user")
    with pytest.raises(KeyError):
        store.promote(
            record.record_id,
            AgentScope.GLOBAL,
            approver="user",
            **{**_repository_identity(record), "tenant": "other-tenant"},
        )
    with pytest.raises(ApprovalRequiredError):
        store.promote(
            record.record_id,
            AgentScope.GLOBAL,
            approver="agent",
            **_repository_identity(record),
        )


def test_global_promotion_succeeds_with_user_approval(store: MemoryStore):
    record = confirmed_repository_record(store)
    promoted = store.promote(
        record.record_id,
        AgentScope.GLOBAL,
        approver="user",
        **_repository_identity(record),
    )
    assert promoted.scope is AgentScope.GLOBAL
    assert promoted.status is MemoryStatus.CONFIRMED


def test_promotion_requires_matching_repository_identity(store: MemoryStore):
    record = confirmed_repository_record(store)
    with pytest.raises(KeyError, match="not found"):
        store.promote(
            record.record_id,
            AgentScope.GLOBAL,
            approver="user",
            scope=AgentScope.REPOSITORY,
            root="C:/repository",
            tenant="another-tenant",
        )


def test_conflicting_high_confidence_records_are_quarantined(store: MemoryStore):
    r1 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="database_port",
        value=5432,
        confidence=0.95,
        source="config",
        status=MemoryStatus.CONFIRMED,
    )
    store.record(r1, actor="user", idempotency_key="r1")

    r2 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="database_port",
        value=3306,
        confidence=0.90,
        source="log",
        status=MemoryStatus.CONFIRMED,
    )
    saved_r2 = store.record(r2, actor="user", idempotency_key="r2")
    assert saved_r2.status is MemoryStatus.QUARANTINED
    assert "conflict" in (saved_r2.quarantine_reason or "").lower()


@pytest.mark.parametrize("scope", [AgentScope.TASK, AgentScope.SESSION])
def test_conflicts_are_isolated_by_scope_id(store: MemoryStore, scope: AgentScope):
    first = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=scope,
            scope_id="scope-one",
            key="isolated-key",
            value="one",
            confidence=0.95,
            status=MemoryStatus.CONFIRMED,
        ),
        actor="user",
        idempotency_key=f"{scope.value}-one",
    )
    second = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=scope,
            scope_id="scope-two",
            key="isolated-key",
            value="two",
            confidence=0.95,
            status=MemoryStatus.CONFIRMED,
        ),
        actor="user",
        idempotency_key=f"{scope.value}-two",
    )

    assert first.status is MemoryStatus.CONFIRMED
    assert second.status is MemoryStatus.CONFIRMED


def test_repository_conflicts_are_isolated_by_root(store: MemoryStore, tmp_path: Path):
    root_one = tmp_path / "repo-one"
    root_two = tmp_path / "repo-two"
    root_one.mkdir()
    root_two.mkdir()
    for root, value, key in ((root_one, "one", "repo-one"), (root_two, "two", "repo-two")):
        record = store.record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.REPOSITORY,
                scope_id=key,
                key="root-isolated-key",
                value=value,
                confidence=0.95,
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(root)},
            ),
            actor="user",
            idempotency_key=key,
        )
        assert record.status is MemoryStatus.CONFIRMED


def test_task_conflicts_are_isolated_by_provenance_root(store: MemoryStore, tmp_path: Path):
    for index in range(2):
        record = store.record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.TASK,
                scope_id="same-task",
                key="root-aware-task-key",
                value=index,
                confidence=0.95,
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(tmp_path / f"repo-{index}")},
            ),
            idempotency_key=f"root-aware-task-{index}",
        )
        assert record.status is MemoryStatus.CONFIRMED


def test_consistency_memory_kinds_round_trip():
    kinds = (
        MemoryKind.FINDING,
        MemoryKind.REUSABLE_CANDIDATE,
        MemoryKind.CONTRACT_MAPPING,
        MemoryKind.REJECTED_APPROACH,
        MemoryKind.UNKNOWN,
        MemoryKind.VALIDATION,
    )
    for kind in kinds:
        record = MemoryRecord.create(kind=kind, scope=AgentScope.TASK, key=kind.value, value={"kind": kind.value})
        restored = MemoryRecord.from_dict(record.to_dict())
        assert restored.kind is kind


def test_record_idempotency_reuses_existing_record(store: MemoryStore):
    first = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            key="same-request",
            value="first",
            scope_id="task-1",
        ),
        actor="agent",
        idempotency_key="memory-request-1",
    )
    second = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            key="same-request",
            value="second",
            scope_id="task-1",
        ),
        actor="agent",
        idempotency_key="memory-request-1",
    )

    assert second.record_id == first.record_id
    assert store.count() == 1
    assert [event.kind for event in store.state_store.events(
        stream_id=memory_event_stream_id(AgentScope.TASK, "task-1", "same-request")
    )].count("memory.recorded") == 1


def test_evidence_memory_persists_revision_metadata_and_is_idempotent(store: MemoryStore, tmp_path: Path):
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        scope_id="repo",
        key="guard:finding:stable:rev-1",
        value={"status": "verified", "evidence_ids": ["ev-1"]},
        evidence_ids=("ev-1",),
        provenance={"repository_id": 'repo-evidence', "root": str(tmp_path), "tenant": "tenant-a"},
        repository_revision="rev-1",
        path_refs=("src/app.py",),
        symbol_refs=("App.run",),
        related_task="task-1",
        expires_at=9999999999.0,
    )
    first = store.record(record, idempotency_key="guard:finding:stable:rev-1")
    second = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            scope_id="repo",
            key="guard:finding:stable:rev-1",
            value={"status": "changed"},
            repository_revision="rev-1",
            provenance={"repository_id": 'repo-evidence', "root": str(tmp_path), "tenant": "tenant-a"},
        ),
        idempotency_key="guard:finding:stable:rev-1",
    )
    restored = store.get(
        first.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id="repo",
        repository_id='repo-evidence', root=str(tmp_path),
        tenant="tenant-a",
    )

    assert second.record_id == first.record_id
    assert restored is not None
    assert restored.repository_revision == "rev-1"
    assert restored.path_refs == ("src/app.py",)
    assert restored.symbol_refs == ("App.run",)
    assert restored.related_task == "task-1"


def test_record_idempotency_is_atomic_under_concurrency(store: MemoryStore):
    def record_attempt(index: int) -> str:
        saved = store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.TASK,
                key="concurrent",
                value=index,
                scope_id="task-concurrent",
            ),
            actor="agent",
            idempotency_key="memory-concurrent-1",
        )
        return saved.record_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        record_ids = list(executor.map(record_attempt, range(4)))

    assert len(set(record_ids)) == 1
    assert store.count() == 1
    assert [event.kind for event in store.state_store.events(
        stream_id=memory_event_stream_id(AgentScope.TASK, "task-concurrent", "concurrent")
    )].count("memory.recorded") == 1


def test_conflicting_high_confidence_insert_is_atomic_under_concurrency(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    stores = [
        MemoryStore(AgentStateStore(db_path)),
        MemoryStore(AgentStateStore(db_path)),
    ]

    def record_attempt(index: int) -> MemoryRecord:
        return stores[index].record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.REPOSITORY,
                scope_id="repo",
                key="concurrent-conflict",
                value=index,
                confidence=0.95,
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(tmp_path / "repo")},
            ),
            actor="agent",
            idempotency_key=f"conflict-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        saved = list(executor.map(record_attempt, range(2)))

    assert sum(item.status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED) for item in saved) == 1
    assert sum(item.status is MemoryStatus.QUARANTINED for item in saved) == 1

def test_repository_revision_is_preserved_in_provenance(store: MemoryStore, tmp_path: Path):
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="parser",
        value="uses Pratt parsing",
        provenance={
            "repository_id": 'repo-evidence', "root": str(tmp_path),
            "tenant": "tenant-a",
            "repository_revision": "rev-1",
            "path_refs": ["src/parser.py"],
            "symbol_refs": ["Parser.parse"],
            "related_task": "task-1",
        },
    )

    saved = store.record(record)
    restored = store.get(
        saved.record_id,
        scope=AgentScope.REPOSITORY,
        repository_id='repo-evidence', root=str(tmp_path),
        tenant="tenant-a",
    )

    assert restored is not None
    assert restored.repository_revision == "rev-1"
    assert restored.path_refs == ("src/parser.py",)
    assert restored.symbol_refs == ("Parser.parse",)
    assert restored.provenance["related_task"] == "task-1"


def test_mark_stale_for_revision_preserves_metadata_and_emits_event(store: MemoryStore, tmp_path: Path):
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="parser",
            value="old evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "repository_id": 'repo-evidence', "root": str(tmp_path),
                "tenant": "tenant-a",
                "repository_revision": "rev-1",
                "path_refs": ["src/parser.py"],
            },
        )
    )

    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/parser.py"]) == 1

    stale = store.get(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        repository_id='repo-evidence', root=str(tmp_path),
        tenant="tenant-a",
    )
    assert stale is not None
    assert stale.status is MemoryStatus.STALE
    assert stale.provenance["repository_revision"] == "rev-1"
    assert stale.provenance["staled_by_revision"] == "rev-2"
    assert stale.provenance["superseded_metadata"]["status"] == "confirmed"
    stream_parts = (AgentScope.REPOSITORY.value, "", "parser")
    stream_id = "memory:" + "".join(f"{len(part)}:{part}" for part in stream_parts)
    assert any(event.kind == "memory.staled" for event in store.state_store.events(stream_id=stream_id))


def test_mark_stale_for_revision_guards_revision_paths_root_and_repeats(store: MemoryStore, tmp_path: Path):
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="guarded",
            value="evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "repository_id": 'repo-evidence', "root": str(tmp_path),
                "tenant": "tenant-a",
                "repository_revision": "rev-1",
                "path_refs": ["src/guarded.py"],
            },
        )
    )

    assert store.mark_stale_for_revision(str(tmp_path), "rev-1", ["src/guarded.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/other.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["other/src/guarded.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path / "other"), "rev-2", ["src/guarded.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", None) == 0

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/guarded.py"]),
            range(2),
        ))

    assert sorted(results) == [0, 1]
    stream_parts = (AgentScope.REPOSITORY.value, "", "guarded")
    stream_id = "memory:" + "".join(f"{len(part)}:{part}" for part in stream_parts)
    events = store.state_store.events(stream_id=stream_id)
    assert [event.kind for event in events].count("memory.staled") == 1
    assert store.get(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        repository_id='repo-evidence', root=str(tmp_path),
        tenant="tenant-a",
    ).status is MemoryStatus.STALE


def test_mark_stale_for_revision_matches_beyond_100k_rows(store: MemoryStore, tmp_path: Path):
    root = str(tmp_path)
    rows = [
        (
            f"bulk-{index}",
            MemoryKind.FINDING.value,
            AgentScope.REPOSITORY.value,
            "",
            f"bulk-{index}",
            json.dumps("unrelated"),
            MemoryStatus.CONFIRMED.value,
            1.0,
            "agent",
            "[]",
            "normal",
            None,
            None,
            None,
            json.dumps({"repository_id": 'repo-evidence', "root": root, "tenant": "tenant-a", "repository_revision": "rev-1", "path_refs": [f"src/other-{index}.py"]}),
            float(index + 2),
            float(index + 2),
            None,
        )
        for index in range(100_000)
    ]
    rows.append(
        (
            "bulk-match",
            MemoryKind.FINDING.value,
            AgentScope.REPOSITORY.value,
            "",
            "bulk-match",
            json.dumps("matching"),
            MemoryStatus.CONFIRMED.value,
            1.0,
            "agent",
            "[]",
            "normal",
            None,
            None,
            None,
            json.dumps({"repository_id": 'repo-evidence', "root": root, "tenant": "tenant-a", "repository_revision": "rev-1", "path_refs": ["src/match.py"]}),
            1.0,
            1.0,
            None,
        )
    )
    con = connect_sqlite(store.state_store.db_path)
    try:
        con.executemany(
            """
            INSERT INTO agent_memory_records (
                record_id, kind, scope, scope_id, key, value, status, confidence, source,
                evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                quarantine_reason, provenance, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
    finally:
        con.close()

    assert store.mark_stale_for_revision(root, "rev-2", ["src/match.py"]) == 1
    assert store.get("bulk-match", scope=AgentScope.REPOSITORY, repository_id='repo-evidence', root=root, tenant="tenant-a").status is MemoryStatus.STALE


def test_mark_stale_for_revision_matches_relative_and_absolute_roots(store: MemoryStore, tmp_path: Path):
    relative_root = os.path.relpath(tmp_path, Path.cwd())
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="relative-root",
            value="evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "repository_id": 'repo-evidence', "root": relative_root,
                "tenant": "tenant-a",
                "repository_revision": "rev-1",
                "path_refs": ["src/relative.py"],
            },
        )
    )

    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/relative.py"]) == 1
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY, repository_id='repo-evidence', root=str(tmp_path), tenant="tenant-a").status is MemoryStatus.STALE


def test_mark_stale_for_revision_deduplicates_and_caps_changed_paths(store: MemoryStore, tmp_path: Path):
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="bounded-paths",
            value="evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "repository_id": 'repo-evidence', "root": str(tmp_path),
                "tenant": "tenant-a",
                "repository_revision": "rev-1",
                "path_refs": ["src/match.py"],
            },
        )
    )
    changed_paths = [None, "None", "src/match.py", "src/match.py"] + [
        f"src/other-{index}.py" for index in range(64)
    ]

    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", changed_paths) == 1
    stale = store.get(record.record_id, scope=AgentScope.REPOSITORY, repository_id='repo-evidence', root=str(tmp_path), tenant="tenant-a")
    assert stale is not None
    bounded_paths = stale.provenance["staled_changed_paths"]
    assert len(bounded_paths) == 32
    assert len(set(bounded_paths)) == len(bounded_paths)
    assert "None" not in bounded_paths


def test_mark_stale_batch_rolls_back_and_repeats_idempotently(store: MemoryStore, tmp_path: Path, monkeypatch):
    records = [
        store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.REPOSITORY,
                key=f"batch-{index}",
                value="evidence",
                status=MemoryStatus.CONFIRMED,
                provenance={
                    "repository_id": 'repo-evidence', "root": str(tmp_path),
                    "tenant": "tenant-a",
                    "repository_revision": "rev-1",
                    "path_refs": [f"src/batch-{index}.py"],
                },
            )
        )
        for index in range(2)
    ]
    original_create = AgentEvent.create
    calls = 0

    def fail_on_second_create(cls, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected batch failure")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(AgentEvent, "create", classmethod(fail_on_second_create))
    with pytest.raises(RuntimeError, match="injected batch failure"):
        store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/batch-0.py", "src/batch-1.py"])

    assert [store.get(record.record_id, scope=AgentScope.REPOSITORY, repository_id='repo-evidence', root=str(tmp_path), tenant="tenant-a").status for record in records] == [
        MemoryStatus.CONFIRMED,
        MemoryStatus.CONFIRMED,
    ]
    assert all(
        not [event for event in store.state_store.events(
            stream_id=f"memory:{AgentScope.REPOSITORY.value}:batch-{index}"
        ) if event.kind == "memory.staled"]
        for index in range(2)
    )

    count = store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/batch-0.py", "src/batch-1.py"])
    assert count == 2
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/batch-0.py", "src/batch-1.py"]) == 0


def test_delete_rejects_repository_record_with_missing_root_provenance(store: MemoryStore):
    root = Path.cwd()
    record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="missing-root-provenance",
        value="must remain",
        provenance={"tenant": "tenant-a"},
    ))

    deleted = store.delete(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        root=str(root),
        tenant="tenant-a",
    )

    assert deleted is False
    # Retention is a storage invariant, not permission for an unscoped read.
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        row = con.execute(
            "SELECT scope, provenance FROM agent_memory_records WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == AgentScope.REPOSITORY.value
    assert json.loads(row[1]) == record.provenance
    assert store.get(record.record_id) is None
def test_memory_write_failure_rolls_back_record_event_and_cursor(store: MemoryStore, monkeypatch):
    idempotency_key = "memory-write-rollback"
    stream_ids: list[str] = []
    append_in_transaction = store.state_store.append_in_transaction
    save_record_row = store._save_record_row

    def capture_append(con, event, **kwargs):
        stream_ids.append(event.stream_id)
        result = append_in_transaction(con, event, **kwargs)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
            (event.stream_id, idempotency_key),
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT last_seq FROM agent_event_cursors WHERE stream_id = ?",
            (event.stream_id,),
        ).fetchone() == (1,)
        return result

    def fail_after_record_insert(con, record):
        save_record_row(con, record)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_records WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()[0] == 1
        raise RuntimeError("injected failure after memory and event writes")

    monkeypatch.setattr(store.state_store, "append_in_transaction", capture_append)
    monkeypatch.setattr(store, "_save_record_row", fail_after_record_insert)
    with pytest.raises(RuntimeError, match="injected failure"):
        store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.TASK,
                scope_id="task-rollback",
                key="rollback-memory",
                value={"safe": "transactional"},
            ),
            idempotency_key=idempotency_key,
        )

    assert len(stream_ids) == 1
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        record_count = con.execute(
            "SELECT COUNT(*) FROM agent_memory_records WHERE key = ?",
            ("rollback-memory",),
        ).fetchone()[0]
        event_count = con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()[0]
        cursor_count = con.execute(
            "SELECT COUNT(*) FROM agent_event_cursors WHERE stream_id = ?",
            (stream_ids[0],),
        ).fetchone()[0]
    assert record_count == 0
    assert event_count == 0
    assert cursor_count == 0
def test_session_memory_requires_exact_session_and_tenant(store: MemoryStore):
    def seed(key: str, scope_id: str, tenant: str | None) -> MemoryRecord:
        provenance = {"tenant": tenant, "root": "C:/repo"} if tenant else {"root": "C:/repo"}
        record = MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.SESSION,
            scope_id=scope_id,
            key=key,
            value=key,
            provenance=provenance,
        )
        store.record(record, actor="user")
        return record

    own_session = seed("own-session", "session-1", "tenant-1")
    other_tenant = seed("other-tenant", "session-1", "tenant-2")
    other_session = seed("other-session", "session-2", "tenant-1")
    missing_tenant = seed("missing-tenant", "session-1", None)
    tenant_as_session = seed("tenant-as-session", "tenant-1", "tenant-1")

    assert store.find(
        scope=AgentScope.SESSION,
        scope_id="session-1",
        tenant="tenant-1",
    ) == []
    assert [record.record_id for record in store.find(
        scope=AgentScope.SESSION,
        session_id="session-1",
        tenant="tenant-1",
    )] == [own_session.record_id]
    assert [record.record_id for record in store.find(
        scope=AgentScope.SESSION,
        session_id="session-1",
        tenant="tenant-2",
    )] == [other_tenant.record_id]
    assert store.find(scope=AgentScope.SESSION, session_id="session-1") == []

    assert [record.record_id for record in store.find_for_context(
        root="C:/repo",
        session_id="session-1",
        tenant="tenant-1",
    )] == [own_session.record_id]
    assert [record.record_id for record in store.find_for_context(
        root="C:/repo",
        session_id="session-1",
        tenant="tenant-2",
    )] == [other_tenant.record_id]
    assert store.find_for_context(session_id="session-1") == []
    assert store.find_for_context(tenant="tenant-1") == []


def test_t08_root_scoped_promotion_contract(store: MemoryStore):
    record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY,
        scope_id="repo-t08", key="t08-promote", value="verified",
        status=MemoryStatus.CONFIRMED,
        provenance={"repository_id": 'repo-evidence', "root": "C:/repo", "tenant": "tenant-a"},
    ), actor="user")
    identity = dict(scope=AgentScope.REPOSITORY, scope_id="repo-t08",
                    repository_id='repo-evidence', root="C:/repo", tenant="tenant-a")
    for mismatch in ({"repository_id": "other"}, {"tenant": "other"}):
        with pytest.raises(KeyError, match="not found"):
            store.promote(record.record_id, AgentScope.GLOBAL, approver="user",
                          **(identity | mismatch))
    promoted = store.promote(record.record_id, AgentScope.GLOBAL,
                             approver="user", **identity)
    assert promoted.scope is AgentScope.GLOBAL
    assert promoted.status is MemoryStatus.CONFIRMED


def test_t08_root_repository_lookup_without_scope_id(store: MemoryStore):
    record = store.record(MemoryRecord.create(
        kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY,
        scope_id="repo-t08", key="t08-scoped-lookup", value="verified",
        provenance={"repository_id": 'repo-evidence', "root": "C:/repo", "tenant": "tenant-a"},
    ), actor="user")
    found = store.get(record.record_id, scope=AgentScope.REPOSITORY,
                      repository_id='repo-evidence', root="C:/repo", tenant="tenant-a")
    assert found is not None and found.record_id == record.record_id
    shared_worktree = store.get(
        record.record_id, scope=AgentScope.REPOSITORY,
        repository_id="repo-evidence", root="C:/other", tenant="tenant-a",
    )
    assert shared_worktree is not None and shared_worktree.record_id == record.record_id
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY,
                     repository_id="other-repository", root="C:/repo", tenant="tenant-a") is None
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY,
                     repository_id='repo-evidence', root="C:/repo", tenant="other") is None
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY,
                     tenant="tenant-a") is None


def test_session_id_cannot_substitute_for_tenant(store: MemoryStore):
    record = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="session-memory",
        value="session memory",
        provenance={"tenant": "tenant-1"},
    ))

    assert store.find(
        scope=AgentScope.SESSION,
        session_id="session-1",
        key="session-memory",
    ) == []
    assert store.find(
        scope=AgentScope.SESSION,
        session_id="session-1",
        tenant="tenant-2",
        key="session-memory",
    ) == []
    assert store.find(
        scope=AgentScope.SESSION,
        scope_id="session-1",
        tenant="tenant-1",
        key="session-memory",
    ) == []
    assert [item.record_id for item in store.find(
        scope=AgentScope.SESSION,
        session_id="session-1",
        tenant="tenant-1",
        key="session-memory",
    )] == [record.record_id]


def test_find_for_context_task_memory_requires_root_task_and_tenant(store: MemoryStore, tmp_path: Path):
    root = tmp_path / "task-repo"
    root.mkdir()
    record = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-1",
        key="task-memory",
        value="private task memory",
        status=MemoryStatus.CONFIRMED,
        provenance={"root": str(root), "task_id": "task-1", "tenant": "tenant-1"},
    ))
    _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-1",
        key="legacy-task-memory",
        value="unrooted task memory",
        status=MemoryStatus.CONFIRMED,
        provenance={"task_id": "task-1", "tenant": "tenant-1"},
    ))

    assert store.find_for_context(task_id="task-1", tenant="tenant-1") == []
    assert store.find_for_context(root=str(root), task_id="task-1") == []
    assert store.find_for_context(root=str(root), task_id="task-1", tenant="tenant-2") == []
    assert store.find_for_context(root=str(root), task_id="task-1", tenant="tenant-1") == [record]


def test_find_for_context_session_memory_requires_session_and_tenant(store: MemoryStore):
    session_one = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="session-one",
        value="tenant one session one",
        provenance={"tenant": "tenant-1"},
    ))
    other_session = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-2",
        key="session-two",
        value="tenant one session two",
        provenance={"tenant": "tenant-1"},
    ))
    other_tenant = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="foreign-session",
        value="tenant two session one",
        provenance={"tenant": "tenant-2"},
    ))
    missing_tenant = _seed_memory_projection(store, MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="unowned-session",
        value="missing tenant provenance",
    ))

    assert [record.record_id for record in store.find_for_context(session_id="session-1", tenant="tenant-1")] == [session_one.record_id]
    assert [record.record_id for record in store.find_for_context(session_id="session-2", tenant="tenant-1")] == [other_session.record_id]
    assert store.find_for_context(tenant="tenant-1") == []
    assert store.find_for_context(session_id="session-1") == []
    assert {other_tenant.record_id, missing_tenant.record_id}.isdisjoint(
        record.record_id for record in store.find_for_context(session_id="session-1", tenant="tenant-1")
    )


def test_memory_record_updates_event_cursor_and_replay_keeps_sequence(store: MemoryStore):
    first = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="cursor-record",
            value="first",
        ),
        actor="user",
        idempotency_key="cursor-record",
    )
    stream_parts = (AgentScope.REPOSITORY.value, "", "cursor-record")
    stream_id = "memory:" + "".join(f"{len(part)}:{part}" for part in stream_parts)
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        event_seq = con.execute(
            "SELECT seq FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
            (stream_id, "cursor-record"),
        ).fetchone()
        cursor = con.execute(
            "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
            (stream_id,),
        ).fetchone()
    assert event_seq == (1,)
    assert cursor == (1, 1)

    replay = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="cursor-record",
            value="changed replay payload",
        ),
        actor="user",
        idempotency_key="cursor-record",
    )
    assert replay.record_id == first.record_id
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        assert con.execute(
            "SELECT last_seq FROM agent_event_cursors WHERE stream_id = ?",
            (stream_id,),
        ).fetchone() == (1,)


def test_memory_record_append_failure_rolls_back_record_event_and_cursor(store: MemoryStore, monkeypatch):
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="cursor-rollback",
        value="must roll back",
    )
    append = store.state_store.append_in_transaction

    def append_then_fail(con, event, **kwargs):
        append(con, event, **kwargs)
        raise RuntimeError("injected memory append failure")

    monkeypatch.setattr(store.state_store, "append_in_transaction", append_then_fail)
    with pytest.raises(RuntimeError, match="injected memory append failure"):
        store.record(record, actor="user", idempotency_key="cursor-rollback")

    stream_parts = (AgentScope.REPOSITORY.value, "", "cursor-rollback")
    stream_id = "memory:" + "".join(f"{len(part)}:{part}" for part in stream_parts)
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_records WHERE record_id = ?",
            (record.record_id,),
        ).fetchone() == (0,)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
            (stream_id, "cursor-rollback"),
        ).fetchone() == (0,)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_event_cursors WHERE stream_id = ?",
            (stream_id,),
        ).fetchone() == (0,)


def test_mark_stale_appends_memory_event_and_advances_cursor(store: MemoryStore, tmp_path: Path):
    store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="cursor-stale",
            value="old evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "root": str(tmp_path),
                "repository_revision": "rev-1",
                "path_refs": ["src/parser.py"],
            },
        )
    )
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/parser.py"]) == 1
    stream_parts = (AgentScope.REPOSITORY.value, "", "cursor-stale")
    stream_id = "memory:" + "".join(f"{len(part)}:{part}" for part in stream_parts)
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        assert con.execute(
            "SELECT last_seq FROM agent_event_cursors WHERE stream_id = ?",
            (stream_id,),
        ).fetchone() == (2,)
        assert con.execute(
            "SELECT kind FROM agent_events WHERE stream_id = ? ORDER BY seq",
            (stream_id,),
        ).fetchall() == [("memory.recorded",), ("memory.staled",)]


def test_get_global_requires_unowned_or_matching_tenant(store: MemoryStore, tmp_path: Path):
    root = str(tmp_path / "repo")
    global_unowned = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.GLOBAL,
        key="global-unowned-get",
        value="shared global memory",
    )
    global_tenant = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.GLOBAL,
        key="global-tenant-get",
        value="tenant memory",
        provenance={"tenant": "tenant-a"},
    )
    global_rooted = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.GLOBAL,
        key="global-rooted-get",
        value="repository-bound global memory",
        provenance={"root": root},
    )
    global_scoped_id = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.GLOBAL,
        scope_id="tenant-a",
        key="global-scope-id-get",
        value="identity-bound global memory",
    )
    repository = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="repository-get",
        value="repository memory",
        provenance={"root": root, "repository_id": "repo", "tenant": "tenant-a"},
    )
    task = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-a",
        key="task-get",
        value="task memory",
        provenance={"root": root, "repository_id": "repo", "tenant": "tenant-a"},
    )
    for record in (global_unowned, global_tenant, global_rooted, global_scoped_id, repository, task):
        store._save_record(record)

    assert store.get(global_unowned.record_id) == global_unowned
    assert store.get(global_tenant.record_id) is None
    assert store.get(global_tenant.record_id, scope=AgentScope.GLOBAL) is None
    assert store.get(global_tenant.record_id, scope=AgentScope.GLOBAL, tenant="tenant-b") is None
    assert store.get(global_tenant.record_id, scope=AgentScope.GLOBAL, tenant="tenant-a") == global_tenant
    assert store.get(global_rooted.record_id, scope=AgentScope.GLOBAL) is None
    assert store.get(global_scoped_id.record_id) is None
    assert store.get(global_scoped_id.record_id, scope=AgentScope.GLOBAL, tenant="tenant-a") is None
    assert store.get(repository.record_id, scope=AgentScope.REPOSITORY) is None
    assert store.get(repository.record_id, scope=AgentScope.REPOSITORY, repository_id='repo', root=root, tenant="tenant-b") is None
    assert store.get(repository.record_id, scope=AgentScope.REPOSITORY, repository_id='repo', root=root, tenant="tenant-a") == repository
    assert store.get(task.record_id, scope=AgentScope.TASK, root=root, tenant="tenant-a") is None
    assert store.get(task.record_id, scope=AgentScope.TASK, task_id="task-a", root=root, tenant="tenant-b") is None
    assert store.get(task.record_id, scope=AgentScope.TASK, task_id="task-a", root=root, tenant="tenant-a") == task
    # GLOBAL delete ignores transport tenant; read remains owner-tenant scoped.
    assert store.delete(global_tenant.record_id, scope=AgentScope.GLOBAL, tenant="tenant-b") is True
    assert store.get(global_tenant.record_id, scope=AgentScope.GLOBAL, tenant="tenant-a") is None
    assert store.delete(global_rooted.record_id, scope=AgentScope.GLOBAL, root=str(tmp_path / "other")) is False
    assert store.delete(global_rooted.record_id, scope=AgentScope.GLOBAL, root=root) is True
    assert store.delete(global_scoped_id.record_id, scope=AgentScope.GLOBAL, scope_id="tenant-a", tenant="tenant-a") is False

