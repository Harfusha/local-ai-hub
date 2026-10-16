from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server, mcp_server, project_config
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.features import FeatureSet


@pytest.fixture
def coordination_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / "hub-state"
    app_config = tmp_path / "hub.toml"
    app_config.write_text(
        f'[server]\nbind = "127.0.0.1"\nstate_dir = "{state_dir.as_posix()}"\n'
        "[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(app_config))

    class LocalHandler(http_server.Handler):
        def _require_authorized(self) -> bool:
            # Authentication is isolated in this namespace bridge fixture.
            # Bind its test principal before production tenant checks run.
            self._authenticated_principal_tenant = self.headers.get("X-LocalAI-Tenant", "owner-a")
            return True

        def _validate_payload(self, _path: str, _payload: dict) -> None:
            return None

        def log_message(self, *_args) -> None:
            return None

    previous_app = http_server.APP
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), LocalHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    client_config = tmp_path / "client.toml"
    client_config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_port}\n'
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mcp_server,
        "FEATURES",
        FeatureSet({"features": {"coord": True, "agent_os": True}}),
    )
    monkeypatch.setattr(mcp_server, "CFG", {"server": {"state_dir": str(state_dir)}})

    common_dirs: dict[Path, Path] = {}
    monkeypatch.setattr(
        project_config,
        "_git_common_dir",
        lambda root: common_dirs.get(Path(root).expanduser().resolve()),
    )

    def project(name: str, *, common: str, namespace: str):
        root = tmp_path / name
        root.mkdir()
        (root / ".local-ai.toml").write_text(
            f'shared_namespace = "{namespace}"\n', encoding="utf-8"
        )
        common_dir = tmp_path / "git-common" / common
        common_dir.mkdir(parents=True, exist_ok=True)
        common_dirs[root.resolve()] = common_dir
        return project_config.resolve_project_context(root, state_dir)

    clients = []

    class CapturingHubClient(HubClient):
        def coord(self, action: str, **payload):
            self.last_coord_result = super().coord(action, **payload)
            return self.last_coord_result

    def coord(
        context,
        action: str,
        *,
        owner: str = "owner-a",
        coordination_id_override: str | None = None,
        **kwargs,
    ):
        tool_tenant = kwargs.pop("tenant", owner)
        client_type = CapturingHubClient
        if coordination_id_override is not None:
            class OverrideCoordinationIdClient(CapturingHubClient):
                def coord(self, action: str, **payload):
                    payload["coordination_id"] = coordination_id_override
                    return super().coord(action, **payload)

            client_type = OverrideCoordinationIdClient
        client = client_type(
            tenant=owner, config_path=str(client_config), auto_start=False
        )
        clients.append(client)
        monkeypatch.setattr(mcp_server, "CLIENT", client)
        return mcp_server.local_ai_coord(
            action=action,
            root=str(context.root),
            tenant=tool_tenant,
            max_response_tokens=3200,
            response_profile="standard",
            extra_fields=["records"],
            **kwargs,
        )

    try:
        yield SimpleNamespace(
            project=project, coord=coord, clients=clients, state_dir=state_dir, app=app
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def _coordination_id(context) -> str:
    value = context.coordination_id
    assert value is not None
    return value


def _record_repository_memory(
    env, context, *, owner: str, key: str, value: str = "shared repo rule",
    record_fields: dict | None = None,
) -> dict:
    record = {
        "kind": "finding",
        "scope": "repository",
        "key": key,
        "value": value,
    }
    record.update(record_fields or {})
    return env.coord(
        context,
        "memory_record",
        owner=owner,
        scope="repository",
        key=key,
        value=value,
        record=record,
    )


def _find_repository_memory(env, context, *, owner: str, key: str) -> dict:
    return env.app.agent_memory.find(
        scope="repository",
        repository_id=_coordination_id(context),
        tenant=owner,
        key=key,
        semantic=False,
    )


def test_repo_memory_bridges_same_git_common_and_namespace_worktrees(coordination_bridge):
    env = coordination_bridge
    worktree_a = env.project("worktree-a", common="repo-common", namespace="team")
    worktree_b = env.project("worktree-b", common="repo-common", namespace="team")
    assert _coordination_id(worktree_a) == _coordination_id(worktree_b)

    written = _record_repository_memory(env, worktree_a, owner="tenant-a", key="shared-rule")
    assert written["success"] is True

    found = _find_repository_memory(env, worktree_b, owner="tenant-a", key="shared-rule")
    assert [record.value for record in found] == ["shared repo rule"]


@pytest.mark.parametrize(
    ("right_common", "right_namespace"),
    [("other-repo", "team"), ("repo-common", "other-team")],
    ids=["different-repository", "different-namespace"],
)
def test_repo_memory_does_not_cross_repository_or_namespace(
    coordination_bridge, right_common: str, right_namespace: str
):
    env = coordination_bridge
    worktree_a = env.project("worktree-a", common="repo-common", namespace="team")
    unrelated = env.project(
        "worktree-unrelated", common=right_common, namespace=right_namespace
    )
    assert _coordination_id(worktree_a) != _coordination_id(unrelated)
    assert _record_repository_memory(
        env, worktree_a, owner="tenant-a", key="private-rule"
    )["success"] is True

    found = _find_repository_memory(
        env, unrelated, owner="tenant-a", key="private-rule"
    )
    assert found == []


def test_repo_memory_rejects_a_different_tenant(coordination_bridge):
    env = coordination_bridge
    repository = env.project("repo", common="repo-common", namespace="team")
    created = env.coord(
        repository,
        "memory_record",
        owner="tenant-a",
        scope="session",
        session_id="tenant-a",
        key="tenant-rule",
        value="private session rule",
        record={
            "kind": "finding",
            "scope": "session",
            "scope_id": "tenant-a",
            "key": "tenant-rule",
            "value": "private session rule",
        },
    )
    assert created["success"] is True

    found = env.app.agent_memory.find(
        scope="session",
        session_id="tenant-b",
        root=str(repository.root),
        tenant="tenant-b",
        key="tenant-rule",
        semantic=False,
    )
    assert found == []


def test_overlapping_lease_from_same_namespace_conflicts_across_worktrees(
    coordination_bridge,
):
    env = coordination_bridge
    worktree_a = env.project("worktree-a", common="repo-common", namespace="team")
    worktree_b = env.project("worktree-b", common="repo-common", namespace="team")
    assert _coordination_id(worktree_a) == _coordination_id(worktree_b)

    held = env.coord(
        worktree_a, "claim", owner="owner-a", paths=["src/config.py"]
    )
    assert held["success"] is True

    conflicting = env.coord(
        worktree_b, "claim", owner="owner-b", paths=["src/config.py"]
    )
    assert conflicting["success"] is False
    assert "overlaps" in conflicting["error"]


def test_lease_renew_and_release_require_the_owner(coordination_bridge):
    env = coordination_bridge
    repository = env.project("repo", common="repo-common", namespace="team")
    held = env.coord(repository, "claim", owner="owner-a", paths=["src/config.py"])
    assert held["success"] is True

    wrong_renewal = env.coord(
        repository, "renew", owner="owner-b", lease_id=held["lease_id"]
    )
    wrong_release = env.coord(
        repository, "release", owner="owner-b", lease_id=held["lease_id"]
    )
    assert wrong_renewal["success"] is False
    assert wrong_release["released_rows"] == 0

    renewed = env.coord(
        repository, "renew", owner="owner-a", lease_id=held["lease_id"]
    )
    released = env.coord(
        repository, "release", owner="owner-a", lease_id=held["lease_id"]
    )
    assert renewed["success"] is True
    assert released["released_rows"] == 1


def test_repository_memory_coord_wrapper_create_find_get_delete(coordination_bridge):
    env = coordination_bridge
    repository = env.project("repo-crud", common="repo-common", namespace="team")
    created = _record_repository_memory(
        env, repository, owner="tenant-a", key="crud-rule", value="stored"
    )
    assert created["success"] is True
    created_raw = env.clients[-1].last_coord_result
    record_id = created_raw["record"]["record_id"]

    found = env.coord(
        repository,
        "memory_find",
        owner="tenant-a",
        scope="repository",
        key="crud-rule",
    )
    found_raw = env.clients[-1].last_coord_result
    assert found["success"] is True
    assert [record["record_id"] for record in found_raw["records"]] == [record_id]

    fetched = env.coord(
        repository,
        "memory_get",
        owner="tenant-a",
        scope="repository",
        record_id=record_id,
    )
    assert fetched["success"] is True
    assert env.clients[-1].last_coord_result["record"]["value"] == "stored"

    deleted = env.coord(
        repository,
        "memory_delete",
        owner="tenant-a",
        scope="repository",
        record_id=record_id,
    )
    assert deleted["success"] is True
    assert env.clients[-1].last_coord_result["deleted"] is True

    missing = env.coord(
        repository,
        "memory_get",
        owner="tenant-a",
        scope="repository",
        record_id=record_id,
    )
    assert missing["success"] is False


def test_repository_memory_coord_wrapper_preserves_correction_lineage(
    coordination_bridge,
):
    env = coordination_bridge
    repository = env.project("repo-correction", common="repo-common", namespace="team")
    created = _record_repository_memory(
        env,
        repository,
        owner="tenant-a",
        key="correction-rule",
        value="original",
        record_fields={"status": "confirmed"},
    )
    assert created["success"] is True
    original_id = env.clients[-1].last_coord_result["record"]["record_id"]

    corrected = _record_repository_memory(
        env,
        repository,
        owner="tenant-a",
        key="corrected-rule",
        value="corrected",
        record_fields={
            "status": "confirmed",
            "contradicts_record_id": original_id,
            "supersedes_record_id": original_id,
        },
    )
    assert corrected["success"] is True
    corrected_record = env.clients[-1].last_coord_result["record"]
    assert corrected_record["contradicts_record_id"] == original_id
    assert corrected_record["supersedes_record_id"] == original_id


def test_client_cannot_override_namespace_or_tenant_for_memory_find(
    coordination_bridge,
):
    env = coordination_bridge
    victim = env.project("victim-repo", common="repo-common", namespace="private")
    attacker = env.project("attacker-repo", common="repo-common", namespace="public")
    assert _coordination_id(victim) != _coordination_id(attacker)
    created = _record_repository_memory(
        env, victim, owner="tenant-victim", key="private-rule", value="secret"
    )
    assert created["success"] is True

    result = env.coord(
        attacker,
        "memory_find",
        owner="tenant-attacker",
        tenant="tenant-victim",
        scope="repository",
        key="private-rule",
        repository_id=_coordination_id(victim),
        coordination_id_override=_coordination_id(victim),
    )
    raw = env.clients[-1].last_coord_result
    assert result["success"] is True
    assert raw.get("records", []) == []
