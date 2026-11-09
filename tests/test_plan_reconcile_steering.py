import hashlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_tasks import GoalContract, ScopeContext
from local_ai_hub.repo_plan import agent_bridge
from local_ai_hub.repo_plan.schema_validation import RepoPlanConflictError
from test_repo_plan_agent_os import create_initial_plan_file

pytest_plugins = ("test_repo_plan_agent_os",)


def test_pending_temp_collision_preserves_existing_file(test_environment, monkeypatch):
    root, storage, _, task_store, _, _, manager = test_environment
    setup_bound_task(test_environment)
    binding = manager.get_binding("task_001")
    pending = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation"
    pending.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(b"task_001").hexdigest() + ".json"
    token = "1234567890abcdef1234567890abcdef"
    existing = pending / f".{name}.{token}.tmp"
    existing.write_bytes(b"preserve")
    monkeypatch.setattr(agent_bridge.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    with pytest.raises(FileExistsError):
        agent_bridge._persist_pending_contract_reconciliation(storage, binding, {"reason": "new"})
    assert existing.read_bytes() == b"preserve"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction reproduction")
def test_pending_reconciliation_resists_parent_junction_swap(test_environment, monkeypatch, tmp_path):
    root, storage, _, task_store, _, _, manager = test_environment
    setup_bound_task(test_environment)
    binding = manager.get_binding("task_001")
    parent = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation"
    parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path.parent / (tmp_path.name + "-steering-outside")
    outside.mkdir()
    name = hashlib.sha256(b"task_001").hexdigest() + ".json"
    sentinel = outside / name
    sentinel.write_bytes(b"unchanged")
    junction = root / "staged-steering-junction"
    env = {**os.environ, "LAH_RACE_LINK": str(junction), "LAH_RACE_TARGET": str(outside)}
    created = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "New-Item -ItemType Junction -Path $env:LAH_RACE_LINK -Target $env:LAH_RACE_TARGET | Out-Null"],
        env=env, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if created.returncode or not junction.exists():
        pytest.skip("Cannot create a Windows junction in this test environment")
    original_mkdir = Path.mkdir
    attempted = False

    def swap_parent(path, *args, **kwargs):
        nonlocal attempted
        if path == parent and not attempted:
            attempted = True
            parent.rename(parent.with_name("old-pending"))
            junction.rename(parent)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", swap_parent)
    try:
        agent_bridge._persist_pending_contract_reconciliation(storage, binding, {"reason": "new"})
    except OSError:
        pass
    assert attempted
    assert sentinel.read_bytes() == b"unchanged"


def setup_bound_task(test_environment):
    root, storage, _, task_store, _, _, manager = test_environment
    plan_path = ".local-ai-hub/plans/workflow.plan.json"
    create_initial_plan_file(storage, plan_path)
    task_store.create(
        GoalContract(goal="Implement core logic", acceptance_criteria=[
            "Core module passes unit tests", "Specification documentation is verified"
        ]),
        ScopeContext(repository_id=str(root), session_id="session_test"),
        task_id="task_001", actor="test_agent", repo_root=str(root),
    )
    manager.bind_task("task_001", "plan_workflow", "task_core", plan_path,
                      session_id="session_test", task_store=task_store)
    _, plan_revision = storage.read_plan_file(plan_path)
    spec = root / "docs" / "feature.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("original\n", encoding="utf-8")
    return root, storage, task_store, plan_path, plan_revision, spec


