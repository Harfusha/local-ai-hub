from __future__ import annotations

import inspect
from typing import Any

from local_ai_hub import mcp_server


class _Backend:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any]]] = []

    def post(self, path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("POST", path, payload, kwargs))
        return self.response

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("GET", path, None, kwargs))
        return self.response


def _enable_rag(monkeypatch: Any, backend: _Backend) -> None:
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", False)
    monkeypatch.setattr(mcp_server, "_timeout", lambda kind: {"quick": 11.0, "long": 77.0}[kind])


def _enable_work(monkeypatch: Any, backend: _Backend) -> None:
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.FEATURES, "work_orchestrator", True)
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", False)
    monkeypatch.setattr(mcp_server, "_timeout", lambda kind: {"quick": 11.0, "long": 77.0}[kind])


def _assert_response_fields(result: Any, expected: dict[str, Any]) -> None:
    assert isinstance(result, dict)
    for key, value in expected.items():
        assert result.get(key) == value
    budget = result.get("response_budget")
    if budget is not None:
        assert isinstance(budget, dict)
        assert budget["requested_tokens"] >= 128
        assert 0 <= budget["returned_tokens"] <= budget["requested_tokens"]


def test_mcp_rag_index_forwards_root_and_workspace(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "indexed_files": 4, "revision": "rag-rev-4"}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)

    result = mcp_server.local_ai_rag(action="index", root=str(tmp_path))

    assert backend.calls == [
        ("POST", "/api/rag/index", {"root": str(tmp_path), "workspace": mcp_server.canonical_workspace_id(str(tmp_path))}, {"timeout": 77.0})
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_rag_search_clamps_top_k_and_uses_root_workspace_default(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "results": [{"path": "guide.md", "score": 0.91, "text": "match"}]}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)

    result = mcp_server.local_ai_rag(action="search", root=str(tmp_path), query="release gate", top_k=99)

    assert backend.calls == [
        (
            "POST",
            "/api/rag/search",
            {"root": str(tmp_path), "query": "release gate", "workspace": mcp_server.canonical_workspace_id(str(tmp_path)), "top_k": 12, "use_reranker": True},
            {},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_rag_list_returns_available_workspace_records(monkeypatch: Any) -> None:
    response = {"success": True, "workspaces": [{"name": "docs", "documents": 3}]}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)

    result = mcp_server.local_ai_rag(action="list")

    assert backend.calls == [("GET", "/api/rag/workspaces", None, {})]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_rag_docset_index_uses_query_as_name_and_returns_index_receipt(
    monkeypatch: Any, tmp_path: Any
) -> None:
    response = {"success": True, "docset": "release-notes", "indexed_documents": 2}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)

    result = mcp_server.local_ai_rag(action="docset_index", root=str(tmp_path), query="release-notes")

    assert backend.calls == [
        ("POST", "/api/rag/docset/index", {"name": "release-notes", "root": str(tmp_path)}, {"timeout": 77.0})
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_rag_docset_search_defaults_name_and_clamps_top_k(monkeypatch: Any) -> None:
    response = {"success": True, "matches": [{"document_id": "d-2", "text": "verified release"}]}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)

    result = mcp_server.local_ai_rag(action="docset_search", query="verified release", top_k=0)

    assert backend.calls == [
        (
            "POST",
            "/api/rag/docset/search",
            {"name": "default", "query": "verified release", "top_k": 1},
            {},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_rag_ingest_document_forwards_content_and_quick_timeout(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "queued", "document_id": "doc-17"}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)
    content = "Operator approved release procedure."
    title = "Release procedure"
    metadata = {"task_id": "task-17", "source": "operator"}
    explicit_ingest = "content" in inspect.signature(mcp_server.local_ai_rag).parameters
    ingest_args = (
        {"content": content, "title": title, "metadata": metadata}
        if explicit_ingest
        else {"query": content}
    )

    result = mcp_server.local_ai_rag(
        action="ingest_document", root=str(tmp_path.resolve()), **ingest_args
    )

    expected_payload = {
        "root": str(tmp_path.resolve()),
        "workspace": mcp_server.canonical_workspace_id(str(tmp_path.resolve())),
        "content": content,
    }
    if explicit_ingest:
        expected_payload.update({"title": title, "metadata": metadata})
    assert backend.calls == [
        (
            "POST",
            "/api/rag/ingest_document",
            expected_payload,
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_rag_ingest_diagram_forwards_image_path_and_caption(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "ingested", "diagram_id": "diagram-5"}
    backend = _Backend(response)
    _enable_rag(monkeypatch, backend)
    image_path = "artifacts/system-map.png"
    caption = "Gateway routes to worker pool"
    metadata = {"task_id": "task-17", "source": "architecture"}
    explicit_ingest = "image_path" in inspect.signature(mcp_server.local_ai_rag).parameters
    ingest_args = (
        {"image_path": image_path, "caption": caption, "metadata": metadata}
        if explicit_ingest
        else {"query": image_path, "extra_fields": [caption]}
    )

    result = mcp_server.local_ai_rag(
        action="ingest_diagram",
        root=str(tmp_path.resolve()),
        **ingest_args,
    )

    expected_payload = {
        "root": str(tmp_path.resolve()),
        "workspace": mcp_server.canonical_workspace_id(str(tmp_path.resolve())),
        "image_path": image_path,
        "caption": caption,
    }
    if explicit_ingest:
        expected_payload["metadata"] = metadata
    assert backend.calls == [
        (
            "POST",
            "/api/rag/ingest_diagram",
            expected_payload,
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_work_submit_forwards_closed_task_contract(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "work_id": "work-101", "status": "queued", "task_id": "task-101"}
    backend = _Backend(response)
    _enable_work(monkeypatch, backend)

    result = mcp_server.local_ai_work(
        action="submit",
        root=str(tmp_path),
        task="Implement release receipt handling",
        acceptance_criteria=["Receipt verifies", "Failure remains terminal"],
        constraints=["No network writes"],
        mode="plan_then_execute",
        permissions={"allow_network": False},
        budget={"max_steps": 4},
        timeout_seconds=45,
    )

    assert backend.calls == [
        (
            "POST",
            "/api/work-orders",
            {
                "action": "submit",
                "root": str(tmp_path),
                "task": "Implement release receipt handling",
                "work_id": "",
                "task_id": "",
                "acceptance_criteria": ["Receipt verifies", "Failure remains terminal"],
                "constraints": ["No network writes"],
                "mode": "plan_then_execute",
                "permissions": {"allow_network": False},
                "budget": {"max_steps": 4},
                "timeout_seconds": 45,
                "answer": "",
                "response_profile": "compact",
                "return_fields": [],
                "max_output_tokens": 0,
                "keep_failed_workspace": False,
            },
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_work_status_forwards_work_identity(monkeypatch: Any) -> None:
    response = {"success": True, "work_id": "work-202", "status": "running", "completed_steps": 2}
    backend = _Backend(response)
    _enable_work(monkeypatch, backend)

    result = mcp_server.local_ai_work(action="status", work_id="work-202")

    assert backend.calls == [
        (
            "POST",
            "/api/work-orders",
            {
                "action": "status",
                "root": mcp_server._workspace,
                "task": "",
                "work_id": "work-202",
                "task_id": "",
                "acceptance_criteria": [],
                "constraints": [],
                "mode": "execute",
                "permissions": {},
                "budget": {},
                "timeout_seconds": 90.0,
                "answer": "",
                "response_profile": "compact",
                "return_fields": [],
                "max_output_tokens": 0,
                "keep_failed_workspace": False,
            },
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_work_wait_forwards_timeout_and_uses_long_transport_timeout(monkeypatch: Any) -> None:
    response = {"success": True, "work_id": "work-303", "status": "completed", "waited": True}
    backend = _Backend(response)
    _enable_work(monkeypatch, backend)

    result = mcp_server.local_ai_work(action="wait", work_id="work-303", timeout_seconds=23.5)

    assert backend.calls == [
        (
            "POST",
            "/api/work-orders",
            {
                "action": "wait",
                "root": mcp_server._workspace,
                "task": "",
                "work_id": "work-303",
                "task_id": "",
                "acceptance_criteria": [],
                "constraints": [],
                "mode": "execute",
                "permissions": {},
                "budget": {},
                "timeout_seconds": 23.5,
                "answer": "",
                "response_profile": "compact",
                "return_fields": [],
                "max_output_tokens": 0,
                "keep_failed_workspace": False,
            },
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_work_get_forwards_projection_options(monkeypatch: Any) -> None:
    response = {"success": True, "work_id": "work-404", "status": "completed", "receipt": "receipt-404"}
    backend = _Backend(response)
    _enable_work(monkeypatch, backend)

    result = mcp_server.local_ai_work(
        action="get",
        work_id="work-404",
        response_profile="minimal",
        return_fields=["receipt", "status"],
        max_output_tokens=321,
    )

    assert backend.calls == [
        (
            "POST",
            "/api/work-orders",
            {
                "action": "get",
                "root": mcp_server._workspace,
                "task": "",
                "work_id": "work-404",
                "task_id": "",
                "acceptance_criteria": [],
                "constraints": [],
                "mode": "execute",
                "permissions": {},
                "budget": {},
                "timeout_seconds": 90.0,
                "answer": "",
                "response_profile": "minimal",
                "return_fields": ["receipt", "status"],
                "max_output_tokens": 321,
                "keep_failed_workspace": False,
            },
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_work_cancel_returns_cancelled_state(monkeypatch: Any) -> None:
    response = {"success": True, "work_id": "work-505", "status": "cancelled", "cancelled": True}
    backend = _Backend(response)
    _enable_work(monkeypatch, backend)

    result = mcp_server.local_ai_work(action="cancel", work_id="work-505")

    assert backend.calls == [
        (
            "POST",
            "/api/work-orders",
            {
                "action": "cancel",
                "root": mcp_server._workspace,
                "task": "",
                "work_id": "work-505",
                "task_id": "",
                "acceptance_criteria": [],
                "constraints": [],
                "mode": "execute",
                "permissions": {},
                "budget": {},
                "timeout_seconds": 90.0,
                "answer": "",
                "response_profile": "compact",
                "return_fields": [],
                "max_output_tokens": 0,
                "keep_failed_workspace": False,
            },
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_work_continue_forwards_answer_and_preserves_updated_state(monkeypatch: Any) -> None:
    response = {
        "success": True,
        "work_id": "work-606",
        "status": "running",
        "continuation_id": "continuation-2",
    }
    backend = _Backend(response)
    _enable_work(monkeypatch, backend)

    result = mcp_server.local_ai_work(
        action="continue", work_id="work-606", answer="Use the verified receipt from step two."
    )

    assert backend.calls == [
        (
            "POST",
            "/api/work-orders",
            {
                "action": "continue",
                "root": mcp_server._workspace,
                "task": "",
                "work_id": "work-606",
                "task_id": "",
                "acceptance_criteria": [],
                "constraints": [],
                "mode": "execute",
                "permissions": {},
                "budget": {},
                "timeout_seconds": 90.0,
                "answer": "Use the verified receipt from step two.",
                "response_profile": "compact",
                "return_fields": [],
                "max_output_tokens": 0,
                "keep_failed_workspace": False,
            },
            {"timeout": 11.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True
