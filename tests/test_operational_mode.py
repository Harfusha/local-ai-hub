from __future__ import annotations

import multiprocessing
from types import SimpleNamespace

import pytest

from local_ai_hub import operational_mode


def _write_modes(state_dir: str, count: int, mode: str) -> None:
    for _ in range(count):
        operational_mode.set_operational_mode(state_dir, mode)


def _set_mode_with_events(state_dir: str, started, completed) -> None:
    started.set()
    operational_mode.set_operational_mode(state_dir, "gaming")
    completed.set()


def test_missing_state_defaults_to_active_and_updates_revision(tmp_path):
    initial = operational_mode.load_operational_mode(tmp_path)
    assert (initial.mode, initial.revision, initial.degraded) == ("active", 0, False)

    updated = operational_mode.set_operational_mode(tmp_path, "gaming")
    assert (updated.mode, updated.revision, updated.degraded) == ("gaming", 1, False)
    assert (tmp_path / "operational_mode.json").is_file()
    assert operational_mode.load_operational_mode(tmp_path) == updated


def test_invalid_mode_does_not_change_persisted_snapshot(tmp_path):
    original = operational_mode.set_operational_mode(tmp_path, "active")
    with pytest.raises(ValueError, match="mode"):
        operational_mode.set_operational_mode(tmp_path, "turbo")
    assert operational_mode.load_operational_mode(tmp_path) == original


def test_corrupt_state_fails_closed_to_degraded_maintenance(tmp_path):
    (tmp_path / "operational_mode.json").write_text("{broken", encoding="utf-8")
    snapshot = operational_mode.load_operational_mode(tmp_path)
    assert snapshot.mode == "maintenance"
    assert snapshot.degraded is True
    assert snapshot.error


def test_legacy_hyphenated_state_path_fails_closed(tmp_path):
    (tmp_path / "operational-mode.json").write_text(
        '{"mode":"gaming","revision":4}', encoding="utf-8"
    )

    snapshot = operational_mode.load_operational_mode(tmp_path)

    assert snapshot.mode == "maintenance"
    assert snapshot.revision == -1
    assert snapshot.degraded is True
    assert "legacy" in snapshot.error


def test_cross_process_updates_increment_revision_without_lost_writes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    workers = [
        ctx.Process(target=_write_modes, args=(str(tmp_path), 4, mode))
        for mode in ("gaming", "maintenance", "active")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    assert operational_mode.load_operational_mode(tmp_path).revision == 12


def test_file_lock_serializes_revision_update_across_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    completed = context.Event()
    _state_path, lock_path = operational_mode._paths(tmp_path)
    child = context.Process(
        target=_set_mode_with_events,
        args=(str(tmp_path), started, completed),
    )

    with operational_mode._file_lock(lock_path):
        child.start()
        assert started.wait(10)
        assert not completed.wait(0.25)

    child.join(10)
    assert child.exitcode == 0
    assert completed.is_set()
    assert operational_mode.load_operational_mode(tmp_path).revision == 1


def test_replace_retries_transient_permission_error(monkeypatch, tmp_path):
    real_replace = operational_mode.os.replace
    calls = 0

    def replace_with_transient_lock(source, target):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("antivirus held target briefly")
        real_replace(source, target)

    monkeypatch.setattr(operational_mode.os, "replace", replace_with_transient_lock)
    monkeypatch.setattr(operational_mode.time, "sleep", lambda _delay: None)
    snapshot = operational_mode.set_operational_mode(tmp_path, "maintenance")
    assert snapshot.mode == "maintenance"
    assert calls == 3


def test_replace_retries_windows_sharing_violation(monkeypatch, tmp_path):
    real_replace = operational_mode.os.replace
    calls = 0

    def replace_with_sharing_violation(source, target):
        nonlocal calls
        calls += 1
        if calls == 1:
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        real_replace(source, target)

    monkeypatch.setattr(operational_mode.os, "replace", replace_with_sharing_violation)
    monkeypatch.setattr(operational_mode.time, "sleep", lambda _delay: None)

    snapshot = operational_mode.set_operational_mode(tmp_path, "gaming")

    assert snapshot.mode == "gaming"
    assert calls == 2


def test_replace_sharing_violation_retries_are_bounded(monkeypatch, tmp_path):
    calls = 0

    def always_sharing_locked(_source, _target):
        nonlocal calls
        calls += 1
        error = OSError("sharing violation")
        error.winerror = 32
        raise error

    monkeypatch.setattr(operational_mode.os, "replace", always_sharing_locked)
    monkeypatch.setattr(operational_mode.time, "sleep", lambda _delay: None)

    with pytest.raises(operational_mode.OperationalModeWriteError):
        operational_mode.set_operational_mode(tmp_path, "maintenance")

    assert calls == operational_mode._REPLACE_ATTEMPTS


@pytest.mark.skipif(operational_mode.os.name != "nt", reason="Windows file sharing semantics required")
def test_windows_open_mode_file_blocks_replace_and_preserves_previous_state(monkeypatch, tmp_path):
    import ctypes
    from ctypes import wintypes

    target = tmp_path / "operational_mode.json"
    previous = operational_mode.set_operational_mode(tmp_path, "active")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(target), 0x80000000, 0x00000001 | 0x00000002, None,
        3, 0x00000080, None,
    )
    assert handle != wintypes.HANDLE(-1).value

    real_replace = operational_mode.os.replace
    calls = 0

    def count_replace(source, destination):
        nonlocal calls
        calls += 1
        return real_replace(source, destination)

    monkeypatch.setattr(operational_mode.os, "replace", count_replace)
    monkeypatch.setattr(operational_mode.time, "sleep", lambda _delay: None)
    try:
        with pytest.raises(operational_mode.OperationalModeWriteError):
            operational_mode.set_operational_mode(tmp_path, "maintenance")
        assert calls == operational_mode._REPLACE_ATTEMPTS
        assert operational_mode.load_operational_mode(tmp_path) == previous
        assert list(tmp_path.glob("operational_mode.json.*.tmp")) == []
    finally:
        assert close_handle(handle)

    recovered = operational_mode.set_operational_mode(tmp_path, "maintenance")
    assert (recovered.mode, recovered.revision) == ("maintenance", previous.revision + 1)


