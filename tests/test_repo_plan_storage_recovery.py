"""Regression coverage for durable CAS, retries and partial-file recovery."""
import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from queue import Empty
from threading import Event

import pytest

from local_ai_hub.repo_plan import RepoPlanConflictError, RepoPlanStorage
from local_ai_hub.repo_plan.storage import IntentTarget, OperationIntent, compute_bytes_sha256
from test_repo_plan_storage import create_sample_plan_dict

PLAN = ".local-ai-hub/plans/main.plan.json"
SPEC = "docs/spec.md"


def test_fresh_instance_rejects_different_request_payload(tmp_path):
    RepoPlanStorage(tmp_path).save_plan_file(PLAN, create_sample_plan_dict(), idempotency_key="request")
    with pytest.raises(RepoPlanConflictError, match="reused with different payload"):
        RepoPlanStorage(tmp_path).save_plan_file(PLAN, create_sample_plan_dict(title="Other"), idempotency_key="request")


def test_retry_original_expected_revision_returns_durable_result(tmp_path):
    result = RepoPlanStorage(tmp_path).save_plan_file(PLAN, create_sample_plan_dict(), expected_revision="", idempotency_key="retry")
    assert RepoPlanStorage(tmp_path).save_plan_file(PLAN, create_sample_plan_dict(), expected_revision="", idempotency_key="retry") == result


def test_cross_instance_cas_serializes_validation_and_publish(tmp_path, monkeypatch):
    first, second = RepoPlanStorage(tmp_path), RepoPlanStorage(tmp_path)
    initial = first.save_plan_file(PLAN, create_sample_plan_dict())["file_revision"]
    entered, release, started = Event(), Event(), Event()
    atomic = first._atomic_write_bytes

    def paused(path, data):
        entered.set()
        assert release.wait(3)
        atomic(path, data)

    monkeypatch.setattr(first, "_atomic_write_bytes", paused)

    def competing():
        started.set()
        return second.save_plan_file(PLAN, create_sample_plan_dict(title="B"), expected_revision=initial)

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first.save_plan_file, PLAN, create_sample_plan_dict(title="A"), expected_revision=initial)
        assert entered.wait(3)
        b = pool.submit(competing)
        assert started.wait(3)
        release.set()
        assert a.result(timeout=5)["success"]
        with pytest.raises(RepoPlanConflictError, match="revision conflict"):
            b.result(timeout=5)
    assert first.read_plan_file(PLAN)[0]["title"] == "A"


def test_hash_only_partial_intent_never_claims_completed(tmp_path):
    storage = RepoPlanStorage(tmp_path)
    (tmp_path / "spec.md").write_bytes(b"new")
    intent = OperationIntent("partial", "save_spec_and_plan", "", "payload", "owner", 1, "pending", [
        IntentTarget("spec.md", "", compute_bytes_sha256(b"new")),
        IntentTarget("plan.json", "", compute_bytes_sha256(b"later")),
    ])
    storage._save_intent(intent)
    outcome = storage.recover_pending_intents()[0]
    assert outcome["status"] != "completed"
    assert not (tmp_path / "plan.json").exists()


