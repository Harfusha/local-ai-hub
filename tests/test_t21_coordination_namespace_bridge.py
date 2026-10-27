from __future__ import annotations

from copy import deepcopy
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
        client_type = CapturingHubClient
        if coordination_id_override is not None:
            class OverrideCoordinationIdClient(CapturingHubClient):
                def coord(self, action: str, **payload):
                    payload["coordination_id"] = coordination_id_override
                    return super().coord(action, **payload)

            client_type = OverrideCoordinationIdClient
        client = client_type(
             config_path=str(client_config), auto_start=False
        )
        clients.append(client)
        monkeypatch.setattr(mcp_server, "CLIENT", client)
        if action in {"claim", "release", "renew"}:
            kwargs["owner"] = owner
        return mcp_server.local_ai_coord(
            action=action,
            root=str(context.root),

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
    env, context, *, key: str, value: str = "shared repo rule",
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
        scope="repository",
        key=key,
        value=value,
        record=record,
    )


def _find_repository_memory(env, context, *, key: str) -> dict:
    return env.app.agent_memory.find(
        scope="repository",
        repository_id=_coordination_id(context),

        key=key,
        semantic=False,
    )


def test_repo_memory_bridges_same_git_common_and_namespace_worktrees(coordination_bridge):
    env = coordination_bridge
    worktree_a = env.project("worktree-a", common="repo-common", namespace="team")
    worktree_b = env.project("worktree-b", common="repo-common", namespace="team")
    assert _coordination_id(worktree_a) == _coordination_id(worktree_b)

    written = _record_repository_memory(env, worktree_a, key="shared-rule")
    assert written["success"] is True

    found = _find_repository_memory(env, worktree_b, key="shared-rule")
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
        env, worktree_a, key="private-rule"
    )["success"] is True

    found = _find_repository_memory(
        env, unrelated, key="private-rule"
    )
    assert found == []


def test_session_memory_remains_bound_to_actual_session_id(coordination_bridge):
    env = coordination_bridge
    repository = env.project("repo", common="repo-common", namespace="team")
    created = env.coord(
        repository,
        "memory_record",
        scope="session",
        scope_id="session-a",
        session_id="session-a",
        key="session-rule",
        value="private session rule",
    )
    assert created["success"] is True, created

    found = env.app.agent_memory.find(
        scope="session",
        session_id="session-b",
        root=str(repository.root),
        key="session-rule",
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
        env, repository, key="crud-rule", value="stored"
    )
    assert created["success"] is True
    created_raw = env.clients[-1].last_coord_result
    record_id = created_raw["record"]["record_id"]

    found = env.coord(
        repository,
        "memory_find",
        scope="repository",
        key="crud-rule",
    )
    found_raw = env.clients[-1].last_coord_result
    assert found["success"] is True
    assert [record["record_id"] for record in found_raw["records"]] == [record_id]

    fetched = env.coord(
        repository,
        "memory_get",
        scope="repository",
        record_id=record_id,
    )
    assert fetched["success"] is True
    assert env.clients[-1].last_coord_result["record"]["value"] == "stored"

    deleted = env.coord(
        repository,
        "memory_delete",
        scope="repository",
        record_id=record_id,
    )
    assert deleted["success"] is True
    assert env.clients[-1].last_coord_result["deleted"] is True

    missing = env.coord(
        repository,
        "memory_get",
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
        key="correction-rule",
        value="original",
        record_fields={"status": "confirmed"},
    )
    assert created["success"] is True
    original_id = env.clients[-1].last_coord_result["record"]["record_id"]

    corrected = _record_repository_memory(
        env,
        repository,
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


def test_client_cannot_override_repository_scope_for_memory_find(
    coordination_bridge,
):
    env = coordination_bridge
    victim = env.project("victim-repo", common="repo-common", namespace="private")
    attacker = env.project("attacker-repo", common="repo-common", namespace="public")
    assert _coordination_id(victim) != _coordination_id(attacker)
    created = _record_repository_memory(
        env, victim, key="private-rule", value="secret"
    )
    assert created["success"] is True

    result = env.coord(
        attacker,
        "memory_find",
        scope="repository",
        key="private-rule",
        repository_id=_coordination_id(victim),
        coordination_id_override=_coordination_id(victim),
    )
    raw = env.clients[-1].last_coord_result
    assert result["success"] is True
    assert raw.get("records", []) == []


def test_client_memory_requests_leave_repository_identity_to_server(
    monkeypatch,
):
    client = HubClient.__new__(HubClient)
    captured: dict[str, object] = {}

    def capture_post(path: str, payload: dict) -> dict:
        captured.update(path=path, payload=payload)
        return {"success": True}

    monkeypatch.setattr(client, "post", capture_post)
    record = {
        "kind": "finding",
        "scope": "repository",
        "scope_id": "forged-scope",
        "repository_id": "forged-repository",
        "coordination_id": "forged-coordination",
        "key": "identity-rule",
        "value": "must use server identity",
    }
    original_record = deepcopy(record)

    result = HubClient.coord(
        client,
        "memory_record",
        root="C:/repo",
        scope="repository",
        scope_id="forged-scope",

        repository_id="forged-repository",
        coordination_id="forged-coordination",
        record=record,
    )

    assert result["success"] is True
    assert captured["path"] == "/api/agent-state/memory"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["root"] == "C:/repo"
    assert payload["scope"] == "repository"
    assert {"repository_id", "coordination_id", "scope_id"}.isdisjoint(payload)
    assert payload["record"] == {
        "kind": "finding",
        "scope": "repository",
        "key": "identity-rule",
        "value": "must use server identity",
    }
    assert record == original_record


def test_client_rejects_retired_tenant_field_before_memory_transport(monkeypatch):
    client = HubClient.__new__(HubClient)
    transported = []
    monkeypatch.setattr(client, "post", lambda *args, **kwargs: transported.append((args, kwargs)))

    result = HubClient.coord(
        client,
        "memory_record",
        root="C:/repo",
        scope="repository",
        record={"kind": "finding", "key": "x", "value": "y", "tenant": None},
    )

    assert result["success"] is False
    assert transported == []

def test_client_memory_record_namespace_comes_from_nested_repository_scope(
    monkeypatch,
):
    client = HubClient.__new__(HubClient)
    captured: dict[str, object] = {}

    def capture_post(path: str, payload: dict) -> dict:
        captured.update(path=path, payload=payload)
        return {"success": True}

    monkeypatch.setattr(client, "post", capture_post)
    record = {
        "kind": "finding",
        "scope": "repository",
        "scope_id": "forged-scope",
        "key": "nested-identity-rule",
        "value": "must use server identity",
    }
    original_record = deepcopy(record)

    result = HubClient.coord(
        client,
        "memory_record",
        root="C:/repo",
        record=record,
    )

    assert result["success"] is True
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "scope_id" not in payload
    assert payload["record"] == {
        "kind": "finding",
        "scope": "repository",
        "key": "nested-identity-rule",
        "value": "must use server identity",
    }
    assert record == original_record
