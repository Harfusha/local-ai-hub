from __future__ import annotations

import pytest

from local_ai_hub.http_server import _agent_question_scope


def test_agent_question_scope_uses_authenticated_identity(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    assert _agent_question_scope(
        payload={},
        authorized_root=str(root),
        authorized_tenant="tenant-a",
    ) == (str(root.resolve()), "tenant-a")


def test_agent_question_scope_rejects_spoofed_root(tmp_path):
    authorized_root = tmp_path / "authorized"
    other_root = tmp_path / "other"
    authorized_root.mkdir()
    other_root.mkdir()

    with pytest.raises(ValueError, match="root does not match authenticated scope"):
        _agent_question_scope(
            payload={"root": str(other_root)},
            authorized_root=str(authorized_root),
            authorized_tenant="tenant-a",
        )


def test_agent_question_scope_rejects_spoofed_tenant(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="tenant does not match authenticated scope"):
        _agent_question_scope(
            payload={"root": str(root), "tenant": "tenant-b"},
            authorized_root=str(root),
            authorized_tenant="tenant-a",
        )


@pytest.mark.parametrize(
    ("requested_tenant", "authorized_tenant"),
    [(" tenant-a ", "tenant-a"), (7, "7")],
)
def test_agent_question_scope_rejects_tenant_normalization_and_coercion(
    tmp_path, requested_tenant, authorized_tenant
):
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="tenant does not match authenticated scope"):
        _agent_question_scope(
            payload={"tenant": requested_tenant},
            authorized_root=str(root),
            authorized_tenant=authorized_tenant,
        )
