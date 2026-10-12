from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub import http_server, trace_context
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus
from local_ai_hub.app import LocalAIApp
from local_ai_hub.token_accounting import json_tokens


def _public_task_client(tmp_path: Path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind="127.0.0.1"\nstate_dir="{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled=true\n",
        encoding="utf-8",
    )
    root = tmp_path / "repo"
    root.mkdir()
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda _self: True)
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda _self: "tenant-a")
    monkeypatch.setattr(http_server.Handler, "_agent", lambda _self: "test-agent")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: self._payload)
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda _self, _path, _payload: None)

    def begin_trace(handler, _path):
        handler._trace_request_id = handler._request_id
        handler._debug_trace_id = ""

    monkeypatch.setattr(http_server.Handler, "_begin_trace", begin_trace)

    def post(
        payload: dict,
        request_id: str,
        path: str = "/api/agent-state/tasks",
    ) -> tuple[int, dict]:
        payload.setdefault("root", str(root))
        handler = object.__new__(http_server.Handler)
        handler.path = path
        handler.command = "POST"
        handler.headers = {"Content-Type": "application/json", "Idempotency-Key": request_id}
        handler._payload = payload
        handler._request_id = request_id
        handler.client_address = ("127.0.0.1", 10000)
        handler.server = object()
        responses: list[tuple[int, dict]] = []
        handler._send = lambda status, data: responses.append((status, data))
        token = trace_context.set_context(tenant="tenant-a")
        try:
            http_server.Handler.do_POST(handler)
        finally:
            trace_context.reset_context(token)
        assert len(responses) == 1, responses
        return responses[0]

    return app, root, post


def test_http_task_checkpoint_cannot_replace_server_memory_context(tmp_path: Path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind="127.0.0.1"\nstate_dir="{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled=true\n",
        encoding="utf-8",
    )
    root = tmp_path / "repo"
    root.mkdir()
    app = LocalAIApp(str(config))
    try:
        record = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="verified fact",
            value="keep authoritative memory context",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        )
        app.agent_memory.record(record, actor="user", idempotency_key="seed-http-memory")
        monkeypatch.setattr(http_server, "APP", app)
        monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda _self: True)
        monkeypatch.setattr(http_server.Handler, "_tenant", lambda _self: "tenant-a")
        monkeypatch.setattr(http_server.Handler, "_agent", lambda _self: "test-agent")
        monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: self._payload)
        monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda _self, _path, _payload: None)

        def begin_trace(handler, _path):
            handler._trace_request_id = handler._request_id
            handler._debug_trace_id = ""

        monkeypatch.setattr(http_server.Handler, "_begin_trace", begin_trace)

        def post(payload: dict, request_id: str) -> tuple[int, dict]:
            payload.setdefault("root", str(root))
            handler = object.__new__(http_server.Handler)
            handler.path = "/api/agent-state/tasks"
            handler.command = "POST"
            handler.headers = {"Content-Type": "application/json"}
            handler._payload = payload
            handler._request_id = request_id
            handler.client_address = ("127.0.0.1", 10000)
            handler.server = object()
            responses: list[tuple[int, dict]] = []
            handler._send = lambda status, data: responses.append((status, data))
            token = trace_context.set_context(tenant="tenant-a")
            try:
                http_server.Handler.do_POST(handler)
            finally:
                trace_context.reset_context(token)
            assert len(responses) == 1, responses
            return responses[0]

        task_id = "http-memory-owned"
        status, created = post(
            {
                "action": "create",
                "task_id": task_id,
                "root": str(root),
                "repo_root": str(root),
                "contract": {"goal": "Use relevant verified memory"},
                "context": {"repository_id": str(root), "branch": "main", "task_id": task_id},
            },
            "http-create-memory-task",
        )
        assert status == 200 and created["success"] is True, created
        authoritative = created["task"]["checkpoint"]["state_data"]["memory_context"]
        assert [item["id"] for item in authoritative["items"]] == [record.record_id]

        before = app.agent_tasks.get(task_id)
        assert before is not None
        before_events = app.agent_state.events(f"task:{task_id}")
        forged = {
            "action": "checkpoint",
            "task_id": task_id,
            "checkpoint": {
                "phase": "work",
                "next_action": "attacker supplied empty context",
                "state_data": {"memory_context": {"items": [], "warnings": []}},
            },
        }
        status, rejected = post(forged, "http-forged-memory-context")

        assert status == 400, rejected
        assert rejected["success"] is False
        after = app.agent_tasks.get(task_id)
        assert after is not None
        assert after.checkpoint.to_dict() == before.checkpoint.to_dict()
        after_events = app.agent_state.events(f"task:{task_id}")
        assert [(event.event_id, event.seq) for event in after_events] == [
            (event.event_id, event.seq) for event in before_events
        ]
        assert after.checkpoint.state_data["memory_context"] == authoritative

        status, identical = post(
            {
                "action": "checkpoint",
                "task_id": task_id,
                "checkpoint": {
                    "phase": "work",
                    "next_action": "same server context retained",
                    "state_data": {
                        "memory_context": authoritative,
                        "memory_audit": {"used_ids": [record.record_id]},
                    },
                },
            },
            "http-identical-memory-context",
        )
        assert status == 200 and identical["success"] is True, identical
        assert identical["task"]["checkpoint"]["state_data"]["memory_context"] == authoritative

        for task_status in ("active", "verifying"):
            status, response = post(
                {"action": "transition", "task_id": task_id, "status": task_status},
                f"http-transition-{task_status}",
            )
            assert status == 200 and response["success"] is True, response
        status, response = post(
            {
                "action": "checkpoint",
                "task_id": task_id,
                "checkpoint": {"phase": "verify", "state_data": {"memory_audit": {"used_ids": []}}},
            },
            "http-empty-memory-audit",
        )
        assert status == 400 and "used memory IDs or not_used_reason" in response["error"], response
        retained = app.agent_tasks.get(task_id)
        assert retained is not None
        assert retained.checkpoint.state_data["memory_audit"] == {"used_ids": [record.record_id]}
        assert retained.checkpoint.state_data["memory_context"] == authoritative

        status, response = post(
            {
                "action": "checkpoint",
                "task_id": task_id,
                "checkpoint": {
                    "phase": "verify",
                    "state_data": {"memory_audit": {"used_ids": [], "not_used_reason": "the fact did not affect this task"}},
                },
            },
            "http-valid-memory-reason",
        )
        assert status == 200 and response["success"] is True, response
        assert response["task"]["checkpoint"]["state_data"]["memory_context"] == authoritative
        status, completed = post({"action": "complete", "task_id": task_id}, "http-complete-with-memory-reason")
        assert status == 200 and completed["success"] is True, completed
    finally:
        app.close()


