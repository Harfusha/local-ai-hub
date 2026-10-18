"""Merged transaction call sites must honor command identity signatures."""

import ast
import inspect
import textwrap

import pytest

from local_ai_hub.commands import CommandBroker


@pytest.mark.parametrize("method_name", ["_run_private_transaction", "patch_and_verify"])
def test_transaction_identity_calls_bind_current_required_scope(method_name):
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(CommandBroker, method_name))))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr in {"_attempt_key", "_key"}
    ]
    assert calls, "transaction must preserve scoped command identity"
    for call in calls:
        signature = inspect.signature(getattr(CommandBroker, call.func.attr))
        arguments = [object()] * (len(call.args) + 1)
        keywords = {keyword.arg: object() for keyword in call.keywords if keyword.arg}
        signature.bind(*arguments, **keywords)
        assert "tenant" not in keywords, "transaction identity must not partition by tenant"
        assert call.args and ast.unparse(call.args[0]) in {"command", "incident_command"}
        assert "timeout" in keywords, "transaction identity must retain its timeout"