class _FakeRuntime:
    config = {"ollama": {"enabled": True}}

    def __init__(self, receipt=None):
        self.receipt = receipt or {
            "success": True, "unloaded": ["fast:latest"], "remaining": [], "verified": True,
        }
        self.calls = []

    def unload_configured_models(self, *, timeout_seconds, should_stop=None, deadline=None):
        self.calls.append((timeout_seconds, should_stop, deadline))
        return dict(self.receipt)


def test_gaming_ollama_release_delegates_once_to_owner_and_preserves_receipt():
    runtime = _FakeRuntime()
    stop = lambda: False
    result = operational_mode.unload_ollama_models_for_gaming(
        runtime, inference_active=False, timeout_seconds=1.5, should_stop=stop
    )

    assert result["success"] is True
    assert result["state"] == "complete"
    assert result["unloaded"] == ["fast:latest"]
    assert result["verified"] is True
    assert runtime.calls[0][0] == 1.5
    assert runtime.calls[0][1] is stop
    assert runtime.calls[0][2] is not None


def test_gaming_ollama_release_defers_during_inference_without_calling_owner():
    runtime = _FakeRuntime()
    result = operational_mode.unload_ollama_models_for_gaming(runtime, inference_active=True)
    assert result["state"] == "deferred"
    assert result["reason"] == "inference_active"
    assert runtime.calls == []


@pytest.mark.parametrize(
    ("receipt", "state"),
    [
        ({"success": False, "cancelled": True, "failed": {"operation": "unload cancelled"}}, "cancelled"),
        ({"success": False, "failed": {"operation": "unload deadline exceeded"}}, "timed_out"),
        ({"success": False, "failed": {"fast:latest": "offline"}, "remaining": ["fast:latest"], "verified": True}, "partial"),
        ({"success": True, "unloaded": [], "remaining": [], "verified": True}, "not_applicable"),
        ({"success": True, "unloaded": [], "remaining": ["fast:latest"], "verified": True}, "partial"),
        ({"success": True, "unloaded": ["fast:latest"], "remaining": [], "verified": False}, "requested"),
        ({"success": False, "unloaded": [], "requested": ["fast:latest"], "remaining": None, "verified": False, "unverified": True}, "unverified"),
        ({"success": True, "unloaded": ["fast:latest"], "remaining": "unknown", "verified": True}, "unverified"),
    ],
)
def test_gaming_ollama_release_maps_owner_receipts_without_inventing_success(receipt, state):
    result = operational_mode.unload_ollama_models_for_gaming(
        _FakeRuntime(receipt), inference_active=False
    )
    assert result["state"] == state
    assert result["success"] is (state == "not_applicable")
    assert result["physical_vram_reclaimed"] is False


