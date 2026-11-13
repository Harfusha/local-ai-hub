import json
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

import local_ai_hub.laya_candidates as candidates_module
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.app import LocalAIApp
from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.laya_dataset_merge import _validate_row
from local_ai_hub.laya_candidates import LayaCandidateStore, LocalModelReviewResult
from tools.model_training.laya_backend import _validate_laya_label_provenance
from local_ai_hub.laya_decisions import (
    ContextSourceEvidence,
    DecisionInput,
    DecisionMode,
    DecisionRequest,
    DecisionResult,
)


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


def _capture(*, state="A short approved state", **changes):
    operation = {
        "action": "capture",
        "task_id": "task-1",
        "session_id": "session-1",
        "_runtime_capture_token": candidates_module._RUNTIME_CAPTURE_TOKEN,
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


def test_capture_persists_only_real_runtime_candidate(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    assert captured["success"] is True
    assert captured["status"] == "pending"
    with closing(sqlite3.connect(store.path)) as con:
        candidate_json = con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()[0]
        consent_table = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='laya_candidate_consents'"
        ).fetchone()
    assert "consent_receipt_id" not in candidate_json
    assert "per_example_consented" not in candidate_json
    assert '"annotations"' not in candidate_json
    assert consent_table is None


def test_default_candidate_store_accepts_one_local_operator_label(candidate_env):
    repo, state, task_store, _configured_store = candidate_env
    store = LayaCandidateStore(state)
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    labeled = store.handle(
        {"action": "label", "candidate_id": captured["candidate_id"], "target": "fast"},
        root=str(repo),
        task_store=task_store,
    )

    assert labeled["success"] is True
    assert labeled["status"] == "verified"
    with closing(sqlite3.connect(store.path)) as con:
        payload = con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()[0]
    candidate = json.loads(payload)
    assert candidate["label_status"] == "verified"
    assert candidate["label_provenance"]["method"] == "local_operator_confirmation"


def test_unverified_export_error_does_not_imply_reviewer_quorum():
    with pytest.raises(ValueError, match="requires a verified human label"):
        candidates_module._export_label_provenance({"label_status": "pending"}, {})


def test_candidate_export_rejects_legacy_multi_reviewer_label():
    target = {"route": "fast"}
    target_sha256 = hashlib.sha256(
        json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    candidate = {
        "label_status": "verified",
        "label_provenance": {
            "method": "blind_double_annotation",
            "rubric_version": "laya-source-label-v1",
            "annotations": [{"annotator_ref": "a"}, {"annotator_ref": "b"}],
            "adjudication": {"reviewer_ref": "c"},
            "verification": {"method": "authenticated_human_review", "reviewer_ref": "d"},
            "target_sha256": target_sha256,
        },
    }

    with pytest.raises(ValueError, match="local operator confirmation"):
        candidates_module._export_label_provenance(candidate, target)


def test_dataset_merge_error_names_supported_label_provenance():
    expected = {"route": "fast"}
    expected_hash = hashlib.sha256(
        json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    candidate_hash = "a" * 64
    proof = {
        "status": "verified",
        "method": "unrecognized",
        "rubric_version": "laya-source-label-v1",
        "target_sha256": expected_hash,
    }
    row = {
        "id": "candidate-1",
        "group_id": "group-1",
        "source_sha256": candidate_hash,
        "state": "bounded state",
        "questions": {"route": {}},
        "expected": expected,
        "provenance": {
            "source": "laya_candidate_store",
            "data_class": "local_scoped",
            "candidate_id": "candidate-1",
            "candidate_sha256": candidate_hash,
            "repository_scope_sha256": "b" * 64,
            "task_id": "task-1",
            "session_id": "session-1",
            "evidence_ids": ["ev-1"],
            "label_provenance": proof,
        },
    }

    with pytest.raises(ValueError, match="local operator confirmation"):
        _validate_row(row)


def test_context_source_candidate_persists_only_redacted_raw_training_content():
    candidate = LayaCandidateStore._candidate_input({
        "decision_schema_version": "laya-hub-v1",
        "category": "context_source",
        "state": {
            "gap_code": "unresolved_evidence_gap",
            "source_codes": ["indexed", "artifact"],
            "freshness_codes": ["current", "current"],
            "coverage_codes": ["partial", "complete"],
            "raw_task_input": "Find route for token=secret-value",
            "raw_context_excerpt": "router.py maps the request",
        },
        "options": ["indexed", "artifact"],
        "language": "en",
        "preprocessing": {"name": "laya-runtime", "version": "fixture"},
        "evidence_ids": ["E" + "a" * 20, "E" + "b" * 20],
    })

    assert candidate["state"]["raw_task_input"] == "Find route for token=[REDACTED]"
    assert candidate["state"]["raw_context_excerpt"] == "router.py maps the request"


def test_decision_candidate_accepts_typed_raw_and_capture_metadata_fields():
    state = {f"signal_{index}": "typed" for index in range(32)}
    state.update({
        "raw_task_input": "Route this task.",
        "raw_context_excerpt": "Current evidence excerpt.",
        "raw_model_response": "Model response excerpt.",
        "raw_tool_output_excerpt": "Tool output excerpt.",
        "training_redacted_fields": "none",
        "training_missing_fields": "none",
        "training_missing_reason": "none",
    })

    candidate = LayaCandidateStore._candidate_input({
        "decision_schema_version": "laya-decision-v1",
        "category": "model_route",
        "state": state,
        "options": ["fast", "smart"],
        "language": "en",
        "preprocessing": {"name": "laya-runtime", "version": "fixture"},
        "evidence_ids": [],
    })

    assert len(candidate["state"]) == 39


def test_laya_reviewer_public_key_config_rejects_retired_ssh_reviewers():
    validate_config({"laya": {"reviewers": {"public_keys": []}}})
    with pytest.raises(ConfigError, match="list of OpenSSH public-key strings"):
        validate_config({"laya": {"reviewers": {"public_keys": "ssh-ed25519 key"}}})
    with pytest.raises(ConfigError, match="list of OpenSSH public-key strings"):
        validate_config({"laya": {"reviewers": {"public_keys": [""]}}})
    with pytest.raises(ConfigError, match="SSH reviewer keys are retired; Laya review is local-only"):
        validate_config({"laya": {"reviewers": {"public_keys": ["ssh-ed25519 AAAA test"]}}})


def test_local_operator_can_confirm_label_without_reviewer_keys(candidate_env):
    repo, state, task_store, _test_authenticator_store = candidate_env
    store = LayaCandidateStore(state)
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    labeled = store.handle(
        {"action": "label", "candidate_id": captured["candidate_id"], "target": "fast"},
        root=str(repo),
        task_store=task_store,
    )

    assert labeled["status"] == "verified"
    with closing(sqlite3.connect(store.path)) as con:
        row = con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()
    candidate = json.loads(row[0])
    provenance = candidates_module._export_label_provenance(
        candidate, {"model_route": "fast"}
    )
    assert provenance["method"] == "local_operator_confirmation"
    assert provenance["status"] == "verified"
    row = {
        "id": captured["candidate_id"],
        "group_id": "group-1",
        "source_sha256": "c" * 64,
        "state": "A short approved state",
        "questions": {"model_route": {"criteria": ["fast", "smart", "background"]}},
        "expected": {"model_route": "fast"},
        "provenance": {
            "source": "laya_candidate_store",
            "data_class": "local_scoped",
            "candidate_id": captured["candidate_id"],
            "candidate_sha256": "c" * 64,
            "repository_scope_sha256": "d" * 64,
            "task_id": "task-1",
            "session_id": "session-1",
            "evidence_ids": ["ev-1"],
            "label_provenance": provenance,
        },
    }
    _validate_row(row)
    _validate_laya_label_provenance(
        {
            "data_class": "local_scoped",
            "candidate_id": captured["candidate_id"],
            "candidate_sha256": "c" * 64,
            "label_provenance": provenance,
        },
        {"model_route": "fast"},
        label="local operator test",
    )


def test_model_review_provenance_is_not_human_training_label():
    candidate = {
        "label_status": "model_reviewed",
        "label_provenance": {
            "rubric_version": "laya-source-label-v1",
            "review_kind": "local_model",
            "model_id": "local-test-model",
            "model_revision": "rev-1",
            "target": "indexed",
        },
    }

    with pytest.raises(ValueError, match="human-confirmed"):
        candidates_module._export_label_provenance(
            candidate, {"context_source": "indexed"}
        )


def test_runtime_outcome_records_deterministic_baseline_and_unobserved_downstream(candidate_env):
    repo, _state, task_store, store = candidate_env
    evidence_ids = ["E" + "a" * 20, "E" + "b" * 20]
    evidence = ContextSourceEvidence.from_mapping({
        "gap_code": "unresolved_evidence_gap",
        "source_codes": ["indexed", "artifact"],
        "freshness_codes": ["current", "current"],
        "coverage_codes": ["partial", "complete"],
        "evidence_ids": evidence_ids,
        "training_content": {"task_input": "Find route"},
    })
    request = DecisionRequest.from_mapping(
        {"category": "context_source", "evidence_ids": evidence_ids, "options": ["indexed", "artifact"]},
        decision_id="decision-1",
        mode=DecisionMode.SHADOW,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
    )
    decision = DecisionResult.from_mapping(request, {
        "success": True,
        "status": "success",
        "suggestion": "artifact",
        "reason_codes": ["EVIDENCE_SUFFICIENT"],
    })
    runtime = SimpleNamespace(
        runtime_version="fixture", model_id="laya", revision="rev", provider="mock",
        device="cpu", device_class="cpu", device_name="mock", parameter_device="cpu",
        execution_verification="NOT_VERIFIED", quality_status="NOT_EVALUATED",
        latency_ms=3.0, input_tokens=12, output_tokens=2, fallback_reason="",
    )

    captured = store.capture_runtime_outcome(
        request,
        evidence,
        SimpleNamespace(decision=decision, runtime=runtime),
        root=str(repo),
        task_store=task_store,
        evidence_store=_evidence_store(),
        baseline={
            "method": "retrieval_rank_order",
            "suggestion": "indexed",
            "evidence_id": evidence_ids[0],
        },
    )

    with closing(sqlite3.connect(store.path)) as con:
        payload = con.execute(
            "SELECT metadata_json FROM laya_candidate_events WHERE candidate_id=? AND action='runtime_output'",
            (captured["candidate_id"],),
        ).fetchone()[0]
    event = json.loads(payload)
    assert event["baseline"] == {
        "status": "recorded",
        "method": "retrieval_rank_order",
        "suggestion": "indexed",
        "evidence_id": evidence_ids[0],
    }
    assert event["downstream_outcome"] == {
        "status": "not_observed",
        "reason": "shadow_only_not_user_exposed",
    }

    duplicate_capture = store.capture_runtime_outcome(
        request,
        evidence,
        SimpleNamespace(decision=decision, runtime=runtime),
        root=str(repo),
        task_store=task_store,
        evidence_store=_evidence_store(),
        baseline={
            "method": "retrieval_rank_order",
            "suggestion": "indexed",
            "evidence_id": evidence_ids[0],
        },
    )
    assert duplicate_capture["duplicate"] is True
    assert duplicate_capture["candidate_id"] == captured["candidate_id"]

    history = store.handle(
        {"action": "runtime_output_history", "candidate_id": captured["candidate_id"], "limit": 1},
        root=str(repo),
        task_store=task_store,
    )
    assert history["success"] is True
    assert history["has_more"] is True
    assert history["next_event_id"] == history["events"][0]["event_id"]
    assert len(history["events"]) == 1
    assert history["events"][0]["metadata"] == event
    next_page = store.handle(
        {
            "action": "runtime_output_history",
            "candidate_id": captured["candidate_id"],
            "after_event_id": history["next_event_id"],
            "limit": 1,
        },
        root=str(repo),
        task_store=task_store,
    )
    assert next_page["has_more"] is False
    assert next_page["next_event_id"] is None
    assert len(next_page["events"]) == 1
    assert next_page["events"][0]["metadata"] == event

    blind_candidate = store.handle(
        {"action": "get", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )["candidate"]
    assert "model_output" not in blind_candidate
    assert "targets" not in blind_candidate


def test_runtime_outcome_records_server_derived_baseline_for_typed_category(candidate_env):
    repo, _state, task_store, store = candidate_env
    evidence_id = "E" + "c" * 20
    decision_input = DecisionInput.from_mapping({
        "state": {"complete": "false", "unsatisfied_count": "1", "stale_count": "0"},
        "training_content": {},
    })
    request = DecisionRequest.from_mapping(
        {
            "category": "completion_gap",
            "evidence_ids": [evidence_id],
            "options": ["missing_verification", "resolve_blocker"],
        },
        decision_id="decision-completion-gap",
        mode=DecisionMode.SHADOW,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
    )
    decision = DecisionResult.from_mapping(request, {
        "success": True,
        "status": "success",
        "suggestion": "missing_verification",
        "reason_codes": ["INSUFFICIENT_EVIDENCE"],
    })
    runtime = SimpleNamespace(
        runtime_version="fixture", model_id="laya", revision="rev", provider="mock",
        device="cpu", device_class="cpu", device_name="mock", parameter_device="cpu",
        execution_verification="NOT_VERIFIED", quality_status="NOT_EVALUATED",
        latency_ms=3.0, input_tokens=12, output_tokens=2, fallback_reason="",
    )

    captured = store.capture_runtime_outcome(
        request,
        decision_input,
        SimpleNamespace(decision=decision, runtime=runtime),
        root=str(repo),
        task_store=task_store,
        evidence_store=_evidence_store(),
        baseline={
            "method": "agent_os_completion_gate",
            "suggestion": "not_ready",
            "evidence_id": evidence_id,
        },
    )

    with closing(sqlite3.connect(store.path)) as con:
        payload = con.execute(
            "SELECT metadata_json FROM laya_candidate_events WHERE candidate_id=? AND action='runtime_output'",
            (captured["candidate_id"],),
        ).fetchone()[0]
    event = json.loads(payload)
    assert event["baseline"] == {
        "status": "recorded",
        "method": "agent_os_completion_gate",
        "suggestion": "not_ready",
        "evidence_id": evidence_id,
    }

    invalid_baseline = {
        "method": "agent_os_completion_gate",
        "suggestion": "not_ready",
        "evidence_id": "E" + "d" * 20,
    }
    with pytest.raises(ValueError, match="request evidence ID"):
        store.capture_runtime_outcome(
            request,
            decision_input,
            SimpleNamespace(decision=decision, runtime=runtime),
            root=str(repo),
            task_store=task_store,
            evidence_store=_evidence_store(),
            baseline=invalid_baseline,
        )

    invalid_baseline["evidence_id"] = evidence_id
    invalid_baseline["method"] = "unregistered_method"
    with pytest.raises(ValueError, match="not registered"):
        store.capture_runtime_outcome(
            request,
            decision_input,
            SimpleNamespace(decision=decision, runtime=runtime),
            root=str(repo),
            task_store=task_store,
            evidence_store=_evidence_store(),
            baseline=invalid_baseline,
        )


def test_duplicate_capture_is_not_stored_twice(candidate_env):
    repo, _state, task_store, store = candidate_env
    first = store.handle(_capture(state="same"), root=str(repo), task_store=task_store)
    duplicate_operation = _capture(state="same")
    second = store.handle(duplicate_operation, root=str(repo), task_store=task_store)

    with closing(sqlite3.connect(store.path)) as con:
        payload = con.execute("SELECT candidate_json FROM laya_candidates WHERE candidate_id=?", (first["candidate_id"],)).fetchone()[0]
        candidate_count = con.execute("SELECT COUNT(*) FROM laya_candidates").fetchone()[0]
    assert second["duplicate"] is True
    assert "consent_receipt_id" not in payload
    assert candidate_count == 1


def test_capture_rejects_retired_per_example_consent_fields(candidate_env):
    repo, _state, task_store, store = candidate_env
    operation = _capture()
    operation["consent_receipt_id"] = "receipt-retired"

    with pytest.raises(ValueError, match="capture fields invalid"):
        store.handle(operation, root=str(repo), task_store=task_store)

    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0


def test_capture_rejects_retired_per_example_consent_boolean(candidate_env):
    repo, _state, task_store, store = candidate_env
    operation = _capture(state="different", per_example_consented=True)

    with pytest.raises(ValueError, match="capture fields invalid"):
        store.handle(operation, root=str(repo), task_store=task_store)


def test_deleted_candidate_can_be_replaced_by_later_runtime_outcome(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(state="delete me"), root=str(repo), task_store=task_store)
    store.handle({"action": "delete", "candidate_id": captured["candidate_id"]}, root=str(repo), task_store=task_store)
    replacement = store.handle(_capture(state="replacement"), root=str(repo), task_store=task_store)
    assert replacement["success"] is True


def test_runtime_capture_requires_internal_token_without_receipt(candidate_env):
    repo, _state, task_store, store = candidate_env
    operation = _capture(state="reserved sample")
    operation.pop("_runtime_capture_token")
    with pytest.raises(ValueError, match="actual Laya runtime callback"):
        store.handle(operation, root=str(repo), task_store=task_store)


def _context_source_capture(*, state=None, evidence_ids=None):
    operation = _capture()
    candidate = operation["candidate"]
    candidate.update({
        "category": "context_source",
        "state": state or {
            "gap_code": "unresolved_evidence_gap",
            "source_codes": ["indexed", "artifact"],
            "freshness_codes": ["current", "current"],
            "coverage_codes": ["partial", "complete"],
        },
        "options": ["indexed", "artifact", "more_evidence"],
        "evidence_ids": evidence_ids or ["E" + "0" * 20, "E" + "1" * 20],
    })
    return operation


def test_context_source_candidate_options_must_match_available_source_codes():
    candidate = _context_source_capture()["candidate"]
    candidate["options"] = ["indexed", "rag"]

    with pytest.raises(ValueError, match="not present in context_source codes"):
        LayaCandidateStore._candidate_input(candidate)


def test_context_source_capture_rejects_codes_without_matching_stored_provenance(candidate_env):
    repo, _state, _task_store, _store = candidate_env
    candidate = LayaCandidateStore._candidate_input(_context_source_capture()["candidate"])

    with pytest.raises(ValueError, match="do not match recorded provenance"):
        LayaCandidateStore._validate_context_source_evidence(
            candidate,
            evidence_store=_evidence_store(source_codes=["indexed", "rag"]),
            canonical_root=str(repo),
        )


def _evidence_store(*, stale=False, available=True, root_override=None, source_codes=None):
    def get_many(evidence_ids, *, verify, root):
        return [
            {
                "success": available,
                "evidence_id": evidence_id,
                "root": root if root_override is None else root_override,
                "stale": stale,
            }
            for evidence_id in evidence_ids
        ]

    def validate_source_provenance(evidence_ids, claimed_codes, *, root):
        return (
            available
            and not stale
            and (root_override is None or root_override == root)
            and list(claimed_codes) == (
                ["indexed", "artifact"] if source_codes is None else source_codes
            )
            and len(evidence_ids) == len(claimed_codes)
        )

    return SimpleNamespace(
        get_many=get_many,
        validate_source_provenance=validate_source_provenance,
    )


def _capture_batch(*, examples=None):
    first = _capture()
    second = _capture()
    example = {"candidate": first["candidate"]}
    second_example = {"candidate": second["candidate"]}
    return {
        "action": "capture_batch",
        "task_id": "task-1",
        "session_id": "session-1",
        "examples": [example, second_example] if examples is None else examples,
    }


def _capture_and_verify(store, repo, task_store, task_id, session_id, state, suffix):
    operation = _capture(state=state)
    operation["task_id"] = task_id
    operation["session_id"] = session_id
    captured = store.handle(
        operation,
        root=str(repo),
        task_store=task_store,
        _runtime_capture_token=candidates_module._RUNTIME_CAPTURE_TOKEN,
    )
    cid = captured["candidate_id"]
    store.handle({
        "action": "label", "candidate_id": cid, "target": "fast",
    }, root=str(repo), task_store=task_store)
    return cid


def test_context_source_capture_accepts_only_approved_minimal_codes(candidate_env):
    repo, _state, task_store, store = candidate_env

    result = store.handle(
        _context_source_capture(),
        root=str(repo),
        task_store=task_store,
        evidence_store=_evidence_store(),
    )

    assert result["success"] is True
    assert result["status"] == "pending"


def test_direct_capture_is_rejected_and_runtime_capture_uses_internal_token(candidate_env):
    repo, _state, task_store, store = candidate_env
    public_operation = _capture()
    public_operation.pop("_runtime_capture_token")
    with pytest.raises(ValueError, match="actual Laya runtime callback"):
        store.handle(public_operation, root=str(repo), task_store=task_store)
    captured = store.handle(
        _capture(),
        root=str(repo),
        task_store=task_store,
        _runtime_capture_token=candidates_module._RUNTIME_CAPTURE_TOKEN,
    )
    assert captured["success"] is True


def test_context_source_capture_requires_authorized_current_scoped_evidence(candidate_env):
    repo, _state, task_store, store = candidate_env
    invalid_stores = [
        None,
        _evidence_store(available=False),
        _evidence_store(stale=True),
        _evidence_store(root_override=str(repo.parent / "foreign")),
    ]

    for evidence_store in invalid_stores:
        with pytest.raises(ValueError, match="context_source evidence is not authorized and current"):
            store.handle(
                _context_source_capture(),
                root=str(repo),
                task_store=task_store,
                evidence_store=evidence_store,
            )


def test_context_source_batch_authorization_failure_has_no_partial_writes(candidate_env):
    repo, _state, task_store, store = candidate_env
    with pytest.raises(ValueError, match="only actual per-decision runtime callbacks"):
        store.handle(
            {
                "action": "capture_batch",
                "task_id": "task-1",
                "session_id": "session-1",
                "examples": [{"candidate": _context_source_capture()["candidate"]}],
            },
            root=str(repo),
            task_store=task_store,
        )

    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0


@pytest.mark.parametrize(
    ("state", "evidence_ids", "message"),
    [
        ("free-form task or source text", ["E" + "0" * 20, "E" + "1" * 20], "context_source state"),
        (
            {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "artifact"],
                "freshness_codes": ["current"],
                "coverage_codes": ["partial", "complete"],
            },
            ["E" + "0" * 20, "E" + "1" * 20],
            "context_source state codes",
        ),
        (
            {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "artifact"],
                "freshness_codes": ["current", "current"],
                "coverage_codes": ["partial", "complete"],
                "task_text": "must not be captured",
            },
            ["E" + "0" * 20, "E" + "1" * 20],
            "context_source state",
        ),
        (
            {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "artifact"],
                "freshness_codes": ["current", "current"],
                "coverage_codes": ["partial", "complete"],
            },
            ["ev-1", "ev-2"],
            "context_source evidence_ids",
        ),
    ],
)
def test_context_source_capture_rejects_text_malformed_codes_and_unshaped_evidence_ids(
    candidate_env, state, evidence_ids, message
):
    repo, _state, task_store, store = candidate_env

    with pytest.raises(ValueError, match=message):
        store.handle(
            _context_source_capture(state=state, evidence_ids=evidence_ids),
            root=str(repo),
            task_store=task_store,
        )


def test_capture_records_local_scoped_metadata_in_agent_state_database(candidate_env):
    repo, state, task_store, store = candidate_env
    operation = _capture()
    result = store.handle(operation, root=str(repo), task_store=task_store)
    assert result["success"] is True
    assert result["status"] == "pending"
    assert store.path == task_store.state_store.db_path
    assert store.path.exists()
    with closing(sqlite3.connect(store.path)) as con:
        candidate_json = con.execute("SELECT candidate_json FROM laya_candidates WHERE candidate_id=?", (result["candidate_id"],)).fetchone()[0]
        captured_metadata = con.execute(
            "SELECT metadata_json FROM laya_candidate_events WHERE candidate_id=? AND action='captured'",
            (result["candidate_id"],),
        ).fetchone()[0]
    assert "consent_receipt_id" not in json.loads(candidate_json)
    assert json.loads(captured_metadata)["data_class"] == "local_scoped"
    assert not (state / "laya_candidates.sqlite3").exists()
    assert not list(repo.glob("*.sqlite3"))


def test_capture_batch_is_not_an_outcome_source(candidate_env):
    repo, _state, task_store, store = candidate_env
    with pytest.raises(ValueError, match="only actual per-decision runtime callbacks"):
        store.handle(_capture_batch(), root=str(repo), task_store=task_store)
    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0


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


def test_get_returns_review_material_without_laya_output_or_human_labels(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    store.handle({
        "action": "label", "candidate_id": captured["candidate_id"], "target": "fast",
    }, root=str(repo), task_store=task_store)
    with closing(sqlite3.connect(store.path)) as con:
        candidate = json.loads(con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()[0])
        candidate["model_output"] = {"target": "background", "private_marker": "laya-secret"}
        con.execute(
            "UPDATE laya_candidates SET candidate_json=? WHERE candidate_id=?",
            (json.dumps(candidate), captured["candidate_id"]),
        )
        con.commit()

    reviewed = store.handle(
        {"action": "get", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )

    assert reviewed["success"] is True
    assert "status" not in reviewed
    assert reviewed["candidate"]["state"] == "A short approved state"
    assert "model_output" not in reviewed["candidate"]
    assert "targets" not in reviewed["candidate"]
    assert "label_status" not in reviewed["candidate"]
    assert "label_provenance" not in reviewed["candidate"]
    assert "laya-secret" not in json.dumps(reviewed)
    assert "annotator-a" not in json.dumps(reviewed)


def test_get_candidate_is_bound_to_authorized_repository_scope(candidate_env, tmp_path):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    other_repo = tmp_path / "other"
    other_repo.mkdir()

    with pytest.raises(ValueError, match="not found in authorized repository scope"):
        store.handle(
            {"action": "get", "candidate_id": captured["candidate_id"]},
            root=str(other_repo),
            task_store=task_store,
        )


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
    with pytest.raises(ValueError, match="only actual per-decision runtime callbacks"):
        store.handle(_capture_batch(), root=str(repo), task_store=task_store)
    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0


def test_capture_batch_is_unavailable(candidate_env):
    repo, _state, task_store, store = candidate_env
    with pytest.raises(ValueError, match="only actual per-decision runtime callbacks"):
        store.handle(_capture_batch(), root=str(repo), task_store=task_store)
    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0


def test_one_local_operator_can_label_without_reviewer_quorum(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    cid = captured["candidate_id"]
    reviewed = store.handle(
        {"action": "label", "candidate_id": cid, "target": "fast"},
        root=str(repo), task_store=task_store,
    )
    assert reviewed["success"] is True
    assert reviewed["status"] == "verified"


def test_legacy_multi_reviewer_api_actions_are_retired(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    with pytest.raises(ValueError, match="retired; use local operator label"):
        store.handle(
            {"action": "verify", "candidate_id": captured["candidate_id"], "reviewer_ref": "reviewer-x"},
            root=str(repo), task_store=task_store,
        )

    snapshot = store.handle({"action": "prepare_splits"}, root=str(repo), task_store=task_store)
    assert snapshot["sufficiency_status"] == "INSUFFICIENT DATA"
    assert snapshot["candidate_count"] == 0
    assert snapshot["snapshot_id"] is None
    assert store.handle({"action": "list", "status": "pending"}, root=str(repo), task_store=task_store)["count"] == 1


def test_configured_ed25519_keys_are_rejected_for_local_only_review(tmp_path):
    with pytest.raises(ValueError, match="SSH reviewer keys are retired"):
        LayaCandidateStore(tmp_path, reviewer_public_keys=["ssh-ed25519 AAAA test"])



def test_local_operator_label_rejects_caller_supplied_reviewer_identities(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    candidate_id = captured["candidate_id"]
    labels = {
        "action": "label",
        "candidate_id": candidate_id,
        "annotations": [
            {"annotator_ref": "annotator-a", "target": "fast"},
            {"annotator_ref": "annotator-b", "target": "fast"},
        ],
        "adjudication": {"reviewer_ref": "adjudicator", "target": "fast"},
    }
    with pytest.raises(ValueError, match="label fields invalid"):
        store.handle(labels, root=str(repo), task_store=task_store)

    result = store.handle(
        {"action": "label", "candidate_id": candidate_id, "target": "fast"},
        root=str(repo), task_store=task_store,
    )
    assert result["status"] == "verified"

    assert store.handle({"action": "list", "status": "verified"}, root=str(repo), task_store=task_store)["count"] == 1


def test_split_preparation_without_verified_candidates_reports_insufficient_data(candidate_env):
    repo, _state, task_store, store = candidate_env
    store.handle(_capture(), root=str(repo), task_store=task_store)
    result = store.handle({"action": "prepare_splits"}, root=str(repo), task_store=task_store)

    assert result["snapshot_id"] is None
    assert result["candidate_count"] == 0
    assert result["status_counts"] == {"pending": 1}
    assert result["sufficiency_status"] == "INSUFFICIENT DATA"


def test_verified_local_scoped_candidate_needs_no_per_example_receipt(candidate_env):
    repo, _state, task_store, store = candidate_env
    _capture_and_verify(store, repo, task_store, "task-1", "session-1", "verified local example", "no-receipt")
    snapshot = store.handle({"action": "prepare_splits"}, root=str(repo), task_store=task_store)
    assert snapshot["candidate_count"] == 1
    assert snapshot["sufficiency_status"] == "INSUFFICIENT DATA"


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
            state = {"scenario_code": f"case_{i}", "source_digest": digest}
        candidates.append(_capture_and_verify(store, repo, task_store, task_id, session_id, state, i))

    # Same task/session group must remain whole even when examples differ.
    _capture_and_verify(
        store, repo, task_store, task_specs[2][0], task_specs[2][1],
        "A second distinct state for task two, with separate evidence and option context.", "same-group",
    )
    snapshot = store.handle({"action": "prepare_splits"}, root=str(repo), task_store=task_store)
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
        {"snapshot_id": snapshot["snapshot_id"]},
        root=str(repo), task_store=task_store,
    )
    zip_rows = [json.loads(line) for line in zip_payload.decode("utf-8").splitlines()]
    assert all(isinstance(row["state"], str) for row in zip_rows)
    assert any(row["state"].startswith('{"scenario_code":') for row in zip_rows)
    for row in zip_rows:
        _validate_row(row)
    assert len(zip_rows) == snapshot["split_counts"]["train"]
    assert all(set(row) == {"id", "group_id", "source_sha256", "state", "questions", "expected", "provenance"} for row in zip_rows)
    assert all(row["provenance"]["data_class"] == "local_scoped" for row in zip_rows)
    assert all("per_example_consented" not in row["provenance"] for row in zip_rows)
    assert all("consent_receipt_sha256" not in row["provenance"] for row in zip_rows)

    exported = store.handle({
        "action": "export", "snapshot_id": snapshot["snapshot_id"],
    }, root=str(repo), task_store=task_store)
    assert exported["count"] == snapshot["split_counts"]["train"]
    export_rows = [json.loads(line) for line in Path(exported["output_path"]).read_text(encoding="utf-8").splitlines()]
    assert all(isinstance(row["state"], str) for row in export_rows)
    assert all(row["provenance"]["data_class"] == "local_scoped" for row in export_rows)
    assert all("per_example_consented" not in row["provenance"] for row in export_rows)
    train_states = {
        (
            state if isinstance(state := json.loads(candidate_json)["state"], str)
            else json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        )
        for _task_id, _session_id, split_name, candidate_json, _candidate_id in assignments if split_name == "train"
    }
    assert {row["state"] for row in export_rows} == train_states
    test_candidate_id = next(candidate_id for _task, _session, split_name, _json, candidate_id in assignments if split_name == "test")
    store.handle(
        {"action": "delete", "candidate_id": test_candidate_id},
        root=str(repo), task_store=task_store,
    )
    with pytest.raises(ValueError, match="invalidated"):
        store.export_train_payload(
            {"snapshot_id": snapshot["snapshot_id"]},
            root=str(repo), task_store=task_store,
        )
    with pytest.raises(ValueError, match="invalidated"):
        store.handle({
            "action": "export", "snapshot_id": snapshot["snapshot_id"],
        }, root=str(repo), task_store=task_store)


def test_candidate_delete_purges_private_events_and_invalidates_export(candidate_env, monkeypatch):
    repo, _state, task_store, store = candidate_env
    monkeypatch.setattr(candidates_module, "_split_for_group", lambda _group: "train")
    operation = _capture(state="private example payload")
    cid = _capture_and_verify(store, repo, task_store, "task-1", "session-1", operation["candidate"]["state"], "delete")
    snapshot = store.handle({"action": "prepare_splits"}, root=str(repo), task_store=task_store)
    exported = store.handle(
        {"action": "export", "snapshot_id": snapshot["snapshot_id"]},
        root=str(repo), task_store=task_store,
    )
    output_path = Path(exported["output_path"])
    assert output_path.is_file()
    with closing(store._connect(task_store)) as con:
        store._event(con, cid, "scope", "task-1", "runtime_output", {"suggestion": "private model output"}, 1.0)

    result = store.handle({"action": "delete", "candidate_id": cid}, root=str(repo), task_store=task_store)

    assert result["deleted"] is True
    assert not output_path.exists()
    assert store.handle({"action": "list"}, root=str(repo), task_store=task_store)["count"] == 0
    with closing(sqlite3.connect(store.path)) as con:
        rows = con.execute("SELECT action,metadata_json FROM laya_candidate_events").fetchall()
    actions = {action for action, _metadata in rows}
    assert actions == {"deleted"}
    serialized_events = json.dumps(rows)
    assert "private example payload" not in serialized_events
    assert "private model output" not in serialized_events


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
        store.handle({"action": "label", "candidate_id": captured["candidate_id"], "target": "fast"}, root=str(other_repo), task_store=task_store)


def test_local_model_review_uses_server_bound_callback_and_stays_separate_from_operator_label(candidate_env):
    repo, state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    with closing(sqlite3.connect(store.path)) as con:
        initial_json = con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()[0]
    initial_candidate = json.loads(initial_json)

    callback_inputs = []

    def local_reviewer(request):
        callback_inputs.append(request)
        return LocalModelReviewResult(
            decision="smart",
            confidence=0.91,
            provider="ollama",
            model_id="test-reviewer",
            model_revision="test-revision",
            runtime_version="test-runtime",
            device="cpu",
        )

    reviewer_store = LayaCandidateStore(
        state,
        local_model_reviewer=local_reviewer,
    )

    reviewed = reviewer_store.handle(
        {
            "action": "model_review",
            "candidate_id": captured["candidate_id"],
        },
        root=str(repo),
        task_store=task_store,
    )

    assert len(callback_inputs) == 1
    assert callback_inputs[0]["candidate_id"] == captured["candidate_id"]
    review_candidate = callback_inputs[0]["candidate"]
    assert review_candidate["state"] == "A short approved state"
    assert "targets" not in review_candidate
    assert "label_provenance" not in review_candidate
    assert "model_reviews" not in review_candidate
    assert reviewed["success"] is True
    assert reviewed["status"] == "pending"
    with closing(sqlite3.connect(store.path)) as con:
        candidate_json, candidate_sha256 = con.execute(
            "SELECT candidate_json,content_hash FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()
    candidate = json.loads(candidate_json)
    model_review = candidate["model_reviews"][0]
    assert model_review["kind"] == "local_model_review"
    assert model_review["decision"] == "smart"
    assert model_review["confidence"] == 0.91
    assert model_review["reviewer_identity_status"] == "attested"
    assert model_review["reviewer_model"] == "test-reviewer"
    assert model_review["rubric_version"] == "laya-decision-review-v1"
    assert model_review["reviewer_revision"] == "test-revision"
    assert model_review["provider"] == "ollama"
    assert model_review["runtime_version"] == "test-runtime"
    assert model_review["candidate_sha256"] == candidate_sha256
    assert candidate.get("targets") == initial_candidate.get("targets")
    assert candidate.get("label_provenance") == initial_candidate.get("label_provenance")

    operator_store = LayaCandidateStore(state)
    labeled = operator_store.handle(
        {
            "action": "label",
            "candidate_id": captured["candidate_id"],
            "target": "fast",
        },
        root=str(repo),
        task_store=task_store,
    )
    assert labeled["status"] == "verified"
    with closing(sqlite3.connect(store.path)) as con:
        candidate_json = con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()[0]
    candidate = json.loads(candidate_json)
    assert candidate["targets"] == {"model_route": "fast"}
    assert candidate["label_provenance"]["method"] == "local_operator_confirmation"
    assert candidate["model_reviews"][0]["decision"] == "smart"


def test_model_review_rejects_caller_output_and_missing_local_reviewer(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    with pytest.raises(RuntimeError, match="local model reviewer is not configured"):
        store.handle(
            {"action": "model_review", "candidate_id": captured["candidate_id"]},
            root=str(repo),
            task_store=task_store,
        )

    with pytest.raises(ValueError, match="model_review fields invalid"):
        store.handle(
            {
                "action": "model_review",
                "candidate_id": captured["candidate_id"],
                "decision": "smart",
                "confidence": 0.99,
                "reviewer_model": "caller-claimed-model",
            },
            root=str(repo),
            task_store=task_store,
        )


def test_local_reviewer_cannot_mutate_candidate_options(candidate_env):
    repo, state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    def mutating_reviewer(request):
        request["candidate"]["questions"]["model_route"]["criteria"] = ["caller-added"]
        return LocalModelReviewResult(
            decision="caller-added",
            confidence=0.99,
            provider="ollama",
            model_id="test-reviewer",
            model_revision="test-revision",
            runtime_version="test-runtime",
            device="cpu",
        )

    reviewer_store = LayaCandidateStore(state, local_model_reviewer=mutating_reviewer)
    with pytest.raises(RuntimeError, match="unsupported decision"):
        reviewer_store.handle(
            {"action": "model_review", "candidate_id": captured["candidate_id"]},
            root=str(repo),
            task_store=task_store,
        )

    history = store.handle(
        {"action": "model_review_history", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )
    assert history["model_reviews"] == []


def test_local_reviewer_rejects_nonlocal_execution(candidate_env):
    _repo, _state, _task_store, _store = candidate_env
    with pytest.raises(ValueError, match="local execution provenance"):
        LocalModelReviewResult(
            decision="smart",
            confidence=0.91,
            provider="remote-provider",
            model_id="test-reviewer",
            model_revision="test-revision",
            runtime_version="test-runtime",
            device="cpu",
            is_local=False,
        )


def test_local_model_review_rejects_candidate_changed_during_inference(candidate_env):
    repo, state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    operator_store = LayaCandidateStore(state)

    def local_reviewer(_request):
        operator_store.handle(
            {
                "action": "label",
                "candidate_id": captured["candidate_id"],
                "target": "fast",
            },
            root=str(repo),
            task_store=task_store,
        )
        return LocalModelReviewResult(
            decision="smart",
            confidence=0.91,
            provider="ollama",
            model_id="test-reviewer",
            model_revision="test-revision",
            runtime_version="test-runtime",
            device="cpu",
        )

    reviewer_store = LayaCandidateStore(state, local_model_reviewer=local_reviewer)
    with pytest.raises(ValueError, match="candidate changed during local model review"):
        reviewer_store.handle(
            {"action": "model_review", "candidate_id": captured["candidate_id"]},
            root=str(repo),
            task_store=task_store,
        )

    with closing(sqlite3.connect(store.path)) as con:
        candidate_json = con.execute(
            "SELECT candidate_json FROM laya_candidates WHERE candidate_id=?",
            (captured["candidate_id"],),
        ).fetchone()[0]
    candidate = json.loads(candidate_json)
    assert candidate["targets"] == {"model_route": "fast"}
    assert candidate["label_provenance"]["method"] == "local_operator_confirmation"
    assert "model_reviews" not in candidate


def test_model_review_history_requires_explicit_scoped_read(candidate_env):
    repo, state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    reviewer_store = LayaCandidateStore(
        state,
        local_model_reviewer=lambda _request: LocalModelReviewResult(
            decision="smart",
            confidence=0.91,
            provider="ollama",
            model_id="test-reviewer",
            model_revision="test-revision",
            runtime_version="test-runtime",
            device="cpu",
        ),
    )
    reviewer_store.handle(
        {
            "action": "model_review",
            "candidate_id": captured["candidate_id"],
        },
        root=str(repo),
        task_store=task_store,
    )

    ordinary_get = store.handle(
        {"action": "get", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )
    assert "model_reviews" not in ordinary_get["candidate"]

    history = reviewer_store.handle(
        {"action": "model_review_history", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )
    assert history["success"] is True
    assert history["model_reviews"][0]["decision"] == "smart"
    assert history["model_reviews"][0]["reviewer_model"] == "test-reviewer"


def test_ssh_review_challenge_is_retired_for_local_only_review(candidate_env):
    repo, _state, task_store, store = candidate_env

    with pytest.raises(ValueError, match="SSH reviewer challenges are retired"):
        store.handle(
            {
                "action": "review_challenge",
                "candidate_id": "candidate-1",
                "review_action": "verify",
                "role": "verification",
                "reviewer_fingerprint": "SHA256:remote-reviewer",
            },
            root=str(repo),
            task_store=task_store,
        )


def test_completion_outcome_is_scoped_and_visible_in_candidate_history(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)

    observed = store.record_completion_outcome(
        {
            "task_id": "task-1",
            "session_id": "session-1",
            "outcome": {
                "status": "passed",
                "reason_code": "completion_gate_passed",
                "duration_ms": 12.5,
                "repository_revision": "a" * 40,
                "mutation_generation": 3,
            },
        },
        root=str(repo),
        task_store=task_store,
    )

    assert observed == {"success": True, "candidate_count": 1, "event_count": 1}
    history = store.handle(
        {"action": "runtime_output_history", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )
    assert history["success"] is True
    assert history["events"][0]["event_type"] == "completion_outcome"
    assert history["events"][0]["metadata"] == {
        "status": "passed",
        "reason_code": "completion_gate_passed",
        "duration_ms": 12.5,
        "repository_revision": "a" * 40,
        "mutation_generation": 3,
    }


def test_app_local_model_reviewer_uses_installed_reasoning_route_and_attested_metadata():
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {"reasoning": "qwen3.5:9b"}}
    app.runtime = SimpleNamespace(
        # Tiered runtimes may report only fast-tier inventory here; model_digest
        # resolves the exact configured model through its serving tier.
        installed_models=lambda: [],
        model_digest=lambda _model: "sha256:" + "a" * 64,
        version=lambda: "0.17.7",
        is_online=lambda: True,
    )
    calls = {}

    def generate(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {
            "success": True,
            "model": "qwen3.5:9b",
            "_lah_provider": "ollama",
            "execution_profile": {"device": "cuda:0"},
            "text": json.dumps({"decision": "artifact", "confidence": 0.91}),
        }

    app.services = SimpleNamespace(_generate=generate)
    request = {
        "candidate_id": "candidate-1",
        "task_id": "task-1",
        "candidate_sha256": "b" * 64,
        "candidate": {
            "category": "context_source",
            "options": ["indexed", "artifact", "more_evidence"],
            "state": {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "artifact"],
                "freshness_codes": ["current", "current"],
                "coverage_codes": ["partial", "complete"],
                "raw_task_input": "Find the route definition.",
                "raw_context_excerpt": "artifact: route definitions are listed.",
            },
            "questions": {
                "context_source": {
                    "id": "context_source",
                    "type": "choice",
                    "instructions": "Choose the next authorized context source or evidence action.",
                    "criteria": {"indexed": "indexed", "artifact": "artifact", "more_evidence": "more evidence"},
                },
            },
            "evidence_ids": ["ev-indexed", "ev-artifact"],
        },
    }

    result = app._review_laya_candidate_locally(request)

    assert isinstance(result, LocalModelReviewResult)
    assert result.decision == "artifact"
    assert result.confidence == 0.91
    assert result.provider == "ollama"
    assert result.model_id == "qwen3.5:9b"
    assert result.model_revision == "sha256:" + "a" * 64
    assert result.runtime_version == "0.17.7"
    assert result.device == "cuda:0"
    kwargs = calls["kwargs"]
    assert calls["args"][0] == "qwen3.5:9b"
    assert kwargs["source"] == "review:reasoning"
    assert kwargs["use_cache"] is False
    assert kwargs["format"]["properties"]["decision"]["enum"] == [
        "indexed", "artifact", "more_evidence", "abstain",
    ]
    assert "Find the route definition." in calls["args"][1]


def test_app_local_model_reviewer_supports_other_typed_decision_categories():
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {"reasoning": "qwen3.5:9b"}}
    app.runtime = SimpleNamespace(
        model_digest=lambda _model: "sha256:" + "a" * 64,
        version=lambda: "0.17.7",
        is_online=lambda: True,
    )
    calls = {}

    def generate(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {
            "success": True,
            "model": "qwen3.5:9b",
            "_lah_provider": "ollama",
            "execution_profile": {"device": "cuda:0"},
            "text": json.dumps({"decision": "smart", "confidence": 0.82}),
        }

    app.services = SimpleNamespace(_generate=generate)
    request = {
        "candidate_id": "candidate-route",
        "task_id": "task-route",
        "candidate_sha256": "b" * 64,
        "candidate": {
            "category": "model_route",
            "options": ["fast", "smart", "generic"],
            "state": {
                "task_type": "code",
                "complexity": "heavy",
                "generator_model": "qwen3.5:9b",
                "raw_task_input": "Implement the parser safely.",
                "raw_model_response": "The change touches parsing and validation.",
                "raw_tool_output_excerpt": "{\"tool\":\"repo_search\",\"output\":\"parser evidence\"}",
            },
            "questions": {
                "model_route": {
                    "id": "model_route",
                    "type": "choice",
                    "instructions": "Choose an available model tier for the described task class.",
                    "criteria": {"fast": "fast", "smart": "smart", "generic": "generic"},
                },
            },
            "evidence_ids": ["ev-route"],
        },
    }

    result = app._review_laya_candidate_locally(request)

    assert result.decision == "smart"
    assert result.confidence == 0.82
    assert calls["kwargs"]["format"]["properties"]["decision"]["enum"] == [
        "fast", "smart", "generic", "abstain",
    ]
    assert "laya-decision-review-v1" in calls["args"][2]
    assert "Implement the parser safely." in calls["args"][1]
    assert "parser evidence" in calls["args"][1]


def test_app_local_model_reviewer_rejects_model_digest_change_during_review():
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {"reasoning": "qwen3.5:9b"}}
    digest_calls = 0

    def model_digest(_model):
        nonlocal digest_calls
        digest_calls += 1
        return "sha256:" + ("a" if digest_calls == 1 else "b") * 64

    app.runtime = SimpleNamespace(
        installed_models=lambda: ["qwen3.5:9b"],
        model_digest=model_digest,
        version=lambda: "0.17.7",
        is_online=lambda: True,
    )
    app.services = SimpleNamespace(_generate=lambda *_args, **_kwargs: {
        "success": True,
        "model": "qwen3.5:9b",
        "_lah_provider": "ollama",
        "execution_profile": {"device": "cuda:0"},
        "text": json.dumps({"decision": "artifact", "confidence": 0.91}),
    })
    request = {
        "candidate_id": "candidate-1",
        "task_id": "task-1",
        "candidate_sha256": "b" * 64,
        "candidate": {
            "category": "context_source",
            "options": ["indexed", "artifact"],
            "state": {"gap_code": "unresolved_evidence_gap"},
            "questions": {"context_source": {
                "id": "context_source",
                "type": "choice",
                "instructions": "Choose the next authorized context source or evidence action.",
                "criteria": {"indexed": "indexed", "artifact": "artifact"},
            }},
        },
    }

    with pytest.raises(RuntimeError, match="model identity changed during review"):
        app._review_laya_candidate_locally(request)


def test_app_local_model_reviewer_rejects_missing_exact_model_digest_before_generation():
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {"reasoning": "qwen3.5:9b"}}
    app.runtime = SimpleNamespace(
        model_digest=lambda _model: None,
        version=lambda: "0.17.7",
        is_online=lambda: True,
    )
    generated = False

    def generate(*_args, **_kwargs):
        nonlocal generated
        generated = True
        raise AssertionError("must reject an unverified model before generation")

    app.services = SimpleNamespace(_generate=generate)
    request = {
        "candidate_id": "candidate-1",
        "task_id": "task-1",
        "candidate_sha256": "b" * 64,
        "candidate": {
            "category": "context_source",
            "options": ["indexed"],
            "state": {"gap_code": "unresolved_evidence_gap"},
            "questions": {"context_source": {
                "id": "context_source",
                "type": "choice",
                "instructions": "Choose the next authorized context source or evidence action.",
                "criteria": {"indexed": "indexed"},
            }},
        },
    }

    with pytest.raises(RuntimeError, match="model identity"):
        app._review_laya_candidate_locally(request)
    assert generated is False


def test_app_local_model_reviewer_rejects_non_ollama_provider():
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {"reasoning": "qwen3.5:9b"}}
    app.runtime = SimpleNamespace(
        model_digest=lambda _model: "sha256:" + "a" * 64,
        version=lambda: "0.17.7",
        is_online=lambda: True,
    )
    app.services = SimpleNamespace(_generate=lambda *_args, **_kwargs: {
        "success": True,
        "model": "qwen3.5:9b",
        "_lah_provider": "openai",
        "text": json.dumps({"decision": "indexed", "confidence": 0.9}),
    })
    request = {
        "candidate_id": "candidate-1",
        "task_id": "task-1",
        "candidate_sha256": "b" * 64,
        "candidate": {
            "category": "context_source",
            "options": ["indexed"],
            "state": {"gap_code": "unresolved_evidence_gap"},
            "questions": {"context_source": {
                "id": "context_source",
                "type": "choice",
                "instructions": "Choose the next authorized context source or evidence action.",
                "criteria": {"indexed": "indexed"},
            }},
        },
    }

    with pytest.raises(RuntimeError, match="not local and pinned"):
        app._review_laya_candidate_locally(request)


def test_runtime_output_history_remains_readable_after_operator_label(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    store.record_completion_outcome({
        "task_id": "task-1",
        "session_id": "session-1",
        "outcome": {
            "status": "passed",
            "reason_code": "completion_gate_passed",
            "duration_ms": 12.5,
            "repository_revision": "a" * 40,
            "mutation_generation": 0,
        },
    }, root=str(repo), task_store=task_store)
    store.handle(
        {"action": "label", "candidate_id": captured["candidate_id"], "target": "fast"},
        root=str(repo),
        task_store=task_store,
    )

    history = store.handle(
        {"action": "runtime_output_history", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )

    assert history["success"] is True
    assert [event["event_type"] for event in history["events"]] == ["completion_outcome"]


def test_completion_outcome_can_be_recorded_after_operator_label(candidate_env):
    repo, _state, task_store, store = candidate_env
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    store.handle(
        {"action": "label", "candidate_id": captured["candidate_id"], "target": "fast"},
        root=str(repo),
        task_store=task_store,
    )

    result = store.record_completion_outcome({
        "task_id": "task-1",
        "session_id": "session-1",
        "outcome": {
            "status": "passed",
            "reason_code": "completion_gate_passed",
            "duration_ms": 12.5,
            "repository_revision": "a" * 40,
            "mutation_generation": 0,
        },
    }, root=str(repo), task_store=task_store)

    assert result["candidate_count"] == 1
    history = store.handle(
        {"action": "runtime_output_history", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )
    assert [event["event_type"] for event in history["events"]] == ["completion_outcome"]


def test_runtime_output_history_remains_readable_after_local_model_review(candidate_env):
    repo, state, task_store, _store = candidate_env
    store = LayaCandidateStore(
        state,
        local_model_reviewer=lambda _request: LocalModelReviewResult(
            decision="fast",
            confidence=0.9,
            provider="ollama",
            model_id="local-reviewer",
            model_revision="sha256:" + "a" * 64,
            runtime_version="test-runtime",
            device="cpu",
            is_local=True,
        ),
    )
    captured = store.handle(_capture(), root=str(repo), task_store=task_store)
    store.record_completion_outcome({
        "task_id": "task-1",
        "session_id": "session-1",
        "outcome": {
            "status": "passed",
            "reason_code": "completion_gate_passed",
            "duration_ms": 12.5,
            "repository_revision": "a" * 40,
            "mutation_generation": 0,
        },
    }, root=str(repo), task_store=task_store)
    store.handle(
        {"action": "model_review", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )

    history = store.handle(
        {"action": "runtime_output_history", "candidate_id": captured["candidate_id"]},
        root=str(repo),
        task_store=task_store,
    )

    assert history["success"] is True
    assert [event["event_type"] for event in history["events"]] == ["completion_outcome"]
