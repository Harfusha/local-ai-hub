from dataclasses import replace
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint, TaskState, TaskStatus
from local_ai_hub.opencode_verification import run_goal_project_verification


def test_goal_verification_binds_project_alias_and_forwards_broker_result(tmp_path):
    root = str(tmp_path.resolve())
    task = TaskState(task_id="task", status=TaskStatus.ACTIVE, owner="opencode-local",
                     contract=GoalContract(goal="Fix", acceptance_criteria=("quality",)),
                     context=ScopeContext(session_id="session"),
                     checkpoint=TaskCheckpoint(state_data={"_agent_task_scope": {"version": 2, "repo_root": root}}))
    tasks = SimpleNamespace(get=lambda task_id: task if task_id == "task" else None)
    settings = SimpleNamespace(commands={"test": "python -m pytest", "other": "python -V"},
                               verification_rules={"quality": ("test",)})
    project = SimpleNamespace(root=tmp_path.resolve(), settings=settings, config_digest="config-digest",
                              resolution=SimpleNamespace(error_codes=()))
    resolved = SimpleNamespace(alias="test", command="python -m pytest", environment={},
                               cache_context="context", config_digest="config-digest", caller_arguments=())
    calls = []
    result = {"success": False, "error": "broker refused"}
    broker = SimpleNamespace(config={"server": {"state_dir": str(tmp_path / "state")}},
                             _cached_project_command_context=lambda *_args: project,
                             _resolve_project_command=lambda *_args: resolved,
                             classify=lambda _command: {"class": "validation", "allowed": True, "replay_safe": True},
                             run=lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    returned = run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test")
    assert returned is result
    assert calls == [(('python -m pytest', root), {"task_id": "task", "criterion": "test", "bypass_cache": True,
                    "_project_command_context": resolved, "_environment_overrides": {}, "_cache_context": "context"})]

    for invalid_task in (replace(task, owner="someone-else"), replace(task, status=TaskStatus.COMPLETED),
                         replace(task, context=ScopeContext(session_id="other"))):
        tasks.get = lambda _task_id, value=invalid_task: value
        assert run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test")["success"] is False
    tasks.get = lambda _task_id: task
    assert run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="other")["success"] is False
    assert run_goal_project_verification(tasks, broker, root=str(tmp_path.parent), task_id="task", session_id="session", alias="test")["success"] is False
    assert len(calls) == 1
    settings.verification_rules = {"quality": ()}
    assert run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test")["success"] is False
    settings.verification_rules = {}
    direct = replace(task, contract=GoalContract(goal="Fix", acceptance_criteria=("test",)))
    tasks.get = lambda _task_id: direct
    broker.classify = lambda _command: {"class": "unknown", "allowed": True, "replay_safe": False}
    assert run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test")["error_code"] == "goal_command_not_validation"
    assert len(calls) == 1
    broker.classify = lambda _command: {"class": "validation", "allowed": True, "replay_safe": True}
    resolved.config_digest = "changed"
    assert run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test")["error_code"] == "goal_project_configuration_changed"
    resolved.config_digest = "config-digest"
    assert run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test") is result
    def lost(*_args, **_kwargs):
        raise TimeoutError("outcome unknown")
    broker.run = lost
    unknown = run_goal_project_verification(tasks, broker, root=root, task_id="task", session_id="session", alias="test")
    assert unknown["outcome_unknown"] is True and unknown["retryable"] is False


