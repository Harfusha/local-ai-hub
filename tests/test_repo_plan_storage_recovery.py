"""Regression coverage for durable CAS, retries and partial-file recovery."""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from queue import Empty
from threading import Event

import pytest

from local_ai_hub.repo_plan import RepoPlanConflictError, RepoPlanStorage
from local_ai_hub.repo_plan.schema_validation import RepoPlanError, serialize_plan_json
from local_ai_hub.repo_plan.storage import IntentTarget, OperationIntent, compute_bytes_sha256
from test_repo_plan_storage import create_sample_plan_dict

PLAN = ".local-ai-hub/plans/main.plan.json"
SPEC = "docs/spec.md"


def test_missing_new_intent_recovers_from_durable_reservation(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    original = storage._save_intent

    def crash_before_intent(_intent):
        raise RuntimeError("interrupted after reservation")

    monkeypatch.setattr(storage, "_save_intent", crash_before_intent)
    with pytest.raises(RuntimeError, match="interrupted after reservation"):
        storage.save_plan_file(PLAN, create_sample_plan_dict(), idempotency_key="reserved")
    assert not (tmp_path / PLAN).exists()
    monkeypatch.setattr(storage, "_save_intent", original)
    outcomes = storage.recover_pending_intents(only_key="reserved", resume_unapplied=True)
    assert len(outcomes) == 1 and outcomes[0]["status"] == "completed"
    assert storage.read_plan_file(PLAN)[0]["id"] == "plan_sample"


def test_maximum_target_bytes_fit_reservation_and_recover(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    plan = create_sample_plan_dict()
    plan_bytes = serialize_plan_json(plan).encode("utf-8")
    spec = "x" * (8 * 1024 * 1024 - len(plan_bytes))
    original = storage._save_intent
    monkeypatch.setattr(storage, "_save_intent", lambda _intent: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        storage.save_spec_and_plan(SPEC, spec, PLAN, plan, idempotency_key="max-size")
    assert storage._request_path("max-size").stat().st_size < 12 * 1024 * 1024
    monkeypatch.setattr(storage, "_save_intent", original)
    outcomes = storage.recover_pending_intents(only_key="max-size", resume_unapplied=True)
    assert len(outcomes) == 1 and outcomes[0]["status"] == "completed"
    assert (tmp_path / SPEC).stat().st_size == len(spec)
    assert storage.read_plan_file(PLAN)[0] == plan


def test_oversized_reservation_fails_before_target_changes(tmp_path):
    storage = RepoPlanStorage(tmp_path)
    with pytest.raises(RepoPlanError, match="Operation record exceeds"):
        storage.save_plan_file(PLAN, create_sample_plan_dict(), idempotency_key="oversized",
                               client_request_fingerprint="client", client_response_data={"value": "x" * (12 * 1024 * 1024)})
    assert not (tmp_path / PLAN).exists()
    assert not storage._request_path("oversized").exists()


def test_missing_intent_with_corrupt_snapshot_stays_blocked(tmp_path, monkeypatch):
    storage = RepoPlanStorage(tmp_path)
    original = storage._save_intent
    monkeypatch.setattr(storage, "_save_intent", lambda _intent: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        storage.save_plan_file(PLAN, create_sample_plan_dict(), idempotency_key="reserved")
    monkeypatch.setattr(storage, "_save_intent", original)
    request_path = storage._request_path("reserved")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["reserved_intent"]["owner"] = "other"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(RepoPlanConflictError, match="reservation identity mismatch"):
        storage.recover_pending_intents(only_key="reserved", resume_unapplied=True)
    assert not (tmp_path / PLAN).exists()


def test_missing_legacy_intent_without_snapshot_stays_blocked(tmp_path):
    storage = RepoPlanStorage(tmp_path)
    storage._ensure_intents_dir()
    storage._save_request("legacy", {"status": "pending", "intent_id": "intent_missing", "payload_sha256": "old"})
    with pytest.raises(RepoPlanConflictError, match="no durable reservation snapshot"):
        storage.recover_pending_intents(only_key="legacy", resume_unapplied=True)


def test_plan_write_never_overwrites_or_deletes_existing_temp_file(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import storage as storage_module

    target = tmp_path / "target"
    existing = tmp_path / ".tmp_target_12345678"
    existing.write_bytes(b"preserve")
    monkeypatch.setattr(storage_module.uuid, "uuid4", lambda: SimpleNamespace(hex="12345678"))
    with pytest.raises(FileExistsError):
        RepoPlanStorage(tmp_path)._atomic_write_bytes(target, b"new")
    assert existing.read_bytes() == b"preserve"
    assert not target.exists()


@pytest.mark.parametrize("record_kind", ["intent", "request"])
def test_journal_temp_collision_preserves_existing_file(tmp_path, monkeypatch, record_kind):
    from local_ai_hub.repo_plan import storage as storage_module

    storage = RepoPlanStorage(tmp_path)
    storage.intents_dir.mkdir(parents=True)
    token = "1234567890abcdef1234567890abcdef"
    name = ".tmp_intent_test_123456" if record_kind == "intent" else f".tmp_{token}"
    existing = storage.intents_dir / name
    existing.write_bytes(b"preserve")
    monkeypatch.setattr(storage_module.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    with pytest.raises(FileExistsError):
        if record_kind == "intent":
            storage._save_intent(OperationIntent("intent_test", "save_plan", "", "payload", "owner", 1, "pending", []))
        else:
            storage._save_request("request", {"status": "pending"})
    assert existing.read_bytes() == b"preserve"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction reproduction")
@pytest.mark.parametrize("phase", ["mkdir", "replace"])
def test_plan_write_resists_parent_junction_swap(tmp_path, monkeypatch, phase):
    root = tmp_path / "repo"
    parent = root / "docs"
    outside = tmp_path / "outside"
    parent.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "spec.md"
    sentinel.write_bytes(b"unchanged")
    junction = root / "staged-junction"
    env = {**os.environ, "LAH_RACE_LINK": str(junction), "LAH_RACE_TARGET": str(outside)}
    created = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "New-Item -ItemType Junction -Path $env:LAH_RACE_LINK -Target $env:LAH_RACE_TARGET | Out-Null"],
        env=env, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if created.returncode or not junction.exists():
        pytest.skip("Cannot create a Windows junction in this test environment")
    storage = RepoPlanStorage(root)
    original_mkdir = Path.mkdir
    swapped = False

    def swap_parent(path, *args, **kwargs):
        nonlocal swapped
        if path == parent and not swapped:
            swapped = True
            parent.rename(root / "old-docs")
            junction.rename(parent)
        return original_mkdir(path, *args, **kwargs)

    if phase == "mkdir":
        monkeypatch.setattr(Path, "mkdir", swap_parent)
    else:
        original_replace = os.replace

        def swap_at_replace(source, destination):
            nonlocal swapped
            if Path(destination) == parent / "spec.md":
                swapped = True
                try:
                    parent.rename(root / "old-docs")
                    junction.rename(parent)
                except OSError:
                    pass
            return original_replace(source, destination)

        monkeypatch.setattr(os, "replace", swap_at_replace)
    try:
        storage._atomic_write_bytes(parent / "spec.md", b"changed")
    except OSError:
        pass  # A safe implementation may deny the attempted swap or write.
    assert swapped, "The controlled swap must be exercised"
    assert sentinel.read_bytes() == b"unchanged"
    if phase == "replace":
        assert (parent / "spec.md").read_bytes() == b"changed"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction reproduction")
def test_journal_write_resists_parent_junction_swap(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    parent = root / ".local-ai-hub" / "local" / "intents"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "intent_test.intent.json"
    sentinel.write_bytes(b"unchanged")
    junction = root / "staged-junction"
    env = {**os.environ, "LAH_RACE_LINK": str(junction), "LAH_RACE_TARGET": str(outside)}
    created = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "New-Item -ItemType Junction -Path $env:LAH_RACE_LINK -Target $env:LAH_RACE_TARGET | Out-Null"],
        env=env, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if created.returncode or not junction.exists():
        pytest.skip("Cannot create a Windows junction in this test environment")
    original_mkdir = Path.mkdir
    swapped = False

    def swap_parent(path, *args, **kwargs):
        nonlocal swapped
        if path == parent and not swapped:
            swapped = True
            parent.rename(parent.with_name("old-intents"))
            junction.rename(parent)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", swap_parent)
    intent = OperationIntent("intent_test", "save_plan", "", "payload", "owner", 1, "pending", [])
    try:
        RepoPlanStorage(root)._save_intent(intent)
    except OSError:
        pass
    assert swapped
    assert sentinel.read_bytes() == b"unchanged"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory share-delete behavior")
def test_plan_write_blocks_root_rename_during_publication(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    storage = RepoPlanStorage(root)
    original_mkdir = Path.mkdir
    attempted = False

    def try_rename(path, *args, **kwargs):
        nonlocal attempted
        if path == root and not attempted:
            attempted = True
            with pytest.raises(OSError):
                root.rename(tmp_path / "moved-repo")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", try_rename)
    storage._atomic_write_bytes(root / "target", b"written")
    assert attempted
    assert (root / "target").read_bytes() == b"written"


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