def test_reconcile_steering_persists_spec_plan_and_task(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    result = agent_bridge.reconcile_task_steering(
        task_store, root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Core module passes unit tests", "Updated requirement"],
        expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
    )
    assert result["success"] is True
    assert spec.read_text(encoding="utf-8") == "updated\n"
    plan, _ = storage.read_plan_file(plan_path)
    assert plan["tasks"]["task_core"]["acceptance_criteria"] == ["Core module passes unit tests", "Updated requirement"]
    assert task_store.get("task_001").contract.acceptance_criteria == ("Core module passes unit tests", "Updated requirement")


def test_pending_steering_growth_after_stat_has_bounded_read(test_environment, monkeypatch):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
                     spec_rel_path="docs/feature.md", spec_content="updated\n",
                     acceptance_criteria=["Core module passes unit tests", "Updated requirement"],
                     expected_revision=plan_rev,
                     expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    agent_bridge.reconcile_task_steering(task_store, **arguments)
    _, saved_revision = storage.read_plan_file(plan_path)
    pending_dir = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending = pending_dir / (hashlib.sha256(b"task_001").hexdigest() + ".json")
    pending.write_bytes(b" " * (agent_bridge.MAX_PENDING_RECONCILIATION_BYTES + 1))
    real_stat = Path.stat
    real_read_text = Path.read_text

    def stale_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == pending:
            values = list(result)
            values[6] = 1
            return os.stat_result(values)
        return result

    def guarded_read_text(path, *args, **kwargs):
        if path == pending:
            raise AssertionError("pending record must not be read without a bound")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stale_stat)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    with pytest.raises(RuntimeError, match="size limit"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert storage.read_plan_file(plan_path)[1] == saved_revision


@pytest.mark.skipif(os.name != "nt", reason="Windows handle path validation")
def test_pending_read_rejects_handle_opened_outside_expected_path(tmp_path, monkeypatch):
    expected = tmp_path / "pending.json"
    outside = tmp_path / "outside.json"
    expected.write_text("{}", encoding="utf-8")
    outside.write_text("{}", encoding="utf-8")
    real_open = os.open
    opened = []

    def swapped_open(path, flags, *args, **kwargs):
        if Path(path) == expected:
            descriptor = real_open(outside, flags, *args, **kwargs)
            opened.append(descriptor)
            return descriptor
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(agent_bridge.os, "open", swapped_open)
    with pytest.raises(ValueError, match="opened pending reconciliation path"):
        agent_bridge._read_pending_reconciliation(expected)
    with pytest.raises(OSError):
        os.fstat(opened[0])


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO regression")
def test_pending_read_rejects_fifo_without_waiting_for_writer(tmp_path):
    fifo = tmp_path / "pending-fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular file"):
        agent_bridge._read_pending_reconciliation(fifo)


def test_pending_record_does_not_replace_unresolved_distinct_content(test_environment):
    root, storage, _, _, _, _, _ = test_environment
    binding = agent_bridge.TaskBinding(task_id="task_001", repo_root=str(root), plan_id="plan_a",
                                       plan_task_id="task_a", plan_rel_path=".local-ai-hub/plans/plan_a.plan.json")
    original = {"task_id": "task_001", "reason": "first clarification"}
    path = agent_bridge._persist_pending_contract_reconciliation(storage, binding, original)
    before = path.read_bytes()
    assert agent_bridge._persist_pending_contract_reconciliation(storage, binding, original) == path
    assert path.read_bytes() == before
    with pytest.raises(RepoPlanConflictError, match="pending reconciliation"):
        agent_bridge._persist_pending_contract_reconciliation(storage, binding, {**original, "reason": "different"})
    assert path.read_bytes() == before


def test_oversized_pending_record_is_not_persisted(test_environment):
    root, storage, _, _, _, _, _ = test_environment
    binding = agent_bridge.TaskBinding(task_id="task_oversized", repo_root=str(root), plan_id="plan_a",
                                       plan_task_id="task_a", plan_rel_path=".local-ai-hub/plans/plan_a.plan.json")
    with pytest.raises(ValueError, match="size limit"):
        agent_bridge._persist_pending_contract_reconciliation(storage, binding, {"text": "x" * agent_bridge.MAX_PENDING_RECONCILIATION_BYTES})
    path = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation" / (hashlib.sha256(b"task_oversized").hexdigest() + ".json")
    assert not path.exists()


def test_existing_pending_blocks_new_steering_before_plan_or_spec_changes(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    binding = agent_bridge.TaskBindingManager(root).get_binding("task_001")
    agent_bridge._persist_pending_contract_reconciliation(storage, binding, {"reason": "unfinished"})
    spec_before = spec.read_bytes()
    task_before = task_store.get("task_001")
    with pytest.raises(RepoPlanConflictError, match="pending reconciliation"):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001", steering_id="new",
            spec_rel_path="docs/feature.md", spec_content="changed\n",
            acceptance_criteria=["New requirement"], expected_revision=plan_rev,
            expected_spec_revision=hashlib.sha256(spec_before).hexdigest())
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_bytes() == spec_before
    assert task_store.get("task_001").contract == task_before.contract


