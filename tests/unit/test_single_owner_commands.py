"""Command broker contracts after removal of tenant partitions."""

from __future__ import annotations

import inspect

import pytest

from local_ai_hub.commands import CommandBroker


def test_command_entry_points_reject_retired_tenant_argument() -> None:
    for method_name in (
        "run",
        "run_project_command",
        "patch_and_verify",
        "preflight",
        "repair_loop",
        "format",
        "lint_fix",
        "cancel",
    ):
        signature = inspect.signature(getattr(CommandBroker, method_name))
        assert "tenant" not in signature.parameters
        with pytest.raises(TypeError):
            signature.bind_partial(object(), tenant=None)


def test_cache_keys_have_no_tenant_partition() -> None:
    for method_name in ("_key", "_attempt_key"):
        signature = inspect.signature(getattr(CommandBroker, method_name))
        assert "tenant" not in signature.parameters
        with pytest.raises(TypeError):
            if method_name == "_key":
                signature.bind_partial(object(), "cmd", "root", {}, tenant="")
            else:
                signature.bind_partial(object(), "cmd", "root", tenant="")


def test_retired_execution_record_schema_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = CommandBroker.__new__(CommandBroker)
    monkeypatch.setattr(CommandBroker, "_get_server_command_execution_record", lambda self, _command_id: {
        "schema": "command_execution_record.v1",
        "tenant_identity": "retired",
    })

    assert broker.get_command_execution_record(
        "a" * 32,
        task_id="task-1",
        repository_root=".",
    ) is None
