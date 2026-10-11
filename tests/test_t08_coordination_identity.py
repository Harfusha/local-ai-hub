from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.task_context import build_context_request


def build_memory_store(tmp_path: Path) -> MemoryStore:
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return MemoryStore(state)


def add_scoped_memory(
    store: MemoryStore,
    *,
    root: Path,
    tenant: str,
    key: str,
    scope: AgentScope = AgentScope.REPOSITORY,
    scope_id: str | None = None,
    coordination_id: str | None = None,
    repository_revision: str | None = None,
    path_refs: tuple[str, ...] = (),
) -> MemoryRecord:
    provenance = {"root": str(root), "tenant": tenant}
    if coordination_id is not None:
        # Persist trusted coordination under the existing repository identity
        # field; the fixture never derives this opaque value.
        provenance["repository_id"] = coordination_id
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=scope,
        scope_id=scope_id or str(root),
        key=key,
        value=key,
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance=provenance,
        repository_revision=repository_revision,
        path_refs=path_refs,
    )
    return store.record(record, actor="user", idempotency_key=f"coord-{key}")


def test_repository_memory_shares_only_for_same_tenant_and_coordination_id(tmp_path: Path):
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    unrelated_repo = tmp_path / "unrelated-repo"
    for root in (worktree_a, worktree_b, unrelated_repo):
        root.mkdir()

    store = build_memory_store(tmp_path)
    shared_coordination_id = "opaque-t21-coordination-id-shared"
    other_coordination_id = "opaque-t21-coordination-id-other"
    shared = add_scoped_memory(
        store,
        root=worktree_a,
        tenant="tenant-a",
        key="shared-repository-memory",
        coordination_id=shared_coordination_id,
    )
    local = add_scoped_memory(
        store,
        root=worktree_b,
        tenant="tenant-a",
        key="physical-worktree-local-memory",
    )
    legacy_root_only = add_scoped_memory(
        store,
        root=worktree_a,
        tenant="tenant-a",
        key="legacy-physical-root-only-memory",
    )
    other_tenant = add_scoped_memory(
        store,
        root=worktree_a,
        tenant="tenant-b",
        key="other-tenant-memory",
        coordination_id=shared_coordination_id,
    )
    other_namespace = add_scoped_memory(
        store,
        root=worktree_a,
        tenant="tenant-a",
        key="other-namespace-memory",
        coordination_id=other_coordination_id,
    )
    unrelated = add_scoped_memory(
        store,
        root=unrelated_repo,
        tenant="tenant-a",
        key="unrelated-repository-memory",
        coordination_id=other_coordination_id,
    )

    visible = store.find_for_context(
        root=str(worktree_b),
        tenant="tenant-a",
        coordination_id=shared_coordination_id,
        limit=20,
    )
    assert {record.record_id for record in visible} == {shared.record_id, local.record_id}
    shared_result = next(record for record in visible if record.record_id == shared.record_id)
    assert shared_result.scope_id == str(worktree_a)
    assert shared_result.provenance["root"] == str(worktree_a)
    assert all(
        record.record_id
        not in {
            other_tenant.record_id,
            other_namespace.record_id,
            unrelated.record_id,
            legacy_root_only.record_id,
        }
        for record in visible
    )

    invalid_project_context = store.find_for_context(
        root=str(worktree_b), tenant="tenant-a", coordination_id=None, limit=20
    )
    assert {record.record_id for record in invalid_project_context} == {local.record_id}

    same_physical_root = store.find_for_context(
        root=str(worktree_a), tenant="tenant-a", coordination_id=None, limit=20
    )
    assert legacy_root_only.record_id in {record.record_id for record in same_physical_root}


def test_task_worktree_and_branch_memory_remain_physical_scope_local(tmp_path: Path):
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    worktree_a.mkdir()
    worktree_b.mkdir()
    store = build_memory_store(tmp_path)
    coordination_id = "opaque-t21-coordination-id-shared"

    local_a = [
        add_scoped_memory(
            store,
            root=worktree_a,
            tenant="tenant-a",
            key=f"{scope.value}-a",
            scope=scope,
            scope_id=scope_id,
            coordination_id=coordination_id,
        )
        for scope, scope_id in (
            (AgentScope.TASK, "task-a"),
            (AgentScope.WORKTREE, "worktree-a-id"),
            (AgentScope.BRANCH, "branch-a"),
        )
    ]
    local_b = [
        add_scoped_memory(
            store,
            root=worktree_b,
            tenant="tenant-a",
            key=f"{scope.value}-b",
            scope=scope,
            scope_id=scope_id,
            coordination_id=coordination_id,
        )
        for scope, scope_id in (
            (AgentScope.TASK, "task-b"),
            (AgentScope.WORKTREE, "worktree-b-id"),
            (AgentScope.BRANCH, "branch-b"),
        )
    ]

    visible = store.find_for_context(
        root=str(worktree_b),
        tenant="tenant-a",
        coordination_id=coordination_id,
        task_id="task-b",
        worktree_id="worktree-b-id",
        branch="branch-b",
        limit=20,
    )
    assert {record.record_id for record in visible} == {
        record.record_id for record in local_b
    }
    assert not ({record.record_id for record in visible} & {record.record_id for record in local_a})