def test_memory_delete_route_passes_verified_repository_identity(tmp_path: Path, monkeypatch):
    app, root, post = _public_task_client(tmp_path, monkeypatch)
    record = app.agent_memory.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="http-delete-memory",
        value="delete through scoped route",
        provenance={"root": str(root), "tenant": "tenant-a"},
    ))

    try:
        status, result = post(
            {
                "action": "delete",
                "record_id": record.record_id,
                "scope": "repository",
                "root": str(root),
            },
            "http-delete-memory",
            path="/api/agent-state/memory",
        )

        assert status == 200 and result["deleted"] is True, result
        assert app.agent_memory.get(record.record_id) is None
    finally:
        app.close()


def test_public_task_create_resume_and_checkpoint_audit_memory_per_attempt(
    tmp_path: Path, monkeypatch
):
    app, root, post = _public_task_client(tmp_path, monkeypatch)
    try:
        first = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="first verified task fact",
            value="first verified task fact",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        )
        app.agent_memory.record(first, actor="user", idempotency_key="seed-first-fact")

        wrong_root = tmp_path / "other-repo"
        wrong_root.mkdir()
        wrong_root_fact = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(wrong_root),
            key="fact from another repository",
            value="fact from another repository",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(wrong_root), "tenant": "tenant-a"},
        )
        app.agent_memory.record(
            wrong_root_fact, actor="user", idempotency_key="seed-wrong-root-fact"
        )
        wrong_tenant_fact = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="fact from another tenant",
            value="fact from another tenant",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-b"},
        )
        app.agent_memory.record(
            wrong_tenant_fact, actor="user", idempotency_key="seed-wrong-tenant-fact"
        )

        status, created = post(
            {
                "action": "create",
                "task_id": "public-memory-resume",
                "root": str(root),
                "repo_root": str(root),
                "contract": {"goal": "Use first and later verified task facts"},
                "context": {"repository_id": str(root), "task_id": "public-memory-resume"},
            },
            "public-memory-create",
        )
        assert status == 200 and created["success"] is True, created
        initial_context = created["task"]["checkpoint"]["state_data"]["memory_context"]
        assert [item["id"] for item in initial_context["items"]] == [first.record_id]

        status, started = post(
            {"action": "transition", "task_id": "public-memory-resume", "status": "active"},
            "public-memory-start",
        )
        assert status == 200 and started["success"] is True, started
        status, used = post(
            {
                "action": "checkpoint",
                "task_id": "public-memory-resume",
                "checkpoint": {
                    "phase": "work",
                    "state_data": {"memory_audit": {"used_ids": [first.record_id]}},
                },
            },
            "public-memory-used-audit",
        )
        assert status == 200 and used["success"] is True, used
        status, blocked = post(
            {"action": "transition", "task_id": "public-memory-resume", "status": "blocked"},
            "public-memory-block",
        )
        assert status == 200 and blocked["success"] is True, blocked

        later = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="later verified task fact",
            value="later verified task fact",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        )
        app.agent_memory.record(later, actor="user", idempotency_key="seed-later-fact")
        status, resumed = post(
            {"action": "resume", "task_id": "public-memory-resume"},
            "public-memory-resume",
        )
        assert status == 200 and resumed["success"] is True, resumed
        resumed_state = resumed["task"]["checkpoint"]["state_data"]
        assert {item["id"] for item in resumed_state["memory_context"]["items"]} == {
            first.record_id,
            later.record_id,
        }
        assert resumed_state["memory_audit"] is None
        assert resumed_state["memory_audit_history"][-1] == {"used_ids": [first.record_id]}

        status, verifying = post(
            {"action": "transition", "task_id": "public-memory-resume", "status": "verifying"},
            "public-memory-verifying",
        )
        assert status == 200 and verifying["success"] is True, verifying
        reason = "Current task did not rely on these advisory facts"
        status, unused = post(
            {
                "action": "checkpoint",
                "task_id": "public-memory-resume",
                "checkpoint": {
                    "phase": "verify",
                    "state_data": {"memory_audit": {"used_ids": [], "not_used_reason": reason}},
                },
            },
            "public-memory-not-used-audit",
        )
        assert status == 200 and unused["success"] is True, unused
        status, completed = post(
            {"action": "complete", "task_id": "public-memory-resume"},
            "public-memory-complete",
        )
        assert status == 200 and completed["success"] is True, completed
        final_state = completed["task"]["checkpoint"]["state_data"]
        assert final_state["memory_audit"]["not_used_reason"] == reason
        assert {item["id"] for item in final_state["memory_context"]["items"]} == {
            first.record_id,
            later.record_id,
        }
    finally:
        app.close()