def test_gaming_ollama_release_fails_closed_if_owner_callback_is_missing():
    result = operational_mode.unload_ollama_models_for_gaming(
        SimpleNamespace(config={"ollama": {"enabled": True}}), inference_active=False
    )
    assert result["success"] is False
    assert result["state"] == "failed"
    assert result["reason"] == "ollama_release_owner_unavailable"


def test_mcp_mode_gate_allows_deterministic_reads_only_outside_maintenance():
    snapshot = operational_mode.OperationalModeSnapshot("gaming", 7)
    assert operational_mode.operational_mode_gate_error(
        snapshot, "repo_search", requires_heavy_work=False
    ) is None
    maintenance = operational_mode.OperationalModeSnapshot("maintenance", 8)
    blocked_read = operational_mode.operational_mode_gate_error(
        maintenance, "local_ai_task_status", requires_heavy_work=False
    )
    assert blocked_read["error_code"] == "operational_mode_blocked"
    assert blocked_read["operational_mode"] == "maintenance"
    blocked = operational_mode.operational_mode_gate_error(
        snapshot, "local_ai_task", requires_heavy_work=True
    )
    assert blocked["error_code"] == "operational_mode_blocked"
    assert blocked["action"] == "local_ai_task"
    assert blocked["retryable"] is True
    assert blocked["terminal"] is False
    assert blocked["retry_after_seconds"] == 5


def test_in_process_accelerator_release_uses_component_cuda_cleanup_receipts():
    class ResidentModel:
        def __init__(self, backend, device):
            self.backend = backend
            self.device = device
            self.timeouts = []

        def status(self):
            return {
                "loaded": getattr(self, "loaded", True),
                "active_backend": self.backend,
                "active_device": self.device,
                "cache_cleanup": {"success": True, "state": "requested", "verified": False},
            }

        def release(self, timeout_seconds=3.0):
            self.timeouts.append(timeout_seconds)
            self.loaded = False
            return True

    embeddings = ResidentModel("sentence-transformers", "cuda:0")
    reranker = ResidentModel("torch", "cuda:0")
    result = operational_mode.unload_in_process_accelerators_for_gaming(
        embeddings,
        reranker,
        inference_active=False,
        timeout_seconds=60.0,
    )

    assert result["success"] is True
    assert result["state"] == "complete"
    assert result["verified"] is False
    assert result["cuda_cleanup"]["state"] == "requested"
    assert all(0 < timeout <= operational_mode._IN_PROCESS_RELEASE_DEADLINE_SECONDS for timeout in embeddings.timeouts + reranker.timeouts)


def test_in_process_accelerator_release_defers_while_inference_active():
    class ResidentModel:
        calls = 0

        def status(self):
            return {"loaded": True, "active_backend": "torch", "active_device": "cuda:0"}

        def release(self, timeout_seconds=3.0):
            self.calls += 1
            return True

    embeddings = ResidentModel()
    result = operational_mode.unload_in_process_accelerators_for_gaming(
        embeddings, inference_active=True
    )

    assert result["success"] is False
    assert result["state"] == "deferred"
    assert embeddings.calls == 0


def test_in_process_accelerator_release_bounds_stalled_component(tmp_path):
    import threading

    entered = threading.Event()
    resume = threading.Event()

    class StalledModel:
        def status(self):
            return {"loaded": True, "active_backend": "torch", "active_device": "cuda:0"}

        def release(self, timeout_seconds=3.0):
            entered.set()
            resume.wait(timeout=1.0)
            return True

    try:
        result = operational_mode.unload_in_process_accelerators_for_gaming(
            StalledModel(), inference_active=False, timeout_seconds=0.02
        )
    finally:
        resume.set()

    assert entered.is_set()
    assert result["success"] is False
    assert result["models"]["embeddings"]["state"] == "timed_out"


