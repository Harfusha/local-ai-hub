from __future__ import annotations

import json

import pytest

from tools.shadow_eval import (
    collect_shadow_observations,
    main,
    project_shadow_observation,
    score_shadow_annotations,
)


def _event(sequence: int, action: str, status: str, *, task_status: str = "active"):
    return {
        "stream_id": "task:task-1",
        "seq": sequence,
        "kind": "host.shadow.observation.v3",
        "payload": {
            "schema": "local-ai-hub.host-shadow-observation.v3",
            "event_id": f"{sequence:064x}",
            "event_type": "task.checkpointed",
            "observed_at": 1794325000.0 + sequence,
            "task_id": "task-1",
            "proposal": {
                "action": action,
                "reason_code": "no_actionable_signal" if status == "not_proposed" else "test_signal",
                "status": status,
            },
            "source_state": {
                "task_status": task_status,
                "has_blockers": action == "recommend_pause",
                "has_next_action": action == "recommend_continue",
            },
            "permission_check": {"status": "not_evaluated", "would_be_denied": None},
            "content_stored": False,
            "private_checkpoint_text": "must not be exported",
        },
    }


def test_projection_exports_only_allowlisted_shadow_metadata():
    projected = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(7, "none", "not_proposed")
    )

    assert projected["sequence"] == 7
    assert projected["proposal"]["status"] == "not_proposed"
    assert projected["source_state"] == {
        "task_status": "active",
        "has_blockers": False,
        "has_next_action": False,
    }
    assert "private_checkpoint_text" not in str(projected)


def test_projection_fails_closed_on_wrong_task_or_non_shadow_event():
    with pytest.raises(ValueError, match="task stream"):
        project_shadow_observation("task-2", "host.shadow.observation.v3", _event(1, "none", "not_proposed"))

    assert project_shadow_observation("task-1", "task.checkpointed", _event(1, "none", "not_proposed")) is None


def test_export_uses_exact_root_task_kind_filter_and_allowlisted_projection():
    calls = []

    class Client:
        def stream_events(self, **kwargs):
            calls.append(kwargs)
            return iter([("host.shadow.observation.v3", _event(4, "none", "not_proposed"))])

    exported = collect_shadow_observations(
        Client(), root="C:/repo", task_id="task-1", after_seq=3, timeout=1.0
    )

    assert calls == [{
        "stream_id": "task:task-1",
        "kind": "host.shadow.observation.v3",
        "after_seq": 3,
        "timeout": 1.0,
        "root": "C:/repo",
    }]
    assert len(exported) == 1
    assert "private_checkpoint_text" not in str(exported)


def test_export_refuses_stream_gaps_without_returning_partial_records():
    class Client:
        def stream_events(self, **_kwargs):
            return iter([
                ("host.shadow.observation.v3", _event(1, "none", "not_proposed")),
                ("retention_gap", {"from_seq": 2, "to_seq": 3}),
            ])

    with pytest.raises(ValueError, match="gap or error"):
        collect_shadow_observations(
            Client(), root="C:/repo", task_id="task-1", after_seq=0, timeout=1.0
        )


def test_scoring_uses_consensus_and_counts_proposal_and_missed_opportunity_errors():
    observations = [
        project_shadow_observation("task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")),
        project_shadow_observation("task-1", "host.shadow.observation.v3", _event(2, "none", "not_proposed")),
        project_shadow_observation("task-1", "host.shadow.observation.v3", _event(3, "recommend_continue", "proposed")),
    ]
    annotations = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 2, "expected_action": "recommend_continue", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:02:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 3, "expected_action": "none", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:03:00Z", "stage": "independent"},
    ]

    report = score_shadow_annotations(observations, annotations)

    assert report["quality_status"] == "not_verified"
    assert report["single_reviewer_cases"] == 2
    assert report["multi_reviewer_cases"] == 1
    assert report["unanimous_cases"] == 1
    assert report["exact_matches"] == 1
    assert report["unresolved_disagreements"] == 0
    assert report["by_action"]["recommend_pause"] == {"true_positive": 1, "false_positive": 0, "false_negative": 0, "precision": 1.0, "recall": 1.0}
    assert report["by_action"]["recommend_continue"] == {"true_positive": 0, "false_positive": 1, "false_negative": 1, "precision": 0.0, "recall": 0.0}