def test_goal_verification_uses_real_broker_and_persisted_receipts(tmp_path, monkeypatch):
    import json
    import threading
    import urllib.error
    import urllib.request
    from local_ai_hub import http_server
    from local_ai_hub.opencode_boundary import derive_local_profile_token
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.project_config import resolve_project_context

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q test_ok.py -p no:cacheprovider"\n'
        'failing = "python -m pytest -q test_fail.py -p no:cacheprovider"\n', encoding="utf-8")
    (root / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (root / "test_fail.py").write_text("def test_failure():\n    assert False\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(f'[server]\nstate_dir = "{state.as_posix()}"\nauto_start_ollama = false\n'
                      '[agent_state]\nenabled = true\n[ollama]\nenabled = false\n'
                      '[llama_cpp]\nmode = "off"\n[background_gpu]\nenabled = false\n'
                      f'[preprocessing]\nenabled = false\n[security]\napi_token = "{"x" * 40}"\n'
                      f'allowed_roots = ["{root.as_posix()}"]\n', encoding="utf-8")
    app = LocalAIApp(str(config))
    try:
        repository_id = resolve_project_context(root, state).coordination_id
        for task_id, criterion in (("pass-task", "test"), ("fail-task", "failing")):
            app.agent_tasks.create(GoalContract(goal="Fix", acceptance_criteria=(criterion,)),
                                   ScopeContext(task_id=task_id, repository_id=repository_id, session_id="session"),
                                   task_id=task_id, actor="opencode-local", repo_root=str(root))
        passed = run_goal_project_verification(app.agent_tasks, app.commands, root=str(root),
                                               task_id="pass-task", session_id="session", alias="test")
        assert passed.get("success") is True, passed.get("error")
        receipt = passed.get("verification_receipt")
        assert isinstance(receipt, dict) and receipt.get("passed") is True
        assert receipt.get("task_id") == "pass-task" and receipt.get("criterion") == "test"
        assert receipt.get("owner") == "opencode-local" and receipt.get("command_id") and receipt.get("evidence_id")
        failed = run_goal_project_verification(app.agent_tasks, app.commands, root=str(root),
                                               task_id="fail-task", session_id="session", alias="failing")
        assert failed.get("success") is False
        assert not failed.get("verification_receipt")
        assert app.agent_tasks.get("fail-task").status != TaskStatus.COMPLETED
        app.agent_tasks.create(GoalContract(goal="Fix", acceptance_criteria=("test",)),
                               ScopeContext(task_id="http-task", repository_id=repository_id, session_id="session"),
                               task_id="http-task", actor="opencode-local", repo_root=str(root))
        monkeypatch.setattr(http_server, "APP", app)
        nonce = "n" * 32
        monkeypatch.setattr(app.opencode_provider, "status", lambda: {"success": True, "state": "running", "nonce": nonce})
        restricted = derive_local_profile_token(nonce)
        server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        calls = []
        original = app.commands.run
        def run(*args, **kwargs):
            calls.append(True)
            return original(*args, **kwargs)
        monkeypatch.setattr(app.commands, "run", run)
        body = {"action": "project_command", "root": str(root), "task_id": "http-task",
                "session_id": "session", "alias": "test"}
        def post(payload, request_id="a" * 32, token=restricted):
            headers = {"Content-Type": "application/json", "X-LocalAI-Token": token, "X-LocalAI-Agent": "cloud-agent"}
            if request_id is not None:
                headers["X-LocalAI-Request-ID"] = request_id
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/verification",
                data=json.dumps(payload).encode(), method="POST", headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        try:
            with pytest.raises(urllib.error.HTTPError) as missing_id:
                post(body, request_id=None)
            assert missing_id.value.code == 400
            missing_id.value.close()
            with pytest.raises(urllib.error.HTTPError) as master_denied:
                post(body, request_id="b" * 32, token="x" * 40)
            assert master_denied.value.code == 403
            master_denied.value.close()
            mismatch = post({**body, "session_id": "other"}, request_id="c" * 32)
            assert mismatch["success"] is False and mismatch["error_code"] == "goal_binding_mismatch"
            with monkeypatch.context() as scoped_patch:
                scoped_patch.setattr(app, "recovery", None)
                with pytest.raises(urllib.error.HTTPError) as no_journal:
                    post(body, request_id="d" * 32)
                assert no_journal.value.code == 503
                no_journal.value.close()
            with monkeypatch.context() as scoped_patch:
                scoped_patch.setattr(app, "recovery", SimpleNamespace(begin=lambda **_: {}, wait_for=lambda **_: {}))
                with pytest.raises(urllib.error.HTTPError) as fake_journal:
                    post(body, request_id="e" * 32)
                assert fake_journal.value.code == 503
                fake_journal.value.close()
            assert calls == []
            first = post(body)
            replay = post(body)
            assert first["success"] is True and replay["success"] is True
            assert first["verification_receipt"]["receipt_id"] == replay["verification_receipt"]["receipt_id"]
            assert calls == [True]
            with pytest.raises(urllib.error.HTTPError) as conflict:
                post({**body, "alias": "failing"})
            assert conflict.value.code == 409
            conflict.value.close()
            assert calls == [True]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    finally:
        app.close()