def test_partial_real_save_recovers_forward_after_restart(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    atomic = storage._atomic_write_bytes

    def fail_plan(path, data):
        if path == tmp_path / PLAN:
            raise OSError("simulated interruption")
        atomic(path, data)

    monkeypatch.setattr(storage, "_atomic_write_bytes", fail_plan)
    with pytest.raises(OSError, match="interruption"):
        storage.save_spec_and_plan(SPEC, "# New spec", PLAN, create_sample_plan_dict(), idempotency_key="partial")
    fresh = RepoPlanStorage(tmp_path)
    outcomes = fresh.recover_pending_intents()
    assert outcomes[0]["status"] == "completed"
    assert outcomes[0]["resolution"] == "forward_recovered"
    assert fresh.read_plan_file(PLAN)[0]["title"] == "Sample Plan"


def test_multifile_lease_rechecked_before_first_publication(tmp_path):
    calls = iter([True, False])
    with pytest.raises(RepoPlanConflictError, match="lease"):
        RepoPlanStorage(tmp_path).save_spec_and_plan(SPEC, "# Spec", PLAN, create_sample_plan_dict(), lease_check_fn=lambda: next(calls))
    assert not (tmp_path / SPEC).exists()


def test_multifile_noop_does_not_rewrite_targets(tmp_path):
    storage = RepoPlanStorage(tmp_path)
    storage.save_spec_and_plan(SPEC, "# Spec", PLAN, create_sample_plan_dict())
    before = [(tmp_path / path).stat().st_mtime_ns for path in [SPEC, PLAN]]
    result = storage.save_spec_and_plan(SPEC, "# Spec", PLAN, create_sample_plan_dict())
    assert result["no_op"] is True
    assert result["changed_paths"] == []
    assert before == [(tmp_path / path).stat().st_mtime_ns for path in [SPEC, PLAN]]


def _competing_process(root, revision, started, result):
    started.set()
    try:
        RepoPlanStorage(root).save_plan_file(PLAN, create_sample_plan_dict(title="process B"), expected_revision=revision)
    except RepoPlanConflictError:
        result.put("conflict")
    else:
        result.put("saved")


def test_cross_process_cas_keeps_lock_until_acknowledgement(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    revision = storage.save_plan_file(PLAN, create_sample_plan_dict())["file_revision"]
    entered, release = Event(), Event()
    atomic = storage._atomic_write_bytes

    def paused(path, data):
        entered.set()
        assert release.wait(10)
        atomic(path, data)

    monkeypatch.setattr(storage, "_atomic_write_bytes", paused)
    context = multiprocessing.get_context("spawn")
    started, result = context.Event(), context.Queue()
    process = context.Process(target=_competing_process, args=(tmp_path, revision, started, result))
    with ThreadPoolExecutor(1) as pool:
        writer = pool.submit(storage.save_plan_file, PLAN, create_sample_plan_dict(title="process A"), expected_revision=revision)
        assert entered.wait(3)
        process.start()
        try:
            assert started.wait(5)
            with pytest.raises(Empty):
                result.get(timeout=0.2)
            release.set()
            assert writer.result(timeout=5)["success"]
            assert result.get(timeout=5) == "conflict"
        finally:
            release.set()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
    assert process.exitcode == 0


def test_recovery_preserves_later_edit(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    atomic = storage._atomic_write_bytes

    def fail_plan(path, data):
        if path == tmp_path / PLAN:
            raise OSError("interruption")
        atomic(path, data)

    monkeypatch.setattr(storage, "_atomic_write_bytes", fail_plan)
    with pytest.raises(OSError):
        storage.save_spec_and_plan(SPEC, "new", PLAN, create_sample_plan_dict())
    (tmp_path / SPEC).write_text("user later edit", encoding="utf-8")
    outcomes = RepoPlanStorage(tmp_path).recover_pending_intents()
    assert outcomes[0]["resolution"] == "diverged"
    assert outcomes[0]["status"] == "reconciled"
    assert not (tmp_path / PLAN).exists()
    assert (tmp_path / SPEC).read_text(encoding="utf-8") == "user later edit"


def test_completed_intent_repairs_interrupted_request_acknowledgement(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    save_request = storage._save_request

    def fail_ack(key, data):
        if data["status"] == "completed":
            raise OSError("request acknowledgement interrupted")
        save_request(key, data)

    monkeypatch.setattr(storage, "_save_request", fail_ack)
    with pytest.raises(OSError, match="acknowledgement"):
        storage.save_plan_file(PLAN, create_sample_plan_dict(), expected_revision="", idempotency_key="ack")
    result = RepoPlanStorage(tmp_path).save_plan_file(PLAN, create_sample_plan_dict(), expected_revision="", idempotency_key="ack")
    assert result["success"] is True


def test_git_head_change_fences_multifile_publish(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    context = storage._context
    original = storage._save_intent
    changed = False

    def mutate_context(intent):
        nonlocal changed
        original(intent)
        changed = True

    monkeypatch.setattr(storage, "_save_intent", mutate_context)
    monkeypatch.setattr(storage, "_context", lambda: dict(context(), git_head="changed") if changed else context())
    with pytest.raises(RepoPlanConflictError, match="context changed"):
        storage.save_spec_and_plan(SPEC, "new", PLAN, create_sample_plan_dict())
    assert not (tmp_path / SPEC).exists()