def test_scoring_rejects_orphan_annotations_and_duplicate_reviewer_rows():
    observations = [project_shadow_observation("task-1", "host.shadow.observation.v3", _event(1, "none", "not_proposed"))]
    row = {"task_id": "task-1", "sequence": 2, "expected_action": "none", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"}
    with pytest.raises(ValueError, match="unknown observation"):
        score_shadow_annotations(observations, [row])

    duplicate = {**row, "sequence": 1}
    with pytest.raises(ValueError, match="duplicate annotation"):
        score_shadow_annotations(observations, [duplicate, duplicate])


def test_scoring_excludes_unresolved_multi_reviewer_cases():
    observation = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")
    )
    annotations = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
    ]

    report = score_shadow_annotations([observation], annotations)

    assert report["multi_reviewer_cases"] == 1
    assert report["unanimous_cases"] == 0
    assert report["unresolved_disagreements"] == 1
    assert report["evaluated_cases"] == 0


def test_scoring_uses_explicit_adjudication_for_independent_disagreement():
    observation = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")
    )
    annotations = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_continue", "reviewer_ref": "a1", "reviewed_at": "2026-11-10T12:02:00Z", "stage": "adjudication"},
    ]

    report = score_shadow_annotations([observation], annotations)

    assert report["adjudicated_cases"] == 1
    assert report["unresolved_disagreements"] == 0
    assert report["evaluated_cases"] == 1
    assert report["by_action"]["recommend_pause"]["false_positive"] == 1
    assert report["by_action"]["recommend_continue"]["false_negative"] == 1
    assert report["exact_matches"] == 0


def test_scoring_requires_adjudication_to_follow_independent_disagreement():
    observation = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")
    )
    single_and_adjudicated = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "a1", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "adjudication"},
    ]
    unanimous_and_adjudicated = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "a1", "reviewed_at": "2026-11-10T12:02:00Z", "stage": "adjudication"},
    ]

    with pytest.raises(ValueError, match="at least two independent reviewers"):
        score_shadow_annotations([observation], single_and_adjudicated)
    with pytest.raises(ValueError, match="independent disagreement"):
        score_shadow_annotations([observation], unanimous_and_adjudicated)


def test_scoring_rejects_invalid_or_duplicate_adjudication_rows():
    observation = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")
    )
    independent = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
    ]
    invalid_stage = {**independent[0], "stage": []}
    duplicate_adjudication = [
        *independent,
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "a1", "reviewed_at": "2026-11-10T12:02:00Z", "stage": "adjudication"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "a2", "reviewed_at": "2026-11-10T12:03:00Z", "stage": "adjudication"},
    ]

    with pytest.raises(ValueError, match="invalid annotation stage"):
        score_shadow_annotations([observation], [invalid_stage])
    with pytest.raises(ValueError, match="duplicate adjudication"):
        score_shadow_annotations([observation], duplicate_adjudication)


def test_double_review_gate_rejects_single_reviewers_and_unadjudicated_disagreements():
    observation = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")
    )
    single_review = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
    ]
    disagreement = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
    ]

    with pytest.raises(ValueError, match="two independent reviewers"):
        score_shadow_annotations([observation], single_review, require_double_review=True)
    with pytest.raises(ValueError, match="requires adjudication"):
        score_shadow_annotations([observation], disagreement, require_double_review=True)


def test_score_cli_reads_adjudication_jsonl_and_keeps_quality_unverified(tmp_path, capsys):
    observation = project_shadow_observation(
        "task-1", "host.shadow.observation.v3", _event(1, "recommend_pause", "proposed")
    )
    annotations = [
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_pause", "reviewer_ref": "r1", "reviewed_at": "2026-11-10T12:00:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "none", "reviewer_ref": "r2", "reviewed_at": "2026-11-10T12:01:00Z", "stage": "independent"},
        {"task_id": "task-1", "sequence": 1, "expected_action": "recommend_continue", "reviewer_ref": "a1", "reviewed_at": "2026-11-10T12:02:00Z", "stage": "adjudication"},
    ]
    observations_path = tmp_path / "observations.jsonl"
    annotations_path = tmp_path / "annotations.jsonl"
    observations_path.write_text(json.dumps(observation) + "\n", encoding="utf-8")
    annotations_path.write_text(
        "".join(json.dumps(row) + "\n" for row in annotations), encoding="utf-8"
    )

    exit_code = main([
        "score",
        "--observations", str(observations_path),
        "--annotations", str(annotations_path),
        "--require-double-review",
    ])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["adjudicated_cases"] == 1
    assert report["unresolved_disagreements"] == 0
    assert report["double_review_gate"] == "passed"
    assert report["reviewer_identity_status"] == "not_verified"
    assert report["quality_status"] == "not_verified"