def test_public_transition_checkpoint_is_guarded_and_completion_uses_supplied_checkpoint(
    tmp_path: Path, monkeypatch
):
    app, root, post = _public_task_client(tmp_path, monkeypatch)
    try:
        record = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="public transition memory fact",
            value="public transition memory fact",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        )
        app.agent_memory.record(record, actor="user", idempotency_key="seed-public-transition-fact")
        status, created = post(
            {
                "action": "create",
                "task_id": "public-transition-memory",
                "root": str(root),
                "repo_root": str(root),
                "contract": {"goal": "Guard transition checkpoints"},
                "context": {"repository_id": str(root), "task_id": "public-transition-memory"},
            },
            "public-transition-memory-create",
        )
        assert status == 200 and created["success"] is True, created
        authoritative = created["task"]["checkpoint"]["state_data"]["memory_context"]
        assert [item["id"] for item in authoritative["items"]] == [record.record_id]

        status, started = post(
            {"action": "transition", "task_id": "public-transition-memory", "status": "active"},
            "public-transition-memory-start",
        )
        assert status == 200 and started["success"] is True, started
        status, audited = post(
            {
                "action": "checkpoint",
                "task_id": "public-transition-memory",
                "checkpoint": {"state_data": {"memory_audit": {"used_ids": [record.record_id]}}},
            },
            "public-transition-memory-audit",
        )
        assert status == 200 and audited["success"] is True, audited

        forged_context = dict(authoritative)
        forged_context["items"] = []
        for index, memory_context in enumerate((forged_context, None)):
            status, rejected = post(
                {
                    "action": "transition",
                    "task_id": "public-transition-memory",
                    "status": "verifying",
                    "checkpoint": {"phase": "verify", "state_data": {"memory_context": memory_context}},
                },
                f"public-transition-memory-forged-context-{index}",
            )
            assert status == 400 and "memory_context is server-managed" in rejected["error"], rejected
            status, current = post(
                {"action": "get", "task_id": "public-transition-memory"},
                f"public-transition-memory-state-{index}",
            )
            assert status == 200 and current["task"]["status"] == "active", current
            assert current["task"]["checkpoint"]["state_data"]["memory_context"] == authoritative

        status, verifying = post(
            {
                "action": "transition",
                "task_id": "public-transition-memory",
                "status": "verifying",
                "checkpoint": {"phase": "verify", "state_data": {"verification_note": "ready"}},
            },
            "public-transition-memory-verify",
        )
        assert status == 200 and verifying["success"] is True, verifying
        verifying_state = verifying["task"]["checkpoint"]["state_data"]
        assert verifying_state["memory_context"] == authoritative
        assert verifying_state["memory_audit"] == {"used_ids": [record.record_id]}

        status, rejected_audit = post(
            {
                "action": "transition",
                "task_id": "public-transition-memory",
                "status": "completed",
                "checkpoint": {"phase": "verify", "state_data": {"memory_audit": {"used_ids": ["forged"]}}},
            },
            "public-transition-memory-invalid-completion-audit",
        )
        assert status == 400 and "memory_audit references unavailable memory IDs" in rejected_audit["error"], rejected_audit
        status, current = post(
            {"action": "get", "task_id": "public-transition-memory"},
            "public-transition-memory-after-rejection",
        )
        assert status == 200 and current["task"]["status"] == "verifying", current
        assert current["task"]["checkpoint"] == verifying["task"]["checkpoint"]

        reason = "The task did not rely on advisory memory."
        status, completed = post(
            {
                "action": "transition",
                "task_id": "public-transition-memory",
                "status": "completed",
                "checkpoint": {
                    "phase": "verify",
                    "state_data": {"memory_audit": {"used_ids": [], "not_used_reason": reason}},
                },
            },
            "public-transition-memory-valid-completion-audit",
        )
        assert status == 200 and completed["success"] is True, completed
        final_state = completed["task"]["checkpoint"]["state_data"]
        assert final_state["memory_context"] == authoritative
        assert final_state["memory_audit"] == {"used_ids": [], "not_used_reason": reason}
    finally:
        app.close()


