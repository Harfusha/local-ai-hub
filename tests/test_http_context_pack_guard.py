from __future__ import annotations

import pytest

from local_ai_hub.http_server import Handler, RequestBodyError


@pytest.mark.parametrize("guarded", [None, 0, 1, "true", []])
def test_context_pack_guarded_requires_boolean(guarded):
    with pytest.raises(RequestBodyError, match="guarded must be boolean"):
        Handler._validate_payload("/api/context/pack", {"guarded": guarded})


@pytest.mark.parametrize("task_id", [None, 1, "", "  "])
def test_guarded_context_requires_nonempty_task_id(task_id):
    with pytest.raises(RequestBodyError, match="guarded context requires a non-empty task_id"):
        Handler._validate_payload("/api/context/pack", {"guarded": True, "task_id": task_id})


def test_context_pack_accepts_unguarded_or_task_bound_payload():
    Handler._validate_payload("/api/context/pack", {})
    Handler._validate_payload("/api/context/pack", {"guarded": False})
    Handler._validate_payload("/api/context/pack", {"guarded": True, "task_id": "task-1"})