def test_in_process_release_adapts_existing_boolean_release_and_reports_observed_state():
    class LegacyReleaseModel:
        def __init__(self, backend, device):
            self.loaded = True
            self.backend = backend
            self.device = device
            self.timeouts = []

        def status(self):
            return {
                "loaded": self.loaded,
                "active_backend": self.backend,
                "active_device": self.device,
                "cache_cleanup": {"success": True, "state": "requested", "verified": False},
            }

        def release(self, timeout_seconds=3.0):
            self.timeouts.append(timeout_seconds)
            self.loaded = False
            return True

    embeddings = LegacyReleaseModel("sentence-transformers", "cuda:0")
    cleanup_timeouts = []
    result = operational_mode.unload_in_process_accelerators_for_gaming(
        embeddings,
        inference_active=False,
        timeout_seconds=1.0,
    )

    receipt = result["models"]["embeddings"]
    assert result["success"] is True
    assert receipt["status"] == "released"
    assert receipt["released"] is True
    assert receipt["backend"] == "sentence-transformers"
    assert receipt["device"] == "cuda:0"
    assert receipt["vram_release"] is None
    assert embeddings.status()["loaded"] is False
    assert 0 < embeddings.timeouts[0] <= 1.0
    assert result["cuda_cleanup"]["state"] == "requested"
    assert cleanup_timeouts == []


def test_in_process_release_classifies_cpu_and_external_backends_without_claiming_release():
    class ResidentModel:
        def __init__(self, backend, device):
            self.backend = backend
            self.device = device
            self.calls = 0

        def status(self):
            return {
                "loaded": True,
                "active_backend": self.backend,
                "active_device": self.device,
                "cache_cleanup": {"success": True, "state": "requested", "verified": False},
            }

        def release(self, **_kwargs):
            self.calls += 1
            return False

    cpu = ResidentModel("sentence-transformers", "cpu")
    ollama = ResidentModel("ollama", "ollama")
    result = operational_mode.unload_in_process_accelerators_for_gaming(
        cpu, ollama, inference_active=False
    )

    assert result["success"] is True
    assert result["models"]["embeddings"]["status"] == "cpu_noop"
    assert result["models"]["reranker"]["status"] == "external_backend"
    assert result["models"]["embeddings"]["released"] is False
    assert result["models"]["reranker"]["released"] is False
    assert result["cuda_cleanup"]["status"] == "not_applicable"
    assert cpu.calls == ollama.calls == 0


def test_in_process_release_reports_false_return_with_loaded_model_as_timed_out():
    class RefusedModel:
        def status(self):
            return {
                "loaded": True,
                "active_backend": "torch",
                "active_device": "cuda:0",
            }

        def release(self, timeout_seconds=3.0):
            return False

    result = operational_mode.unload_in_process_accelerators_for_gaming(
        RefusedModel(), inference_active=False, timeout_seconds=0.2
    )

    assert result["success"] is False
    assert result["models"]["embeddings"]["status"] == "timed_out"
    assert result["models"]["embeddings"]["released"] is False
    assert result["cuda_cleanup"]["state"] == "not_reported"


def test_in_process_cuda_cache_cleanup_uses_mocked_torch_without_hardware(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []
    mock_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            empty_cache=lambda: calls.append("empty_cache"),
        )
    )
    monkeypatch.setitem(sys.modules, "torch", mock_torch)

    result = operational_mode._empty_torch_cuda_cache(0.25)

    assert result == {"success": True, "state": "requested", "verified": False}
    assert calls == ["empty_cache"]


def test_in_process_cuda_cache_cleanup_respects_deadline(monkeypatch):
    import sys
    import threading
    from types import SimpleNamespace

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_empty_cache():
        entered.set()
        release.wait(timeout=1.0)
        finished.set()

    mock_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            empty_cache=blocking_empty_cache,
        )
    )
    monkeypatch.setitem(sys.modules, "torch", mock_torch)
    result = {}
    caller = threading.Thread(
        target=lambda: result.update(
            value=operational_mode._empty_torch_cuda_cache(0.05)
        )
    )
    caller.start()

    try:
        assert entered.wait(timeout=1.0)
        caller.join(timeout=0.5)
        assert not caller.is_alive()
        overlapping = operational_mode._empty_torch_cuda_cache(0.01)
    finally:
        release.set()

    assert finished.wait(timeout=1.0)
    assert result["value"]["success"] is False
    assert result["value"]["state"] == "deadline_exceeded"
    assert overlapping["state"] == "busy"
    assert operational_mode._empty_torch_cuda_cache(0.1)["state"] == "requested"


