"""Deferred bundle regressions; background operations are event-controlled fakes."""
import threading
from types import SimpleNamespace

from local_ai_hub.context_warmup import ContextWarmup
from local_ai_hub.services import LocalAIServices


def test_queue_is_bounded_and_never_duplicates_active_prediction():
    warmup = ContextWarmup()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked():
        entered.set()
        assert release.wait(3)
        calls.append("active")

    try:
        assert warmup.submit("active", blocked)
        assert entered.wait(1)
        assert not warmup.submit("active", lambda: calls.append("duplicate"))
        for index in range(4):
            assert warmup.submit(str(index), lambda: calls.append("queued"))
        assert not warmup.submit("overflow", lambda: calls.append("overflow"))
    finally:
        # Closing drops queued predictions; the active fake cooperatively finishes.
        warmup._stop.set()
        release.set()
        warmup.close()
    assert calls == ["active"]
    assert not warmup.submit("after-close", lambda: None)


def test_task_prediction_uses_existing_adaptive_request_identity(tmp_path, monkeypatch):
    task = SimpleNamespace(task_id="task-one", updated_at=10,
                           contract=SimpleNamespace(goal="Find bounded context", acceptance_criteria=("criterion",)),
                           context=SimpleNamespace(session_id="session-one"), status="active")
    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    service.task_store = SimpleNamespace(get=lambda _task_id: task)
    predictions = []
    service._context_warmup = SimpleNamespace(submit=lambda key, operation: predictions.append((key, operation)) or True)
    packs = []
    service.adaptive_context_pack = lambda request, **kwargs: packs.append((request, kwargs)) or {"success": True}
    monkeypatch.setattr("local_ai_hub.operational_mode.load_operational_mode", lambda _root: SimpleNamespace(mode="active"))
    assert service.schedule_task_context_warmup(task, root=str(tmp_path), tenant="tenant-one", changed_paths=["src/a.py"])
    predictions[0][1]()
    request, options = packs[0]
    assert request.tenant == "tenant-one"
    assert request.task_id == "task-one"
    assert request.session_id == "session-one"
    assert request.changed_paths == ("src/a.py",)
    assert request.token_budget == 4000
    assert options == {"mode": "adaptive"}
    task.updated_at = 11
    predictions[0][1]()
    assert len(packs) == 1, "changed task state must invalidate queued prediction"


def test_gaming_mode_never_queues_prediction(tmp_path, monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")}}
    task = SimpleNamespace(contract=SimpleNamespace(acceptance_criteria=("criterion",)))
    monkeypatch.setattr("local_ai_hub.operational_mode.load_operational_mode", lambda _root: SimpleNamespace(mode="gaming"))
    assert not service.schedule_task_context_warmup(task, root=str(tmp_path), tenant="tenant-one")
