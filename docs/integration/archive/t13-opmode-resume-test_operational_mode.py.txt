from __future__ import annotations

import json

import pytest

from local_ai_hub.operational_mode import (
    MODE_STATE_FILENAME,
    load_operational_mode,
    mode_allows,
    set_operational_mode,
)


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_restricted_modes_block_heavy_work_but_allow_deterministic_reads(tmp_path, mode: str) -> None:
    set_operational_mode(tmp_path, mode)

    state = load_operational_mode(tmp_path)

    assert state.mode == mode
    assert state.degraded is False
    assert mode_allows(state, "deterministic_read") is True
    assert mode_allows(state, "inference") is False
    assert mode_allows(state, "preprocess") is False


def test_active_mode_allows_heavy_work(tmp_path) -> None:
    state = set_operational_mode(tmp_path, "active")

    assert mode_allows(state, "deterministic_read") is True
    assert mode_allows(state, "inference") is True
    assert mode_allows(state, "preprocess") is True


def test_invalid_saved_mode_fails_closed(tmp_path) -> None:
    path = tmp_path / MODE_STATE_FILENAME
    path.write_text(json.dumps({"mode": "unknown"}), encoding="utf-8")

    state = load_operational_mode(tmp_path)

    assert state.mode == "maintenance"
    assert state.degraded is True
    assert mode_allows(state, "deterministic_read") is True
    assert mode_allows(state, "inference") is False
    assert mode_allows(state, "preprocess") is False


def test_malformed_saved_metadata_fails_closed(tmp_path) -> None:
    path = tmp_path / MODE_STATE_FILENAME
    path.write_text(json.dumps({"mode": "active", "updated_at": "broken"}), encoding="utf-8")

    state = load_operational_mode(tmp_path)

    assert state.mode == "maintenance"
    assert state.degraded is True
    assert mode_allows(state, "inference") is False


def test_degraded_active_state_fails_closed_for_heavy_work() -> None:
    from local_ai_hub.operational_mode import OperationalMode

    state = OperationalMode(mode="active", degraded=True)

    assert mode_allows(state, "deterministic_read") is True
    assert mode_allows(state, "inference") is False
    assert mode_allows(state, "preprocess") is False


def test_unknown_operation_class_is_rejected(tmp_path) -> None:
    state = load_operational_mode(tmp_path)

    with pytest.raises(ValueError, match="unknown operation class"):
        mode_allows(state, "unknown")


def test_invalid_mode_change_does_not_replace_saved_state(tmp_path) -> None:
    set_operational_mode(tmp_path, "gaming")

    with pytest.raises(ValueError, match="unsupported operational mode"):
        set_operational_mode(tmp_path, "unknown")

    assert load_operational_mode(tmp_path).mode == "gaming"


def test_services_blocks_inference_but_keeps_read_only_preprocess_actions(tmp_path, monkeypatch) -> None:
    from local_ai_hub.services import LocalAIServices

    set_operational_mode(tmp_path, "gaming")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    service.preprocessor = type("Preprocessor", (), {"status": lambda self, root=None: {"success": True, "root": root}})()

    inference = service._generate("model", "prompt", "system", 64, 0.0, "tenant", "mcp", 0)
    status = service.preprocess({"action": "status"})

    assert inference["success"] is False
    assert inference["blocked"] is True
    assert inference["operation"] == "inference"
    assert status["success"] is True


@pytest.mark.parametrize("action", ["start", "refresh", "resume"])
def test_services_blocks_preprocess_mutations_in_restricted_modes(tmp_path, action: str) -> None:
    from local_ai_hub.services import LocalAIServices

    set_operational_mode(tmp_path, "maintenance")
    calls: list[str] = []
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    service.preprocessor = type(
        "Preprocessor",
        (),
        {
            "register": lambda *args, **kwargs: calls.append("register"),
            "refresh": lambda *args, **kwargs: calls.append("refresh"),
            "resume": lambda *args, **kwargs: calls.append("resume"),
        },
    )()

    result = service.preprocess({"action": action})

    assert result["success"] is False
    assert result["blocked"] is True
    assert result["operation"] == "preprocess"
    assert calls == []


def test_background_semantic_generation_checks_mode_before_runtime(tmp_path) -> None:
    from local_ai_hub.preprocess import ProjectPreprocessor

    set_operational_mode(tmp_path, "gaming")
    calls: list[bool] = []
    preprocessor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    preprocessor.state_dir = tmp_path
    preprocessor._gpu_yield = lambda: calls.append(True) or False
    preprocessor.background_gpu = type("GPU", (), {"generate": lambda *args, **kwargs: calls.append(True)})()

    result = preprocessor._run_background_generate("model", "p", "s", {}, 64, "preprocess:test")

    assert result["success"] is False
    assert result["blocked"] is True
    assert result["operation"] == "preprocess"
    assert calls == []


def test_running_preprocess_project_step_stops_after_mode_changes(tmp_path) -> None:
    from local_ai_hub.preprocess import ProjectPreprocessor

    set_operational_mode(tmp_path, "maintenance")
    preprocessor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    preprocessor.state_dir = tmp_path
    preprocessor._project_step_lock = lambda _root: (_ for _ in ()).throw(AssertionError("step lock acquired"))

    assert preprocessor._run_project_step({"root": "repo"}) is None
