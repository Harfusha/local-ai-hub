from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import sys
from unittest.mock import MagicMock

_TEST_SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TEST_SOURCE_ROOT / "src"))

import local_ai_hub.operational_mode as operational_mode
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


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

    real_load = operational_mode.load_operational_mode
    operational_mode.set_operational_mode(tmp_path, "active")
    stale_snapshot_read = threading.Event()
    continue_service = threading.Event()
    worker_ident: list[int] = []
    actions: list[str] = []

    @contextmanager
    def admission(action: str, *, job_id=None):
        del job_id
        actions.append(action)
        snapshot = real_load(tmp_path)
        rejection = None
        if snapshot.degraded or snapshot.mode != "active":
            rejection = {
                "success": False,
                "error": "inference start blocked by operational mode",
                "error_code": "operational_mode_paused",
                "mode": snapshot.mode,
                "terminal": True,
                "retryable": False,
            }
        yield rejection

    service.inference_admission = admission
    original_load = operational_mode.load_operational_mode

    def interleaved_load(state_dir=None):
        snapshot = original_load(state_dir)
        if worker_ident and threading.get_ident() == worker_ident[0] and not stale_snapshot_read.is_set():
            stale_snapshot_read.set()
            assert continue_service.wait(2), "test did not release the service worker"
        return snapshot

    monkeypatch.setattr(operational_mode, "load_operational_mode", interleaved_load)

    def generate():
        worker_ident.append(threading.get_ident())
        with service.inference_admission("delegate") as rejection:
            assert rejection is None
            return service._generate(
                "local-model", "task prompt", "system", 64, 0.0, "default",
                "delegate:general", 5, internal=True, use_cache=False,
            )

    results: list[dict] = []
    thread = threading.Thread(target=lambda: results.append(generate()))
    thread.start()
    assert stale_snapshot_read.wait(2), "service did not reach the stale mode snapshot"
    operational_mode.set_operational_mode(tmp_path, "gaming")
    continue_service.set()
    thread.join(2)
    assert not thread.is_alive(), "service worker did not complete"

    assert actions == ["delegate", "delegate"]
    assert results and results[0].get("success") is False
    assert "inference start blocked by operational mode" in results[0].get("error", "")
    assert runtime.payloads == []
