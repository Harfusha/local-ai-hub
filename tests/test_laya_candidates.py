import json
import hashlib
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

import local_ai_hub.laya_candidates as candidates_module
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.laya_candidates import LayaCandidateStore


@pytest.fixture
def candidate_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state_store = AgentStateStore(state / "agent_state.sqlite", enabled=True)
    task = SimpleNamespace(
        task_id="task-1",
        context=SimpleNamespace(session_id="session-1"),
    )
    task_store = SimpleNamespace(list_tasks=lambda **_kwargs: [task], state_store=state_store)
    monkeypatch.setattr(candidates_module, "_task_matches_scope", lambda *_args: True)
    return repo, state, task_store, LayaCandidateStore(state)


def _capture(*, consent=True, state="A short approved state", **changes):
    operation = {
        "action": "capture",
        "consent": consent,
        "task_id": "task-1",
        "session_id": "session-1",
        "candidate": {
            "decision_schema_version": "laya-hub-v1",
            "category": "model_route",
            "state": state,
            "options": ["fast", "smart", "background"],
            "language": "en",
            "preprocessing": {"name": "none", "version": "1"},
            "evidence_ids": ["ev-1"],
        },
    }
    operation.update(changes)
    return operation


def _capture_batch(*, examples=None):
    example = {"consent": True, "candidate": _capture()["candidate"]}
    return {
        "action": "capture_batch",
        "task_id": "task-1",
        "session_id": "session-1",
        "examples": [example, dict(example)] if examples is None else examples,
    }


def _capture_and_verify(store, repo, task_store, task_id, session_id, state, suffix):
    operation = _capture(state=state)
    operation["task_id"] = task_id
    operation["session_id"] = session_id
    captured = store.handle(operation, root=str(repo), task_store=task_store)
    cid = captured["candidate_id"]
    store.handle({
        "action": "label", "candidate_id": cid,
        "annotations": [
            {"annotator_ref": f"annotator-a-{suffix}", "target": "fast"},
            {"annotator_ref": f"annotator-b-{suffix}", "target": "fast"},
        ],
        "adjudication": {"reviewer_ref": f"adjudicator-{suffix}", "target": "fast"},
    }, root=str(repo), task_store=task_store)
    store.handle({
        "action": "verify", "candidate_id": cid, "consent": True,
        "reviewer_ref": f"verifier-{suffix}",
    }, root=str(repo), task_store=task_store)
    return cid


def test_capture_requires_per_example_consent_and_reuses_agent_state_database(candidate_env):
    repo, state, task_store, store = candidate_env

    with pytest.raises(ValueError, match="consent=true"):
        store.handle(_capture(consent=False), root=str(repo), task_store=task_store)

    result = store.handle(_capture(), root=str(repo), task_store=task_store)
    assert result["success"] is True
    assert result["status"] == "pending"
    assert store.path == task_store.state_store.db_path
    assert store.path.exists()
    assert not (state / "laya_candidates.sqlite3").exists()
    assert not list(repo.glob("*.sqlite3"))


def test_capture_deduplicates_exact_inputs_and_list_omits_candidate_text(candidate_env):
    repo, _state, task_store, store = candidate_env
    first = store.handle(_capture(), root=str(repo), task_store=task_store)
    second = store.handle(_capture(), root=str(repo), task_store=task_store)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["candidate_id"] == first["candidate_id"]
    listed = store.handle({"action": "list"}, root=str(repo), task_store=task_store)
    assert listed["count"] == 1
    assert "candidate" not in listed["candidates"][0]
    assert "A short approved state" not in json.dumps(listed)


def test_capture_preserves_laya_choice_option_order_in_persisted_question(candidate_env):
    repo, _state, task_store, store = candidate_env
    operation = _capture()
    operation["candidate"]["options"] = ["background", "fast", "smart"]

    captured = store.handle(operation, root=str(repo), task_store=task_store)

    connection = sqlite3.connect(store.path)
    try:
        row = connection.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()
    finally:
        connection.close()
    candidate = json.loads(row[0])
    assert list(candidate["questions"]["model_route"]["criteria"]) == [
        "background", "fast", "smart"
    ]


def test_capture_batch_deduplicates_in_one_scoped_request(candidate_env):
    repo, _state, task_store, store = candidate_env

    result = store.handle(_capture_batch(), root=str(repo), task_store=task_store)

    assert result["success"] is True
    assert result["count"] == 2
    assert result["captured_count"] == 1
    assert result["duplicate_count"] == 1
    assert result["results"][0]["candidate_id"] == result["results"][1]["candidate_id"]
    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 1


