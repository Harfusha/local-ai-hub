from __future__ import annotations

import threading
from pathlib import Path

import pytest


@pytest.fixture
def http_post_paths(monkeypatch):
    from local_ai_hub import http_server

    paths = []
    original = http_server.Handler.do_POST

    def count_request(handler):
        paths.append(handler.path.split("?", 1)[0])
        return original(handler)

    monkeypatch.setattr(http_server.Handler, "do_POST", count_request)
    return paths


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n'
        '[agent_state]\nenabled = true\n'
        '[security]\n'
        'api_token_tenant = "sdk-test"\n'
        'tenant_derivation_key = "sdk-test-root-key-0123456789-abcdef"\n'
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(tenant="sdk-test", config_path=str(config), auto_start=False)
    try:
        yield app, client
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


@pytest.fixture
def root_scoped_live_client(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = tmp_path / "root-scoped-config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n'
        '[agent_state]\nenabled = true\n'
        '[security]\n'
        'api_token_tenant = "sdk-root-test"\n'
        'tenant_derivation_key = "t04-test-root-key-0123456789-abcdef"\n'
        f'allowed_roots = ["{workspace.as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_completion_revision_or_stop", lambda *_args: ("test-revision", None))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(tenant="sdk-root-test", config_path=str(config), auto_start=False)
    try:
        yield app, client, workspace
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def test_verification_sdk_methods_forward_root_through_allowed_http_route(root_scoped_live_client, tmp_path):
    _app, client, workspace = root_scoped_live_client
    root = str(workspace)
    created = client.create_task(
        "Verify a root-scoped SDK task",
        acceptance_criteria=["receipt accepted"],
        task_id="sdk-root-verification",
        root=root,
    )
    assert created.get("success") is True

    receipt = client.verify_receipt(
        "sdk-root-verification",
        "receipt accepted",
        passed=False,
        repository_revision="rev-sdk-test",
        root=root,
    )
    completion = client.verify_completion("sdk-root-verification", root=root)

    assert receipt.get("success") is True
    assert receipt["receipt"]["repository_revision"] == "rev-sdk-test"
    assert completion.get("success") is True
    rejected = client.verify_receipt(
        "sdk-root-verification",
        "receipt accepted",
        root=str(tmp_path / "outside-allowlist"),
    )
    assert rejected.get("success") is False


def test_git_history_sdk_forwards_canonical_filters_once():
    from local_ai_hub.client import HubClient

    client = HubClient.__new__(HubClient)
    calls = []
    client.post = lambda path, payload: calls.append((path, payload)) or {"success": True}
    result = client.git_history_search(
        "repo", "literal phrase", 12, author="Ada", since="2026-01-01",
        until="2026-01-31", path="src/a.py",
    )
    assert result == {"success": True}
    assert calls == [(
        "/api/git/history_search",
        {
            "root": "repo", "query": "literal phrase", "max_commits": 12,
            "author": "Ada", "since": "2026-01-01", "until": "2026-01-31",
            "path": "src/a.py",
        },
    )]


def test_sdk_convenience_methods_map_to_production_http_handlers(live_client, tmp_path, http_post_paths):
    app, client = live_client
    routes = []
    root = str(tmp_path)

    def callers(actual_root, symbol, limit):
        routes.append(("callers", actual_root, symbol, limit))
        return {"success": True, "callers": ["Example.call"]}

    def fast_context(actual_root, query, max_tokens):
        routes.append(("context", actual_root, query, max_tokens))
        return {"success": True, "context": ["indexed evidence"]}

    def cancel(tenant, job_id):
        routes.append(("cancel", tenant, job_id))
        return {"success": True, "job_id": job_id, "cancelled": True}

    def evidence(evidence_id, *, verify=True):
        routes.append(("evidence", evidence_id, verify))
        return {"success": True, "evidence_id": evidence_id, "verified": verify}

    app.services.callers = callers
    app.services.fast_context = fast_context
    app.async_jobs.cancel = cancel
    app.evidence.get = evidence

    before = len(http_post_paths)
    caller_result = client.callers(root, "Example", limit=7)
    assert caller_result["success"] is True
    assert http_post_paths[before:] == ["/api/repo/callers"]

    before = len(http_post_paths)
    context_result = client.context_pack(root, "find Example callers", max_tokens=512, mode="fast")
    assert context_result["success"] is True
    assert http_post_paths[before:] == ["/api/context/pack"]

    before = len(http_post_paths)
    cancel_result = client.cancel_job("job-123")
    assert cancel_result["success"] is True
    assert http_post_paths[before:] == ["/api/async-jobs"]

    before = len(http_post_paths)
    evidence_result = client.get_evidence("E123", verify=False)
    assert evidence_result["success"] is True
    assert http_post_paths[before:] == ["/api/evidence/get"]

    assert caller_result["callers"] == ["Example.call"]
    assert context_result["delivery_mode"] == "fast"
    assert cancel_result["cancelled"] is True
    assert evidence_result["verified"] is False
    assert routes == [
        ("callers", root, "Example", 7),
        ("context", root, "find Example callers", 512),
        ("cancel", "sdk-test", "job-123"),
        ("evidence", "E123", False),
    ]


def test_sdk_coord_pubsub_poll_maps_payload_to_production_handler(
    live_client, http_post_paths, monkeypatch, tmp_path
):
    from local_ai_hub import http_server

    app, client = live_client
    received = []
    payloads = []
    original_read_json = http_server.Handler._read_json

    def capture_payload(handler):
        payload = original_read_json(handler)
        payloads.append(payload)
        return payload

    monkeypatch.setattr(http_server.Handler, "_read_json", capture_payload)

    def poll(topic, since_timestamp=0.0, limit=50):
        received.append((topic, since_timestamp, limit))
        return {"success": True, "messages": [{"topic": topic, "message": "ready"}]}

    app.services.pubsub_poll = poll
    before = len(http_post_paths)
    result = client.coord(
        "pubsub_poll",
        root=str(tmp_path),
        topic="release",
        after_ts=123.5,
        limit=3,
    )

    assert result["success"] is True
    assert result["messages"] == [{"topic": "release", "message": "ready"}]
    assert http_post_paths[before:] == ["/api/coord/pubsub_poll"]
    assert payloads == [{
        "root": str(tmp_path),
        "topic": "release",
        "after_ts": 123.5,
        "limit": 3,
    }]
    assert received == [("release", 123.5, 3)]

    retired_alias = client.post(
        "/api/coord/pubsub_poll",
        {"root": str(tmp_path), "topic": "release", "since_timestamp": 123.5},
    )
    assert retired_alias["success"] is False
    assert retired_alias["status_code"] == 400
    assert received == [("release", 123.5, 3)]


def test_sdk_coord_pubsub_poll_none_timestamp_keeps_sequence_cursor(
    live_client, http_post_paths, monkeypatch, tmp_path
):
    _app, client = live_client
    from local_ai_hub import http_server

    payloads = []
    original_read_json = http_server.Handler._read_json

    def capture_payload(handler):
        payload = original_read_json(handler)
        payloads.append(payload)
        return payload

    monkeypatch.setattr(http_server.Handler, "_read_json", capture_payload)
    before = len(http_post_paths)
    result = client.coord(
        "pubsub_poll",
        root=str(tmp_path),
        topic="release",
        after_ts=None,
        after_seq=7,
        limit=2,
    )

    assert result["success"] is True
    assert http_post_paths[before:] == ["/api/coord/pubsub_poll"]
    assert payloads == [{
        "root": str(tmp_path),
        "topic": "release",
        "after_seq": 7,
        "limit": 2,
    }]


def test_sdk_coord_pubsub_poll_null_numeric_options_use_defaults(
    live_client, http_post_paths, monkeypatch, tmp_path
):
    _app, client = live_client
    before = len(http_post_paths)

    result = client.coord(
        "pubsub_poll", root=str(tmp_path), topic="release",
        after_ts=None, after_seq=None, limit=None,
    )

    assert result["success"] is True
    assert http_post_paths[before:] == ["/api/coord/pubsub_poll"]


def test_callers_finds_real_python_call_through_sdk_handler(live_client, tmp_path, http_post_paths):
    _app, client = live_client
    repo = tmp_path / "sdk-caller-repo"
    repo.mkdir()
    source = repo / "module.py"
    source.write_text(
        "def target():\n    return 'found'\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )

    result = client.callers(str(repo), "target")

    assert http_post_paths == ["/api/repo/callers"]
    assert result["success"] is True
    assert result["caller_count"] == 1
    assert result["callers"][0]["caller"] == "caller"
    assert result["callers"][0]["file"] == "module.py"
    assert result["callers"][0]["line"] == 5


def test_context_pack_rejects_invalid_mode_before_http(live_client, tmp_path, http_post_paths):
    _, client = live_client

    result = client.context_pack(str(tmp_path), "query", mode="invalid")

    assert http_post_paths == []
    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["error"] == "context mode must be adaptive, full or fast"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_sdk_resume_and_verification_use_real_agent_state_handlers(live_client, http_post_paths):
    from local_ai_hub.agent_tasks import TaskCheckpoint, TaskStatus

    app, client = live_client
    root = str(Path(__file__).resolve().parents[1])
    created = client.create_task(
        "SDK route flow",
        acceptance_criteria=["change_verified"],
        task_id="sdk-route-task",
        root=root,
    )
    assert created["success"] is True
    app.agent_tasks.transition(
        "sdk-route-task",
        TaskStatus.ACTIVE,
        reason="start route test",
        actor="sdk-test",
        idempotency_key="start-sdk-route-task",
    )
    checkpoint = TaskCheckpoint(
        phase="implementation",
        next_action="review changed paths",
        affected_paths=("src/example.py",),
        evidence_ids=("E-sdk-checkpoint",),
        state_data={"marker": "checkpoint-preserved"},
    )
    app.agent_tasks.checkpoint(
        "sdk-route-task",
        checkpoint,
        actor="sdk-test",
        idempotency_key="checkpoint-sdk-route-task",
    )

    http_post_paths.clear()
    resumed = client.coord(
        "task_resume",
        task_id="sdk-route-task",
        idempotency_key="resume-sdk-route-task",
        root=root,
    )
    assert http_post_paths == ["/api/agent-state/tasks"]
    http_post_paths.clear()
    evidence_id = app.artifacts.put_json(
        {
            "kind": "work_source_review",
            "task_id": "sdk-route-task",
            "owner": "generic",
            "repository_revision": "",
            "mutation_generation": 0,
            "passed": True,
            "criteria": ["change_verified"],
        },
        tenant="generic",
        kind="source_review",
    )
    assert evidence_id
    assert app.artifacts.get(evidence_id, tenant="generic")["success"] is True
    receipt = client.verify_receipt(
        "sdk-route-task",
        "change_verified",
        evidence_id=evidence_id,
        root=root,
    )
    assert http_post_paths == ["/api/agent-state/verification"]

    assert resumed["success"] is True
    assert resumed["task"]["status"] == TaskStatus.ACTIVE.value
    resumed_checkpoint = resumed["task"]["checkpoint"]
    assert resumed_checkpoint["phase"] == checkpoint.phase
    assert resumed_checkpoint["next_action"] == checkpoint.next_action
    assert resumed_checkpoint["affected_paths"] == list(checkpoint.affected_paths)
    assert resumed_checkpoint["evidence_ids"] == list(checkpoint.evidence_ids)
    assert resumed_checkpoint["state_data"]["marker"] == "checkpoint-preserved"
    assert resumed_checkpoint["state_data"]["repo_root"] == root
    assert resumed_checkpoint["state_data"]["_agent_task_scope"]["repo_root"] == root
    assert receipt["success"] is True, receipt
    assert receipt["receipt"]["criterion"] == "change_verified"


def test_continue_conversation_uses_real_http_handler_and_store(live_client, http_post_paths):
    app, client = live_client
    conversation = app.services.conversations.start("sdk-test", {
        "model": "test-model",
        "system": "test system",
        "max_tokens": 64,
        "temperature": 0.0,
        "source": "sdk-test",
        "priority": 0,
        "route": {"model": "test-model"},
    })
    generated = []

    def fake_generate(*args, **kwargs):
        generated.append((args, kwargs))
        return {"success": True, "text": "continued answer"}

    app.services._generate = fake_generate

    result = client.continue_conversation(conversation.conversation_id, "follow-up question")

    assert http_post_paths == ["/api/conversations/continue"]
    assert result["success"] is True
    assert result["text"] == "continued answer"
    assert result["conversation_id"] == conversation.conversation_id
    assert conversation.messages == [
        {"role": "user", "content": "TASK:\nfollow-up question\n"},
        {"role": "assistant", "content": "continued answer"},
    ]
    assert len(generated) == 1


def test_cancel_job_reaches_real_queue_through_sdk_handler(live_client, http_post_paths):
    app, client = live_client
    app.async_jobs._resource_admission = lambda: {
        "state": "accepted",
        "reason": "capacity_available",
        "retryable": False,
        "pressure_level": "nominal",
        "context_budget_factor": 1.0,
    }
    submitted = app.async_jobs.submit(
        "sdk-test",
        "reason",
        {"task": "cancel through SDK"},
        dispatch_delay_seconds=30,
    )

    result = client.cancel_job(submitted["job_id"])

    assert http_post_paths == ["/api/async-jobs"]
    assert result["success"] is True
    assert result["state"] == "cancelled"
    assert result["terminal"] is True
    assert app.async_jobs.status("sdk-test", submitted["job_id"])["state"] == "cancelled"


def test_get_evidence_fetches_real_store_record_through_sdk_handler(live_client, tmp_path, http_post_paths):
    import hashlib

    app, client = live_client
    repo = tmp_path / "sdk-evidence-repo"
    repo.mkdir()
    source = repo / "settings.toml"
    source.write_text('[sdk]\nanswer = "grounded evidence"\n', encoding="utf-8")
    evidence_id = app.evidence.put(str(repo), {
        "path": source.name,
        "text": source.read_text(encoding="utf-8"),
        "file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "start_line": 1,
        "end_line": 2,
    })
    assert evidence_id

    result = client.get_evidence(evidence_id)

    assert http_post_paths == ["/api/evidence/get"]
    assert result["success"] is True
    assert result["evidence_id"] == evidence_id
    assert result["path"] == source.name
    assert result["text"] == '[sdk]\nanswer = "grounded evidence"\n'
    assert result["stale"] is False


def test_context_pack_returns_indexed_evidence_from_real_fast_context(live_client, tmp_path, http_post_paths):
    app, client = live_client
    repo = tmp_path / "sdk-context-repo"
    repo.mkdir()
    source = repo / "settings.toml"
    source.write_text('[sdk]\ncontext_sentinel = "grounded local value"\n', encoding="utf-8")

    indexed = app.services.deterministic.update_file(str(repo), source.name)
    assert indexed["success"] is True

    result = client.context_pack(
        str(repo),
        "config context_sentinel",
        max_tokens=512,
        mode="fast",
    )

    assert http_post_paths == ["/api/context/pack"]
    assert result["success"] is True
    assert result["context_source"] == "deterministic-fast"
    assert result["semantic_used"] is False
    assert "context_sentinel" in result["context"]
    assert "grounded local value" in result["context"]
    assert any(str(item.get("path", "")).endswith(source.name) for item in result["evidence"])


def test_adaptive_context_pack_returns_grounded_indexed_evidence_offline(live_client, tmp_path, http_post_paths):
    app, client = live_client
    app.services.config.setdefault("features", {})["rag"] = False
    app.services.external_tools = None
    repo = tmp_path / "sdk-adaptive-context-repo"
    repo.mkdir()
    source = repo / "settings.toml"
    source.write_text('[sdk]\nadaptive_context_sentinel = "grounded adaptive value"\n', encoding="utf-8")

    indexed = app.services.deterministic.update_file(str(repo), source.name)
    assert indexed["success"] is True

    result = client.context_pack(
        str(repo),
        "config adaptive_context_sentinel",
        max_tokens=512,
        mode="adaptive",
    )

    assert http_post_paths == ["/api/context/pack"]
    assert result["success"] is True
    assert result["delivery_mode"] == "adaptive"
    assert result["retrieval"]["quality_first"] is True
    assert "deterministic" in result["retrieval"]["used_backends"]
    assert "lexical" in result["retrieval"]["used_backends"]
    assert result["retrieval"]["quality"]["evidence_count"] >= 1
    assert "adaptive_context_sentinel" in result["context"]
    assert "grounded adaptive value" in result["context"]
    assert any(str(item.get("path", "")).endswith(source.name) for item in result["evidence"])
