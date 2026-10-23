from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from local_ai_hub import http_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.agent_verification import VerificationReceipt
from local_ai_hub.app import LocalAIApp
from local_ai_hub.project_config import resolve_project_context


def test_context_pack_after_task_resume_keeps_memory_scoped_fresh_and_bounded(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    project_context = resolve_project_context(root, state_dir)
    coordination_id = project_context.coordination_id
    assert isinstance(coordination_id, str) and coordination_id
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        "\n[debug_traces]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        task_id = "task-context-pack-resume"
        task = app.agent_tasks.create(
            GoalContract(goal="Resume scoped context task", acceptance_criteria=("context pack",)),
            ScopeContext(repository_id=coordination_id, task_id=task_id, session_id="session-a"),
            task_id=task_id,
            repo_root=str(root),
        )
        assert task.status.value == "planned"
        resumed = app.agent_tasks.resume(task_id)
        assert resumed.status.value == "active"
        compiled_requests = []
        compile_context = app.agent_context.compile

        def capture_context_request(request):
            compiled_requests.append(request)
            return compile_context(request)

        app.agent_context.compile = capture_context_request

        safe = app.agent_memory.record(MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope="repository",
            key="safe fact",
            value="repository fresh value",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": str(root), "repository_id": coordination_id},
            repository_revision="revision-1",
            path_refs=("src/keep.py",),
        ))
        stale = app.agent_memory.record(MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope="repository",
            key="stale fact",
            value="old changed-path value",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": str(root), "repository_id": coordination_id},
            repository_revision="revision-0",
            path_refs=("src/changed.py",),
        ))
        app.agent_memory.record(MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope="session",
            key="session-only fact",
            value="session-b private value",
            scope_id="session-b",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": str(root), "repository_id": coordination_id},
            repository_revision="revision-1",
            path_refs=("src/keep.py",),
        ))
        assert app.agent_memory.mark_stale_for_revision(str(root), "revision-1", ["src/changed.py"]) == 1
        assert app.agent_memory.get(stale.record_id, root=str(root), repository_id=coordination_id).status is MemoryStatus.STALE

        app.services.adaptive_context_pack = lambda *_args, **_kwargs: {
            "success": True,
            "context": "repository evidence",
            "repo_revision": "revision-1",
            "evidence": [],
        }
        request_payload = {
            "root": str(root),
            "query": "resume task context",
            "task_id": task_id,
            "phase": "review",
            "repository_revision": "revision-1",
            "clone_id": "clone-current",
            "worktree_id": "worktree-current",
            "branch": "feature/context-pack",
            "repository_id": coordination_id,
            "session_id": "session-a",
            "include_diagnostics": True,
            "max_tokens": 128,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/context/pack",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))

        assert result["success"] is True
        assert result["task_context"]["complete"] is True
        assert "repository fresh value" in result["task_context"]["text"]
        assert "old changed-path value" not in result["task_context"]["text"]
        assert "session-b private value" not in result["task_context"]["text"]
        assert len(result["task_context"]["text"]) <= 128 * 4
        assert len(compiled_requests) == 1
        assert compiled_requests[0].session_id == "session-a"
        assert compiled_requests[0].clone_id == "clone-current"
        assert compiled_requests[0].worktree_id == "worktree-current"
        assert compiled_requests[0].branch == "feature/context-pack"
        assert compiled_requests[0].repository_id == coordination_id
        assert compiled_requests[0].repository_revision == "revision-1"
        assert compiled_requests[0].include_diagnostics is True

        class FailedMemoryStore:
            def find_for_context(self, **_kwargs):
                raise OSError("memory backend unavailable")

        app.agent_context.memory_store = FailedMemoryStore()
        degraded_request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/context/pack",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(degraded_request) as response:
            degraded = json.loads(response.read().decode("utf-8"))
        assert degraded["success"] is True
        assert degraded["task_context"]["complete"] is True
        assert any(warning["code"] == "memory_context_unavailable" for warning in degraded["task_context"]["warnings"])
        assert "repository fresh value" not in degraded["task_context"]["text"]

        app.services.adaptive_context_pack = lambda *_args, **_kwargs: {
            "success": False,
            "terminal": False,
            "retryable": True,
            "degraded": True,
            "degraded_reason": "repository_context_unavailable",
            "error": "repository index temporarily unavailable",
        }
        unavailable_request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/context/pack",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(unavailable_request) as response:
                unavailable_status = response.status
                unavailable = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            unavailable_status = error.code
            unavailable = json.loads(error.read().decode("utf-8"))
        assert unavailable_status == 503
        assert unavailable["success"] is False
        assert unavailable["stop_code"] == "context_task_context_incomplete"
        assert "Resume scoped context task" in unavailable["task_context"]["text"]
        assert unavailable["task_context"]["repository"]["degraded"] is True
        assert any(
            element["element_id"] == safe.record_id
            for element in result["task_context"]["agent_state"]["elements"]
        )
        task = app.agent_tasks.get(task_id)
        evidence_id = app.artifacts.put_json(
            {
                "kind": "work_source_review",
                "passed": True,
                "task_id": task_id,
                "owner": task.owner,
                "criteria": ["context pack"],
                "repository_revision": "revision-1",
                "mutation_generation": 0,
                "details": {"context_id": result["task_context"]["context_id"], "complete": True},
            },
            kind="source_review",
        )
        receipt = app.agent_verification.record(VerificationReceipt.create(
            task_id=task_id,
            criterion="context pack",
            evidence_id=evidence_id,
            repository_revision="revision-1",
            owner=task.owner,
            details={"context_id": result["task_context"]["context_id"], "complete": True},
        ))
        completion = app.agent_verification.completion(task_id, current_revision="revision-1")
        assert app.agent_tasks.get(task_id).verification_receipts["context pack"] == receipt.receipt_id
        assert completion.complete is True
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()