def test_stale_source_invalidation_uses_physical_worktree_root(tmp_path: Path):
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    worktree_a.mkdir()
    worktree_b.mkdir()
    store = build_memory_store(tmp_path)
    coordination_id = "opaque-t21-coordination-id-shared"
    memory_a = add_scoped_memory(
        store,
        root=worktree_a,
        tenant="tenant-a",
        key="worktree-a-parser-rule",
        coordination_id=coordination_id,
        repository_revision="rev-a",
        path_refs=("src/parser.py",),
    )
    memory_b = add_scoped_memory(
        store,
        root=worktree_b,
        tenant="tenant-a",
        key="worktree-b-parser-rule",
        coordination_id=coordination_id,
        repository_revision="rev-b",
        path_refs=("src/parser.py",),
    )

    assert store.mark_stale_for_revision(
        str(worktree_b), "rev-b-next", ["src/parser.py"]
    ) == 1
    assert store.get(memory_a.record_id, scope=AgentScope.REPOSITORY, root=str(worktree_a), tenant="tenant-a").status is MemoryStatus.CONFIRMED
    assert store.get(memory_b.record_id, scope=AgentScope.REPOSITORY, root=str(worktree_b), tenant="tenant-a").status is MemoryStatus.STALE


def test_client_supplied_coordination_id_is_ignored_without_project_context():
    request = build_context_request(
        {
            "task_id": "task-client-input",
            "root": "C:/repo/worktree",
            "coordination_id": "attacker-chosen-id",
            "repository_id": "attacker-chosen-repository-id",
        },
        tenant="tenant-a",
    )
    assert request.coordination_id == ""
    assert request.repository_id == "attacker-chosen-repository-id"


def test_context_request_uses_only_server_project_context_coordination_id(tmp_path: Path):
    class TrustedProjectContext:
        root = tmp_path
        coordination_id = "opaque-server-derived-id"
        config_digest = "a" * 64
        settings = SimpleNamespace(pinned_context=(), entry_points=())

        def path_hints(self, **_kwargs):
            return ()

    request = build_context_request(
        {
            "task_id": "task-server-context",
            "root": str(tmp_path),
            "coordination_id": "attacker-chosen-id",
        },
        tenant="tenant-a",
        project_context=TrustedProjectContext(),
    )
    assert request.coordination_id == "opaque-server-derived-id"


def test_repository_write_replaces_client_identity_with_server_identity(tmp_path: Path):
    from local_ai_hub.http_server import _bind_repository_memory_provenance

    class TrustedProjectContext:
        root = tmp_path
        coordination_id = "opaque-server-derived-id"

    provenance = _bind_repository_memory_provenance(
        {"root": "C:/forged", "tenant": "forged-tenant", "repository_id": "client-id"},
        root=str(tmp_path),
        tenant="tenant-a",
        project_context=TrustedProjectContext(),
    )
    assert provenance == {
        "root": str(tmp_path),
        "tenant": "tenant-a",
        "repository_id": "opaque-server-derived-id",
    }


def test_http_context_ignores_client_coordination_identity(tmp_path: Path, monkeypatch):
    import json
    import threading
    import urllib.request

    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    root_a = tmp_path / "worktree-a"
    root_b = tmp_path / "worktree-b"
    root_a.mkdir()
    root_b.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    trusted = add_scoped_memory(
        app.agent_memory,
        root=root_a,
        tenant="http-default",
        key="trusted-shared-memory",
        coordination_id="server-coordination-id",
    )
    attacker = add_scoped_memory(
        app.agent_memory,
        root=root_a,
        tenant="http-default",
        key="attacker-chosen-memory",
        coordination_id="client-coordination-id",
    )
    class TrustedProjectContext:
        root = root_b
        coordination_id = "server-coordination-id"
        config_digest = "a" * 64
        settings = SimpleNamespace(pinned_context=(), entry_points=())

        def path_hints(self, **_kwargs):
            return ()

    monkeypatch.setattr(http_server, "_trusted_project_context", lambda _root: TrustedProjectContext())
    monkeypatch.setattr(
        http_server.Handler,
        "_memory_project_identity",
        lambda _self, _root: (str(root_b.resolve()), "server-coordination-id"),
    )
    monkeypatch.setattr(
        app.services,
        "adaptive_context_pack",
        lambda *_args, **_kwargs: {"success": True, "text": "repo context", "repo_revision": "rev-b"},
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "action": "compile",
            "task_id": "coordination-http-task",
            "root": str(root_b),
            "coordination_id": "client-coordination-id",
            "token_budget": 2000,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/context",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close", "X-LocalAI-Tenant": "http-default"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        forged_find = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps({
                "action": "find",
            "root": str(root_a),
                "repository_id": "client-coordination-id",
                "query": "memory",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close", "X-LocalAI-Tenant": "http-default"},
            method="POST",
        )
        with urllib.request.urlopen(forged_find) as response:
            find_result = json.loads(response.read().decode("utf-8"))
        forged_delete = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps({
                "action": "delete",
                "record_id": attacker.record_id,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close", "X-LocalAI-Tenant": "http-default"},
            method="POST",
        )
        try:
            urllib.request.urlopen(forged_delete)
            delete_status = 200
        except urllib.error.HTTPError as exc:
            delete_status = exc.code
        delete_survived = app.agent_memory.get(
            attacker.record_id,
            scope=AgentScope.REPOSITORY,
            root=str(root_a),
            tenant="http-default",
            repository_id="client-coordination-id",
        ) is not None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        http_server.APP = previous_app
        app.close()

    elements = result["context"]["elements"]
    visible_ids = {item["element_id"] for item in elements}
    assert trusted.record_id in visible_ids
    assert attacker.record_id not in visible_ids
    assert not any("attacker-chosen-memory" in item.get("content", "") for item in elements)
    assert attacker.record_id not in {item["record_id"] for item in find_result["records"]}
    assert delete_status in {400, 404}
    assert delete_survived
