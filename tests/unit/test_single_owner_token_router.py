from __future__ import annotations

import inspect

import pytest

from local_ai_hub.token_router import LosslessTokenRouter


def _router(state_dir) -> LosslessTokenRouter:
    return LosslessTokenRouter(
        {
            "server": {"state_dir": str(state_dir)},
            "lossless_router": {"enabled": True},
            "models": {"fast_code": "selector-a"},
        },
        services=object(),
    )


def test_public_route_signatures_retire_tenant_arguments() -> None:
    text = inspect.signature(LosslessTokenRouter.route_text)
    file = inspect.signature(LosslessTokenRouter.route_file)
    assert "tenant" not in text.parameters
    assert "tenant" not in file.parameters
    assert text.parameters["path"].kind is inspect.Parameter.KEYWORD_ONLY
    assert file.parameters["force_local"].kind is inspect.Parameter.KEYWORD_ONLY


def test_retired_tenant_calls_reject_without_positional_shifting(tmp_path) -> None:
    router = _router(tmp_path / "state")
    with pytest.raises(TypeError):
        router.route_text("body", "query", None)
    with pytest.raises(TypeError):
        router.route_text("body", "query", tenant="")
    with pytest.raises(TypeError):
        router.route_file(str(tmp_path), "a.txt", "query", None)
    with pytest.raises(TypeError):
        router.route_file(str(tmp_path), "a.txt", "query", tenant=False)


def test_file_cache_is_namespaced_by_resolved_repository_and_confined(tmp_path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "note.txt").write_text("stable evidence line", encoding="utf-8")
    (second_root / "note.txt").write_text("stable evidence line", encoding="utf-8")
    router = _router(tmp_path / "state")

    first = router.route_file(str(first_root), "note.txt", "evidence")
    same_root = router.route_file(str(first_root), "note.txt", "evidence")
    other_root = router.route_file(str(second_root), "note.txt", "evidence")

    assert first["success"] and not first["cache_hit"]
    assert same_root["cache_hit"] is True
    assert other_root["success"] and other_root["cache_hit"] is False
    escaped = router.route_file(str(first_root), "../second/note.txt", "evidence")
    assert escaped == {"success": False, "error": "path escapes root"}