def test_public_task_memory_unavailable_is_bounded_and_redacted(
    tmp_path: Path, monkeypatch, caplog
):
    app, root, post = _public_task_client(tmp_path, monkeypatch)
    private_backend_detail = "private backend failure detail"

    class UnavailableCompiler:
        requests = []

        def compile(self, request):
            self.requests.append(request)
            raise RuntimeError(private_backend_detail)

    compiler = UnavailableCompiler()
    app.agent_tasks.set_memory_adoption(
        memory_store=app.agent_memory,
        context_compiler=compiler,
        incident_store=app.agent_incidents,
    )
    caplog.clear()
    try:
        status, created = post(
            {
                "action": "create",
                "task_id": "public-memory-unavailable",
                "root": str(root),
                "repo_root": str(root),
                "contract": {"goal": "Continue when advisory memory lookup is unavailable"},
                "context": {"repository_id": str(root), "task_id": "public-memory-unavailable"},
            },
            "public-memory-unavailable-create",
        )
        assert status == 200 and created["success"] is True, created
        memory_context = created["task"]["checkpoint"]["state_data"]["memory_context"]
        assert memory_context["items"] == []
        assert memory_context["estimated_tokens"] == json_tokens(memory_context)
        assert json_tokens(memory_context) <= 512
        assert memory_context["warnings"] == [{"code": "memory_context_unavailable"}]
        assert len(compiler.requests) == 1
        assert compiler.requests[0].token_budget == 512
        assert private_backend_detail not in repr(created)
        assert all(private_backend_detail not in record.getMessage() for record in caplog.records)
    finally:
        app.close()