def test_oversized_recovery_payload_is_rejected_before_plan_or_spec_changes(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    spec_before = spec.read_bytes()
    criteria = [f"{index}:" + "\U0001f431" * 4000 for index in range(50)]
    with pytest.raises(ValueError, match="size limit"):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001", steering_id="oversized",
            spec_rel_path="docs/feature.md", spec_content="changed\n",
            acceptance_criteria=criteria, expected_revision=plan_rev,
            expected_spec_revision=hashlib.sha256(spec_before).hexdigest())
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_bytes() == spec_before


@pytest.mark.parametrize("crash_point", ["before_save", "after_reservation", "after_spec", "before_ack", "before_contract", "before_binding"])
def test_steering_intent_is_durable_before_writes_and_recovers(test_environment, monkeypatch, crash_point):
    from local_ai_hub.repo_plan.storage import RepoPlanStorage
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="intent-test",
                     spec_rel_path="docs/feature.md", spec_content="updated\n",
                     acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
                     expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())

    class SimulatedCrash(BaseException):
        pass

    if crash_point == "before_save":
        original = RepoPlanStorage.save_spec_and_plan
        monkeypatch.setattr(RepoPlanStorage, "save_spec_and_plan", lambda *_a, **_k: (_ for _ in ()).throw(SimulatedCrash()))
    elif crash_point == "after_reservation":
        original = RepoPlanStorage._save_intent
        monkeypatch.setattr(RepoPlanStorage, "_save_intent", lambda *_a, **_k: (_ for _ in ()).throw(SimulatedCrash()))
    elif crash_point == "after_spec":
        original = RepoPlanStorage._atomic_write_bytes
        def crash_after_spec(store, path, data):
            original(store, path, data)
            if path == spec:
                raise SimulatedCrash()
        monkeypatch.setattr(RepoPlanStorage, "_atomic_write_bytes", crash_after_spec)
    elif crash_point == "before_ack":
        original = RepoPlanStorage._save_request
        def crash_before_ack(store, key, data):
            if data.get("status") == "completed" and key.startswith("steering_v2_"):
                raise SimulatedCrash()
            return original(store, key, data)
        monkeypatch.setattr(RepoPlanStorage, "_save_request", crash_before_ack)
    elif crash_point == "before_contract":
        original = task_store.revise_contract
        monkeypatch.setattr(task_store, "revise_contract", lambda *_a, **_k: (_ for _ in ()).throw(SimulatedCrash()))
    else:
        original = agent_bridge.TaskBindingManager._save
        def crash_binding(manager, binding, **kwargs):
            if binding.contract_revision == 2:
                raise SimulatedCrash()
            return original(manager, binding, **kwargs)
        monkeypatch.setattr(agent_bridge.TaskBindingManager, "_save", crash_binding)

    with pytest.raises(SimulatedCrash):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    pending = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation" / (hashlib.sha256(b"task_001").hexdigest() + ".json")
    assert pending.is_file()
    if crash_point == "before_save":
        assert storage.read_plan_file(plan_path)[1] == plan_rev
        assert spec.read_text(encoding="utf-8") == "original\n"
        monkeypatch.setattr(RepoPlanStorage, "save_spec_and_plan", original)
    elif crash_point == "after_reservation":
        assert storage.read_plan_file(plan_path)[1] == plan_rev
        assert spec.read_text(encoding="utf-8") == "original\n"
        monkeypatch.setattr(RepoPlanStorage, "_save_intent", original)
    elif crash_point == "after_spec":
        assert storage.read_plan_file(plan_path)[1] == plan_rev
        assert spec.read_text(encoding="utf-8") == "updated\n"
        monkeypatch.setattr(RepoPlanStorage, "_atomic_write_bytes", original)
    elif crash_point == "before_ack":
        monkeypatch.setattr(RepoPlanStorage, "_save_request", original)
    elif crash_point == "before_contract":
        monkeypatch.setattr(task_store, "revise_contract", original)
    else:
        monkeypatch.setattr(agent_bridge.TaskBindingManager, "_save", original)
    recovered = agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert recovered["success"] is True
    assert task_store.get("task_001").contract.acceptance_criteria == ("Updated requirement",)
    assert not pending.exists()


