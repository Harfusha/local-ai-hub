from __future__ import annotations

import pytest

from local_ai_hub.http_server import _agent_question_scope


def test_agent_question_scope_uses_authorized_repository_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert _agent_question_scope(payload={}, authorized_root=str(root)) == str(root.resolve())
    assert _agent_question_scope(
        payload={"root": str(root)}, authorized_root=str(root)
    ) == str(root.resolve())


def test_agent_question_scope_rejects_spoofed_root(tmp_path):
    authorized_root = tmp_path / "authorized"
    other_root = tmp_path / "other"
    authorized_root.mkdir()
    other_root.mkdir()
    with pytest.raises(ValueError, match="root does not match authenticated scope"):
        _agent_question_scope(payload={"root": str(other_root)}, authorized_root=str(authorized_root))


@pytest.mark.parametrize("field", ["tenant", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_agent_question_scope_rejects_retired_identity_fields_by_presence(tmp_path, field, value):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ValueError, match="retired"):
        _agent_question_scope(
            payload={"root": str(root), field: value}, authorized_root=str(root)
        )
