from __future__ import annotations

import pytest

from local_ai_hub.agent_context import CompiledContext, ContextElement
from local_ai_hub.task_context import (
    build_context_request,
    compose_task_context,
    get_task_context_evidence_ids,
    is_task_context_complete,
)


def _make_compiled() -> CompiledContext:
    return CompiledContext(
        elements=[
            ContextElement(
                element_id="elem-1",
                source_kind="task_goal",
                content="Goal: test edge cases",
                estimated_tokens=5,
                reason="testing",
            )
        ],
        estimated_tokens=5,
        token_budget=200,
        phase="testing",
        repo_revision="rev-test",
    )


@pytest.mark.parametrize("payload", [None, "not-a-mapping"])
def test_build_context_request_rejects_non_mapping(payload) -> None:
    with pytest.raises(ValueError, match="payload must be an object"):
        build_context_request(payload)


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), "invalid-str", False])
def test_build_context_request_rejects_invalid_budget(budget) -> None:
    with pytest.raises(ValueError, match="token_budget must be an integer"):
        build_context_request({"token_budget": budget})


def test_build_context_request_retains_omitted_budget_default() -> None:
    assert build_context_request({}).token_budget == 4000


def test_build_context_request_rejects_retired_etag_input_alias() -> None:
    req = build_context_request({"task_id": "task-1", "etag": "old-hash"})
    assert req.since_hash == ""


@pytest.mark.parametrize("field", ["root", "task_id", "session_id", "clone_id", "worktree_id", "branch"])
def test_build_context_request_rejects_null_byte_identity(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        build_context_request({field: "identity\x00poison"})


def test_build_context_request_rejects_null_byte_changed_path() -> None:
    with pytest.raises(ValueError, match="without null bytes"):
        build_context_request({"session_id": "session-1", "changed_paths": ["path\x00one", "path/two"]})


def test_build_context_request_preserves_canonical_changed_paths() -> None:
    request = build_context_request({"session_id": "session-1", "changed_paths": ["path/one", "path/two"]})
    assert request.session_id == "session-1"
    assert list(request.changed_paths) == ["path/one", "path/two"]


@pytest.mark.parametrize("retired", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, "", False])
def test_build_context_request_rejects_retired_scope_field_by_presence(retired, value) -> None:
    with pytest.raises(ValueError, match="retired task context field"):
        build_context_request({"task_id": "task-1", retired: value})


def test_compose_task_context_none_repository_handling() -> None:
    compiled = _make_compiled()
    # None repository must not raise TypeError when repository_required is False
    ctx = compose_task_context(
        task_id="t-1",
        compiled=compiled,
        repository=None,  # type: ignore[arg-type]
        token_budget=4000,
        repository_required=False,
    )
    assert ctx["success"] is True
    assert ctx["complete"] is True
    assert ctx["repository"] == {}


def test_compose_task_context_nan_budget_safety() -> None:
    compiled = _make_compiled()
    # NaN / invalid token_budget must not raise ValueError
    ctx = compose_task_context(
        task_id="t-1",
        compiled=compiled,
        repository={"success": True, "repo_revision": "rev-test"},
        token_budget=float("nan"),  # type: ignore[arg-type]
    )
    assert ctx["success"] is True
    assert ctx["token_budget"] == 4000


def test_task_context_inspection_helpers() -> None:
    compiled = _make_compiled()
    ctx_complete = compose_task_context(
        task_id="t-1",
        compiled=compiled,
        repository={
            "success": True,
            "evidence_ids": ["E1", "E2"],
            "repo_revision": "rev-test",
        },
        token_budget=4000,
    )
    assert is_task_context_complete(ctx_complete) is True
    assert get_task_context_evidence_ids(ctx_complete) == ["E1", "E2"]

    ctx_incomplete = compose_task_context(
        task_id="t-2",
        compiled=compiled,
        repository={"success": False},
        token_budget=4000,
        repository_required=True,
    )
    assert is_task_context_complete(ctx_incomplete) is False
    assert get_task_context_evidence_ids(ctx_incomplete) == []

    # Non-mapping input safety
    assert is_task_context_complete(None) is False  # type: ignore[arg-type]
    assert get_task_context_evidence_ids(None) == []  # type: ignore[arg-type]