def test_service_reconcile_routes_to_real_persistence(test_environment):
    from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace
    from local_ai_hub.services import LocalAIServices

    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)

    class Service:
        def __init__(self):
            self.task_store = task_store

        def _plan_workspace(self, actual_root, action, arguments):
            assert actual_root == str(root) and action == "plan_reconcile_steering"
            return RepoPlanWorkspace(actual_root)

    result = LocalAIServices.plan_reconcile_steering(
        Service(), root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
    )
    assert result["success"] is True
    assert storage.read_plan_file(plan_path)[0]["tasks"]["task_core"]["acceptance_criteria"] == ["Updated requirement"]
    assert task_store.get("task_001").contract.acceptance_criteria == ("Updated requirement",)


def test_http_reconcile_updates_bound_task_and_plan(test_environment, tmp_path, monkeypatch):
    import asyncio
    import json
    import threading
    import urllib.error
    import urllib.request
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    state = tmp_path / "http-state"
    state.mkdir()
    config = tmp_path / "http-test.toml"
    config.write_text(f'''[server]
bind = "127.0.0.1"
state_dir = "{state.as_posix()}"
[agent_state]
enabled = true
[security]
allowed_roots = ["{root.as_posix()}"]
''', encoding="utf-8")
    app = LocalAIApp(str(config))
    app.services.task_store = task_store
    old_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_http",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["HTTP requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
        summary="Operator HTTP clarification")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/api/coord/plan_reconcile_steering",
        data=json.dumps(arguments).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        config.write_text(config.read_text(encoding="utf-8").replace(
            '[server]\n', f'[server]\nport = {server.server_address[1]}\n'), encoding="utf-8")
        monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
        monkeypatch.setattr(mcp_server, "CLIENT", HubClient(config_path=str(config), auto_start=False))
        monkeypatch.setattr(mcp_server, "_compact", lambda value, *_args: value)
        _, mcp_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": "plan_reconcile_steering", **arguments,
        }))
        assert mcp_result["success"] is True, mcp_result
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise AssertionError(exc.read().decode("utf-8")) from exc
        assert result["success"] is True
        assert task_store.get("task_001").contract.acceptance_criteria == ("HTTP requirement",)
        assert storage.read_plan_file(plan_path)[0]["tasks"]["task_core"]["acceptance_criteria"] == ["HTTP requirement"]
        assert storage.read_plan_file(plan_path)[0]["tasks"]["task_core"]["clarifications"][0]["summary"] == "Operator HTTP clarification"
        assert spec.read_text(encoding="utf-8") == "updated\n"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        http_server.APP = old_app
        app.close()


def test_stale_spec_revision_leaves_plan_task_and_spec_unchanged(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    before = task_store.get("task_001")
    with pytest.raises(RepoPlanConflictError):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001", steering_id="steering_001",
            spec_rel_path="docs/feature.md", spec_content="updated\n",
            acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
            expected_spec_revision="0" * 64,
        )
    assert spec.read_text(encoding="utf-8") == "original\n"
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert task_store.get("task_001").contract == before.contract


