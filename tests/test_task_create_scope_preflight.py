import pytest

from local_ai_hub.operation_contracts import validate_operation_call


@pytest.mark.parametrize("scope", ["", False, None, 0])
def test_task_create_rejects_explicit_falsey_scope(scope):
    result = validate_operation_call("local_ai_coord", {
        "action": "task_create", "root": "C:/fixture", "title": "test", "scope": scope,
    })
    assert result is not None
    assert result[0] == 400


@pytest.mark.parametrize("extra", [{}, {"scope": "task"}, {"scope": "repository"}])
def test_task_create_accepts_omitted_or_canonical_scope(extra):
    assert validate_operation_call("local_ai_coord", {
        "action": "task_create", "root": "C:/fixture", "title": "test", **extra,
    }) is None