def test_embedding_and_reranker_release_only_loaded_accelerator_models(tmp_path):
    from local_ai_hub.embeddings import EmbeddingModel
    from local_ai_hub.reranker import Reranker

    config = {"server": {"state_dir": str(tmp_path)}, "models": {}}
    embeddings = EmbeddingModel(config)
    embeddings._model = object()
    embeddings.active_backend = "sentence-transformers"
    embeddings.active_device = "cuda:0"
    embeddings._active_cache_identity = "st:cuda:0:model"
    released_embedding = embeddings.release_accelerator(timeout_seconds=0.2)

    reranker = Reranker(config)
    reranker._model = object()
    reranker.active_backend = "torch"
    reranker.active_device = "cuda:0"
    released_reranker = reranker.release_accelerator(timeout_seconds=0.2)

    assert released_embedding["success"] is True
    assert released_embedding["state"] == "unloaded"
    assert embeddings._model is None
    assert embeddings._active_cache_identity is None
    assert released_reranker["success"] is True
    assert released_reranker["state"] == "unloaded"
    assert reranker._model is None


def test_embedding_release_defers_while_request_is_loading_model(tmp_path, monkeypatch):
    import threading

    from local_ai_hub.embeddings import EmbeddingModel

    model = EmbeddingModel({
        "server": {"state_dir": str(tmp_path)},
        "models": {"embedding_backend": "sentence-transformers"},
    })
    model._model = object()
    model.active_backend = "sentence-transformers"
    model.active_device = "cuda:0"
    model._loaded_model_name = "test-model"
    entered = threading.Event()
    resume = threading.Event()

    def load_model():
        entered.set()
        resume.wait(timeout=1.0)
        model._model = object()
        model.active_backend = "sentence-transformers"
        model.active_device = "cuda:0"
        model._loaded_model_name = "test-model"
        return True

    monkeypatch.setattr(model, "_ensure_model", load_model)
    monkeypatch.setattr(
        model,
        "_encode_st_batch",
        lambda *_args, **_kwargs: ([[0.25, 0.75]], "sentence-transformers"),
    )
    result = {}

    def encode():
        result["value"] = model.encode(["race test"])

    worker = threading.Thread(target=encode)
    worker.start()

    try:
        assert entered.wait(timeout=1.0)
        released = model.release_accelerator(timeout_seconds=0.01)
    finally:
        resume.set()
        worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert released["success"] is False
    assert released["state"] == "busy"
    assert result["value"]["success"] is True


def test_reranker_release_defers_while_request_is_loading_model(tmp_path, monkeypatch):
    import threading

    from local_ai_hub.reranker import Reranker

    reranker = Reranker({"server": {"state_dir": str(tmp_path)}, "models": {}})
    reranker._model = object()
    entered = threading.Event()
    resume = threading.Event()

    def load_model():
        entered.set()
        resume.wait(timeout=1.0)
        reranker._model = object()
        reranker.active_backend = "torch"
        reranker.active_device = "cuda:0"
        return True

    monkeypatch.setattr(reranker, "_ensure_model", load_model)
    monkeypatch.setattr(reranker, "_predict", lambda *_args, **_kwargs: [0.5])
    worker = threading.Thread(target=lambda: reranker.rerank("query", ["document"]))
    worker.start()

    try:
        assert entered.wait(timeout=1.0)
        released = reranker.release_accelerator(timeout_seconds=0.01)
    finally:
        resume.set()
        worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert released["success"] is False
    assert released["state"] == "busy"


def test_in_process_release_preserves_component_not_applicable_receipt():
    class CpuResident:
        def status(self):
            return {"loaded": True, "active_backend": "torch", "active_device": ""}

        def release_accelerator(self, *, timeout_seconds):
            return {"success": True, "state": "not_applicable", "verified": False}

    result = operational_mode.unload_in_process_accelerators_for_gaming(
        CpuResident(), inference_active=False
    )
    receipt = result["models"]["embeddings"]
    assert result["success"] is True
    assert receipt["state"] == "not_applicable"
    assert receipt["released"] is False