def test_same_steering_replay_does_not_revise_twice(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    first = agent_bridge.reconcile_task_steering(task_store, **arguments)
    second = agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert first["success"] is True and second["success"] is True
    task = task_store.get("task_001")
    assert task.checkpoint.state_data["contract_revision"] == 2
    plan, _ = storage.read_plan_file(plan_path)
    assert len(plan["tasks"]["task_core"]["clarifications"]) == 1


def test_steering_id_reuse_with_different_payload_is_rejected(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    agent_bridge.reconcile_task_steering(task_store, **arguments)
    saved_plan_rev = storage.read_plan_file(plan_path)[1]
    arguments["acceptance_criteria"] = ["Different requirement"]
    arguments["expected_revision"] = saved_plan_rev
    with pytest.raises(RepoPlanConflictError):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert storage.read_plan_file(plan_path)[1] == saved_plan_rev
    assert task_store.get("task_001").contract.acceptance_criteria == ("Updated requirement",)


@pytest.mark.parametrize("changed_field", ["summary", "adoption", "spec_refs"])
def test_replay_rejects_changed_persisted_clarification(test_environment, changed_field):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    agent_bridge.reconcile_task_steering(task_store, **arguments)
    plan, revision = storage.read_plan_file(plan_path)
    clarification = plan["tasks"]["task_core"]["clarifications"][0]
    clarification[changed_field] = {"summary": "Different instruction", "adoption": "pending", "spec_refs": []}[changed_field]
    storage.save_plan_file(plan_path, plan, expected_revision=revision, owner="test_agent")
    with pytest.raises(RepoPlanConflictError, match="persisted steering"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)


def test_stale_plan_revision_rejected_without_mutation(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    with pytest.raises(RepoPlanConflictError):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001", steering_id="steering_001",
            spec_rel_path="docs/feature.md", spec_content="updated\n",
            acceptance_criteria=["Updated requirement"], expected_revision="0" * 64,
            expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
        )
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("invalid", [None, False, 0, [], "ABC"])
def test_invalid_revision_is_rejected_without_mutation(test_environment, invalid):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    with pytest.raises(ValueError, match="expected_revision"):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001", steering_id="steering_001",
            spec_rel_path="docs/feature.md", spec_content="updated\n",
            acceptance_criteria=["Updated requirement"], expected_revision=invalid,
            expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
        )
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_text(encoding="utf-8") == "original\n"


def test_mismatched_root_cannot_reconcile_another_task(test_environment, tmp_path):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    with pytest.raises((ValueError, PermissionError)):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(foreign_root), task_id="task_001", steering_id="steering_001",
            spec_rel_path="docs/feature.md", spec_content="updated\n",
            acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
            expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
        )
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_text(encoding="utf-8") == "original\n"


def test_invalid_task_identity_rejected(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    with pytest.raises(ValueError, match="task_id"):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001\x00", steering_id="steering_001",
            spec_rel_path="docs/feature.md", spec_content="updated\n",
            acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
            expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
        )
    assert storage.read_plan_file(plan_path)[1] == plan_rev


def test_linked_spec_parent_rejected_before_mutation(test_environment, monkeypatch):
    from pathlib import Path

    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == spec.parent or original(path))
    with pytest.raises(ValueError, match="link"):
        agent_bridge.reconcile_task_steering(
            task_store, root=str(root), task_id="task_001", steering_id="steering_001",
            spec_rel_path="docs/feature.md", spec_content="updated\n",
            acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
            expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest(),
        )
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_text(encoding="utf-8") == "original\n"


def test_contract_revision_passes_caller_spec_revision_to_atomic_store(test_environment):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    binding = agent_bridge.TaskBindingManager(root).get_binding("task_001")
    with pytest.raises(RepoPlanConflictError):
        agent_bridge.reconcile_contract_revision(
            storage, binding, ["Updated requirement"], "Operator clarification",
            task_store=task_store, owner="test_agent", spec_rel_path="docs/feature.md",
            spec_content="updated\n", expected_plan_revision=plan_rev,
            expected_spec_revision="0" * 64,
        )
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_text(encoding="utf-8") == "original\n"
    assert task_store.get("task_001").checkpoint.state_data.get("contract_revision", 1) == 1


def test_retry_recovers_persisted_partial_reconciliation(test_environment, monkeypatch):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated task store failure")
        return original_revise(*args, **kwargs)

    monkeypatch.setattr(task_store, "revise_contract", fail_once)
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    pending_path = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation" / (hashlib.sha256(b"task_001").hexdigest() + ".json")
    import json
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert pending["plan_revision"] == storage.read_plan_file(plan_path)[1]
    result = agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert result["success"] is True
    assert task_store.get("task_001").contract.acceptance_criteria == ("Updated requirement",)
    plan, _ = storage.read_plan_file(plan_path)
    assert len(plan["tasks"]["task_core"]["clarifications"]) == 1
    assert spec.read_text(encoding="utf-8") == "updated\n"


def test_recovery_does_not_revise_contract_after_concurrent_plan_change(test_environment, monkeypatch):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(task_store, "revise_contract", original_revise)
    original_get = task_store.get
    calls = 0

    def change_plan_on_second_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            plan, revision = storage.read_plan_file(plan_path)
            plan["tasks"]["task_core"]["clarifications"][0]["summary"] = "Changed concurrently"
            storage.save_plan_file(plan_path, plan, expected_revision=revision, owner="test_agent")
        return original_get(*args, **kwargs)

    monkeypatch.setattr(task_store, "get", change_plan_on_second_read)
    with pytest.raises(RepoPlanConflictError):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert original_get("task_001").checkpoint.state_data.get("contract_revision", 1) == 1