def test_capture_batch_rejects_missing_example_consent_without_partial_writes(candidate_env):
    repo, _state, task_store, store = candidate_env
    examples = _capture_batch()["examples"]
    examples[1]["consent"] = False

    with pytest.raises(ValueError, match="per-example consent=true"):
        store.handle(_capture_batch(examples=examples), root=str(repo), task_store=task_store)

    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0


def test_label_verify_and_split_snapshot_require_independent_review_and_consent(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    cid = captured["candidate_id"]
    labels = {
        "action": "label",
        "candidate_id": cid,
        "annotations": [
            {"annotator_ref": "reviewer-a", "target": "fast"},
            {"annotator_ref": "reviewer-b", "target": "fast"},
        ],
        "adjudication": {"reviewer_ref": "adjudicator-c", "target": "fast"},
    }
    reviewed = store.handle(labels, root=str(repo), task_store=task_store)
    assert reviewed["status"] == "reviewed"
    with pytest.raises(ValueError, match="independent"):
        store.handle({"action": "verify", "candidate_id": cid, "consent": True, "reviewer_ref": "reviewer-a"}, root=str(repo), task_store=task_store)
    verified = store.handle({"action": "verify", "candidate_id": cid, "consent": True, "reviewer_ref": "reviewer-d"}, root=str(repo), task_store=task_store)
    assert verified["status"] == "verified"

    with pytest.raises(ValueError, match="consent=true"):
        store.handle({"action": "prepare_splits", "consent": False}, root=str(repo), task_store=task_store)
    snapshot = store.handle({"action": "prepare_splits", "consent": True}, root=str(repo), task_store=task_store)
    assert snapshot["sufficiency_status"] == "INSUFFICIENT DATA"
    repeated = store.handle({"action": "prepare_splits", "consent": True}, root=str(repo), task_store=task_store)
    assert repeated["snapshot_id"] == snapshot["snapshot_id"]
    assert repeated["reused"] is True
    with pytest.raises(ValueError, match="consent=true"):
        store.handle({
            "action": "export", "consent": False, "output_path": "dataset.jsonl",
            "snapshot_id": snapshot["snapshot_id"],
        }, root=str(repo), task_store=task_store)
    assert store.handle({"action": "list", "status": "verified"}, root=str(repo), task_store=task_store)["count"] == 1


def test_split_preparation_without_verified_candidates_reports_insufficient_data(candidate_env):
    repo, _state, task_store, store = candidate_env
    store.handle(_capture(), root=str(repo), task_store=task_store)
    result = store.handle({"action": "prepare_splits", "consent": True}, root=str(repo), task_store=task_store)

    assert result["snapshot_id"] is None
    assert result["candidate_count"] == 0
    assert result["status_counts"] == {"pending": 1}
    assert result["sufficiency_status"] == "INSUFFICIENT DATA"


def test_group_and_near_duplicate_safe_splits_keep_test_labels_out_of_train_export(candidate_env):
    repo, _state, _single_task_store, store = candidate_env
    task_specs = [(f"task-{i:03}", f"session-{i:03}") for i in range(100)]
    task_specs.append(("task-100", "session-000"))
    tasks = [SimpleNamespace(task_id=task, context=SimpleNamespace(session_id=session)) for task, session in task_specs]
    task_store = SimpleNamespace(
        list_tasks=lambda **_kwargs: tasks,
        state_store=_single_task_store.state_store,
    )
    candidates = []
    for i, (task_id, session_id) in enumerate(task_specs):
        if i == 0:
            state = "Compiler reports a missing symbol in the source module near line twelve."
        elif i == 1:
            state = "The compiler reports a missing symbol in this source module near line twelve."
        else:
            digest = hashlib.sha256(f"case-{i}".encode()).hexdigest()
            state = f"scenario {i} unique issue reference {digest}"
        candidates.append(_capture_and_verify(store, repo, task_store, task_id, session_id, state, i))

    # Same task/session group must remain whole even when examples differ.
    _capture_and_verify(
        store, repo, task_store, task_specs[2][0], task_specs[2][1],
        "A second distinct state for task two, with separate evidence and option context.", "same-group",
    )
    snapshot = store.handle({"action": "prepare_splits", "consent": True}, root=str(repo), task_store=task_store)
    assert snapshot["candidate_count"] == 102
    assert snapshot["sufficiency_status"] == "UNASSESSED"
    assert snapshot["near_duplicate_group_merges"] >= 1
    assert sum(snapshot["split_counts"].values()) == 102

    with closing(sqlite3.connect(store.path)) as con:
        assignments = con.execute(
            "SELECT c.task_id,c.session_id,a.split_name,c.candidate_json,c.candidate_id FROM laya_dataset_assignments a "
            "JOIN laya_candidates c ON c.candidate_id=a.candidate_id WHERE a.snapshot_id=?",
            (snapshot["snapshot_id"],),
        ).fetchall()
    by_task = {}
    by_session = {}
    for task_id, session_id, split_name, _candidate_json, _candidate_id in assignments:
        by_task.setdefault(task_id, set()).add(split_name)
        by_session.setdefault(session_id, set()).add(split_name)
    assert all(len(splits) == 1 for splits in by_task.values())
    assert by_session["session-000"] == by_task["task-000"]
    assert by_task["task-000"] == by_task["task-001"]  # near duplicates share a split
    assert all(value > 0 for value in snapshot["split_counts"].values())

    zip_payload = store.export_train_payload(
        {"consent": True, "snapshot_id": snapshot["snapshot_id"]},
        root=str(repo), task_store=task_store,
    )
    zip_rows = [json.loads(line) for line in zip_payload.decode("utf-8").splitlines()]
    assert len(zip_rows) == snapshot["split_counts"]["train"]
    assert all(set(row) == {"state", "questions", "expected"} for row in zip_rows)

    exported = store.handle({
        "action": "export", "consent": True, "output_path": "train.jsonl",
        "snapshot_id": snapshot["snapshot_id"],
    }, root=str(repo), task_store=task_store)
    assert exported["count"] == snapshot["split_counts"]["train"]
    export_rows = [json.loads(line) for line in (repo / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    train_states = {
        json.loads(candidate_json)["state"]
        for _task_id, _session_id, split_name, candidate_json, _candidate_id in assignments if split_name == "train"
    }
    assert {row["state"] for row in export_rows} == train_states
    test_candidate_id = next(candidate_id for _task, _session, split_name, _json, candidate_id in assignments if split_name == "test")
    store.handle(
        {"action": "delete", "candidate_id": test_candidate_id, "consent": True},
        root=str(repo), task_store=task_store,
    )
    with pytest.raises(ValueError, match="invalidated"):
        store.export_train_payload(
            {"consent": True, "snapshot_id": snapshot["snapshot_id"]},
            root=str(repo), task_store=task_store,
        )
    with pytest.raises(ValueError, match="invalidated"):
        store.handle({
            "action": "export", "consent": True, "output_path": "train-again.jsonl",
            "snapshot_id": snapshot["snapshot_id"],
        }, root=str(repo), task_store=task_store)


def test_candidate_delete_removes_payload_and_keeps_metadata_only_audit(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(state="private example payload"), root=str(repo), task_store=task_store)
    cid = captured["candidate_id"]
    result = store.handle({"action": "delete", "candidate_id": cid, "consent": True}, root=str(repo), task_store=task_store)

    assert result["deleted"] is True
    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0
    with closing(sqlite3.connect(store.path)) as con:
        rows = con.execute("SELECT action,metadata_json FROM laya_candidate_events").fetchall()
    assert any(action == "deleted" for action, _metadata in rows)
    assert all("private example payload" not in metadata for _action, metadata in rows)


@pytest.mark.parametrize("changes", [
    {"options": ["stop", "continue"]},
    {"category": "arbitrary"},
    {"extra": "rejected"},
])
def test_candidate_capture_rejects_untyped_or_noncanonical_input(candidate_env, changes):
    repo, _state, task_store, store = candidate_env
    operation = _capture()
    candidate = operation["candidate"]
    candidate.update(changes)
    with pytest.raises(ValueError):
        store.handle(operation, root=str(repo), task_store=task_store)


def test_candidate_operations_are_scoped_to_authorized_repository(candidate_env, tmp_path):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    with pytest.raises(ValueError, match="not found"):
        store.handle({"action": "verify", "candidate_id": captured["candidate_id"], "consent": True, "reviewer_ref": "reviewer-x"}, root=str(other_repo), task_store=task_store)
