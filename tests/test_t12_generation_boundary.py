from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import sys
from unittest.mock import MagicMock

_TEST_SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TEST_SOURCE_ROOT / "src"))

import local_ai_hub.operational_mode as operational_mode
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.trace_context import reset_observer, set_observer


class _Runtime:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def is_online(self) -> bool:
        return True

    def request(self, endpoint, payload=None, **_kwargs):
        assert endpoint == "/api/generate"
        self.payloads.append(payload)
        return {"response": "unexpected", "done": True}


class _InlineScheduler:
    def status(self) -> dict:
        return {}

    def submit(self, _model, _tenant, _source, work, **_kwargs):
        return work()


class _NoopSemanticCache:
    def get(self, _scope, _query):
        return None, 0.0

    def set(self, _scope, _query, _value):
        return None


class _Observer:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def model_request(self, payload) -> None:
        self.requests.append(payload)

    def output_delta(self, _text: str) -> None:
        return None


def test_generate_rechecks_admission_after_stale_active_mode_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = {
        "server": {"state_dir": str(tmp_path), "request_timeout_seconds": 5},
        "models": {"general": "local-model", "fast_code": "local-model", "heavy_code": "local-model"},
        "hardware": {"profile": "balanced"},
        "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
        "cache": {"generation": False, "embeddings": False},
        "resilience": {"model_fallback_enabled": False, "serve_stale_on_error": False},
        "token_saving": {"compact_responses": False},
    }
    runtime = _Runtime()
    service = LocalAIServices(
        config=config,
        runtime=runtime,
        scheduler=_InlineScheduler(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=RepositoryTools(config),
    )
    service.semantic_cache = _NoopSemanticCache()
    manager = AsyncJobManager(
        config=config,
        scheduler=object(),
        artifacts=MagicMock(),
        executor=lambda *_args: {"success": True},
    )

    real_admission = manager.inference_admission
    operational_mode.set_operational_mode(tmp_path, "active")
    stale_snapshot_read = threading.Event()
    continue_service = threading.Event()
    worker_ident: list[int] = []
    actions: list[str] = []
    trace_observer = _Observer()

    @contextmanager
    def admission(action: str, *, job_id=None):
        actions.append(action)
        with real_admission(action, job_id=job_id) as rejection:
            yield rejection

    service.inference_admission = admission
    original_load = operational_mode.load_operational_mode
    worker_load_count: dict[int, int] = {}

    def interleaved_load(state_dir=None):
        snapshot = original_load(state_dir)
        worker_id = threading.get_ident()
        worker_load_count[worker_id] = worker_load_count.get(worker_id, 0) + 1
        if (
            worker_ident
            and worker_id == worker_ident[0]
            and worker_load_count[worker_id] == 2
            and not stale_snapshot_read.is_set()
        ):
            stale_snapshot_read.set()
            assert continue_service.wait(2), "test did not release the service worker"
        return snapshot

    monkeypatch.setattr(operational_mode, "load_operational_mode", interleaved_load)

    def generate():
        worker_ident.append(threading.get_ident())
        token = set_observer(trace_observer)
        try:
            with service.inference_admission("delegate") as rejection:
                assert rejection is None
                return service._generate(
                    "local-model", "task prompt", "system", 64, 0.0, "default",
                    "delegate:general", 5, internal=True, use_cache=False,
                )
        finally:
            reset_observer(token)

    results: list[dict] = []
    thread = threading.Thread(target=lambda: results.append(generate()))
    try:
        thread.start()
        assert stale_snapshot_read.wait(2), "service did not reach the stale mode snapshot"
        with manager.operational_mode_change_guard():
            snapshot = operational_mode.set_operational_mode(tmp_path, "gaming")
            manager.on_operational_mode_changed(snapshot)
        expected = operational_mode.operational_mode_gate_error(snapshot, "delegate")
        continue_service.set()
        thread.join(2)
        assert not thread.is_alive(), "service worker did not complete"

        assert actions == ["delegate", "delegate"]
        assert expected is not None
        assert results and results[0] == expected
        assert runtime.payloads == []
        assert trace_observer.requests == []
    finally:
        continue_service.set()
        thread.join(2)
        manager.close()


def test_generate_pause_before_start_uses_central_retryable_gate_contract(
    tmp_path: Path,
) -> None:
    config = {
        "server": {"state_dir": str(tmp_path), "request_timeout_seconds": 5},
        "models": {"general": "local-model", "fast_code": "local-model", "heavy_code": "local-model"},
        "hardware": {"profile": "balanced"},
        "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
        "cache": {"generation": False, "embeddings": False},
        "resilience": {"model_fallback_enabled": False, "serve_stale_on_error": False},
        "token_saving": {"compact_responses": False},
    }
    runtime = _Runtime()
    service = LocalAIServices(
        config=config,
        runtime=runtime,
        scheduler=_InlineScheduler(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=RepositoryTools(config),
    )
    service.semantic_cache = _NoopSemanticCache()
    manager = AsyncJobManager(config=config, scheduler=object(), artifacts=MagicMock(), executor=lambda *_args: {"success": True})
    service.inference_admission = manager.inference_admission
    observer = _Observer()
    token = set_observer(observer)
    try:
        snapshot = operational_mode.set_operational_mode(tmp_path, "gaming")
        expected = operational_mode.operational_mode_gate_error(snapshot, "delegate")
        assert expected is not None
        result = service._generate(
            "local-model", "task prompt", "system", 64, 0.0, "default",
            "delegate:general", 5, internal=True, use_cache=False,
        )
        assert result == expected
        assert runtime.payloads == []
        assert observer.requests == []
    finally:
        reset_observer(token)
        manager.close()


def test_generate_operational_mode_load_failure_fails_closed_with_central_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = {
        "server": {"state_dir": str(tmp_path), "request_timeout_seconds": 5},
        "models": {"general": "local-model", "fast_code": "local-model", "heavy_code": "local-model"},
        "hardware": {"profile": "balanced"},
        "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
        "cache": {"generation": False, "embeddings": False},
        "resilience": {"model_fallback_enabled": False, "serve_stale_on_error": False},
        "token_saving": {"compact_responses": False},
    }
    runtime = _Runtime()
    service = LocalAIServices(
        config=config,
        runtime=runtime,
        scheduler=_InlineScheduler(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=RepositoryTools(config),
    )
    service.semantic_cache = _NoopSemanticCache()

    def unavailable(_state_dir=None):
        raise OSError("mode state unavailable")

    monkeypatch.setattr(operational_mode, "load_operational_mode", unavailable)
    expected = operational_mode.operational_mode_gate_error(None, "delegate")
    result = service._generate(
        "local-model", "task prompt", "system", 64, 0.0, "default",
        "delegate:general", 5, internal=True, use_cache=False,
    )

    assert expected is not None
    assert result == expected
    assert runtime.payloads == []