def test_recovery_serializes_plan_writes_until_contract_revision(test_environment, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    started, finished = Event(), Event()
    plan, revision = storage.read_plan_file(plan_path)
    plan["tasks"]["task_core"]["clarifications"][0]["summary"] = "Later edit"

    def write_plan():
        started.set()
        try:
            storage.save_plan_file(plan_path, plan, expected_revision=revision, owner="test_agent")
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        def revise_while_writer_waits(*args, **kwargs):
            future = pool.submit(write_plan)
            assert started.wait(2)
            assert not finished.wait(0.2)
            revise_while_writer_waits.future = future
            return original_revise(*args, **kwargs)

        monkeypatch.setattr(task_store, "revise_contract", revise_while_writer_waits)
        assert agent_bridge.reconcile_task_steering(task_store, **arguments)["success"] is True
        revise_while_writer_waits.future.result(timeout=5)
    assert finished.is_set()


def test_recovery_with_pending_checkpoint_projection(test_environment, monkeypatch):
    root, storage, task_store, plan_path, _, spec = setup_bound_task(test_environment)
    plan, revision = storage.read_plan_file(plan_path)
    plan["tasks"]["task_core"]["next_action"] = "A newer plan action"
    storage.save_plan_file(plan_path, plan, expected_revision=revision, owner="test_agent")
    _, plan_rev = storage.read_plan_file(plan_path)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(task_store, "revise_contract", original_revise)
    assert agent_bridge.reconcile_task_steering(task_store, **arguments)["success"] is True
    binding = agent_bridge.TaskBindingManager(root).get_binding("task_001")
    assert binding.adopted_plan_revision == storage.read_plan_file(plan_path)[1]


def test_recovery_retries_binding_after_checkpoint_projection(test_environment, monkeypatch):
    root, storage, task_store, plan_path, _, spec = setup_bound_task(test_environment)
    plan, revision = storage.read_plan_file(plan_path)
    plan["tasks"]["task_core"]["next_action"] = "A newer plan action"
    storage.save_plan_file(plan_path, plan, expected_revision=revision, owner="test_agent")
    _, plan_rev = storage.read_plan_file(plan_path)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(task_store, "revise_contract", original_revise)
    original_save = agent_bridge.TaskBindingManager._save
    monkeypatch.setattr(agent_bridge.TaskBindingManager, "_save", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("binding unavailable")))
    with pytest.raises(RuntimeError, match="binding unavailable"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(agent_bridge.TaskBindingManager, "_save", original_save)
    result = agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert result["success"] is True
    assert task_store.get("task_001").checkpoint.state_data["contract_revision"] == 2
    assert agent_bridge.TaskBindingManager(root).get_binding("task_001").adopted_plan_revision == storage.read_plan_file(plan_path)[1]


@pytest.mark.parametrize("alter_plan", [False, True, "forged"])
def test_recovery_retries_after_projection_record_write_failure(test_environment, monkeypatch, alter_plan):
    root, storage, task_store, plan_path, _, spec = setup_bound_task(test_environment)
    plan, revision = storage.read_plan_file(plan_path)
    plan["tasks"]["task_core"]["next_action"] = "A newer plan action"
    storage.save_plan_file(plan_path, plan, expected_revision=revision, owner="test_agent")
    _, plan_rev = storage.read_plan_file(plan_path)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(task_store, "revise_contract", original_revise)
    original_replace = agent_bridge.os.replace
    pending_writes = 0

    def fail_pending_replace(source, destination):
        nonlocal pending_writes
        if "pending-contract-reconciliation" in str(destination):
            pending_writes += 1
            if pending_writes == 1:
                raise OSError("injected retry record failure")
        return original_replace(source, destination)

    monkeypatch.setattr(agent_bridge.os, "replace", fail_pending_replace)
    with pytest.raises(OSError, match="injected retry record failure"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert task_store.get("task_001").checkpoint.state_data["contract_revision"] == 2
    monkeypatch.setattr(agent_bridge.os, "replace", original_replace)
    if alter_plan:
        plan, current = storage.read_plan_file(plan_path)
        plan["tasks"]["task_core"]["next_action"] = "Unrelated later change"
        storage.save_plan_file(plan_path, plan, expected_revision=current, owner="test_agent")
        if alter_plan == "forged":
            import json
            pending_path = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation" / (hashlib.sha256(b"task_001").hexdigest() + ".json")
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            pending["projected_plan_revision"] = storage.read_plan_file(plan_path)[1]
            pending_path.write_text(json.dumps(pending), encoding="utf-8")
        with pytest.raises(RepoPlanConflictError):
            agent_bridge.reconcile_task_steering(task_store, **arguments)
        return
    assert agent_bridge.reconcile_task_steering(task_store, **arguments)["success"] is True
    assert task_store.get("task_001").checkpoint.state_data["contract_revision"] == 2


def test_retry_recovers_when_binding_write_fails(test_environment, monkeypatch):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_save = agent_bridge.TaskBindingManager._save
    calls = 0

    def fail_once(manager, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated binding write failure")
        return original_save(manager, *args, **kwargs)

    monkeypatch.setattr(agent_bridge.TaskBindingManager, "_save", fail_once)
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    result = agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert result["success"] is True
    assert task_store.get("task_001").checkpoint.state_data["contract_revision"] == 2
    assert len(storage.read_plan_file(plan_path)[0]["tasks"]["task_core"]["clarifications"]) == 1


def test_retry_rejects_tampered_pending_record_without_revising_task(test_environment, monkeypatch):
    import json

    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("failed")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    pending_path = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation" / (hashlib.sha256(b"task_001").hexdigest() + ".json")
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    pending["acceptance_criteria"] = ["tampered"]
    pending_path.write_text(json.dumps(pending), encoding="utf-8")
    monkeypatch.setattr(task_store, "revise_contract", original_revise)
    with pytest.raises(RepoPlanConflictError):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert task_store.get("task_001").checkpoint.state_data.get("contract_revision", 1) == 1
    assert pending_path.is_file()


def test_same_criteria_does_not_fake_recovery_when_pending_record_is_missing(test_environment, monkeypatch):
    root, storage, task_store, plan_path, plan_rev, spec = setup_bound_task(test_environment)
    original_spec = spec.read_bytes()
    criteria = list(task_store.get("task_001").contract.acceptance_criteria)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=criteria, expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("failed")))
    monkeypatch.setattr(agent_bridge, "_persist_pending_contract_reconciliation", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk failure")))
    with pytest.raises(RuntimeError, match="disk failure"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    with pytest.raises(RuntimeError, match="disk failure"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    assert storage.read_plan_file(plan_path)[1] == plan_rev
    assert spec.read_bytes() == original_spec
    assert task_store.get("task_001").checkpoint.state_data.get("contract_revision", 1) == 1


def test_retry_finishes_pending_record_after_binding_was_already_saved(test_environment, monkeypatch):
    from pathlib import Path

    root, _, task_store, _, plan_rev, spec = setup_bound_task(test_environment)
    arguments = dict(root=str(root), task_id="task_001", steering_id="steering_001",
        spec_rel_path="docs/feature.md", spec_content="updated\n",
        acceptance_criteria=["Updated requirement"], expected_revision=plan_rev,
        expected_spec_revision=hashlib.sha256(spec.read_bytes()).hexdigest())
    original_revise = task_store.revise_contract
    monkeypatch.setattr(task_store, "revise_contract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("failed")))
    with pytest.raises(RuntimeError, match="pending"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(task_store, "revise_contract", original_revise)
    pending_path = root / ".local-ai-hub" / "local" / "pending-contract-reconciliation" / (hashlib.sha256(b"task_001").hexdigest() + ".json")
    original_unlink = Path.unlink

    def fail_pending_unlink(path, *args, **kwargs):
        if path == pending_path:
            raise OSError("simulated removal failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_pending_unlink)
    with pytest.raises(OSError, match="simulated"):
        agent_bridge.reconcile_task_steering(task_store, **arguments)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert pending_path.is_file()
    assert agent_bridge.reconcile_task_steering(task_store, **arguments)["success"] is True
    assert not pending_path.exists()
