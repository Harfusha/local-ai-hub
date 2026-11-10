"""Export and score metadata-only Agent OS shadow observations.

The exporter uses the existing root/task-bound event stream and never starts
the Hub. Scoring is offline and does not invoke any model.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

SHADOW_KIND = "host.shadow.observation.v3"
SHADOW_SCHEMA = "local-ai-hub.host-shadow-observation.v3"
EXPORT_SCHEMA = "local-ai-hub.shadow-evaluation-observation.v1"
EXPECTED_ACTIONS = {"recommend_pause", "recommend_continue", "none", "unclear"}
TASK_STATUSES = {
    "draft", "planned", "active", "verifying", "completed",
    "waiting", "blocked", "failed", "cancelled", "abandoned",
}
MAX_STREAM_EVENTS = 10_000
MAX_JSONL_RECORDS = 100_000
MAX_JSONL_LINE_BYTES = 64 * 1024


def project_shadow_observation(
    task_id: str,
    event_kind: str,
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate one SSE event and return only allowlisted evaluation metadata."""
    if event_kind in {"stream.gap", "retention_gap", "error"}:
        raise ValueError(f"event stream has a gap or error: {event_kind}")
    if event_kind != SHADOW_KIND:
        return None
    if not isinstance(event, dict):
        raise ValueError("shadow event must be an object")
    if event.get("stream_id") != f"task:{task_id}":
        raise ValueError("shadow event is outside the requested task stream")
    if event.get("kind") != SHADOW_KIND:
        raise ValueError("shadow event kind mismatch")
    sequence = event.get("seq")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("invalid shadow event sequence")

    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("schema") != SHADOW_SCHEMA:
        raise ValueError("unsupported shadow event schema")
    if payload.get("task_id") != task_id or payload.get("content_stored") is not False:
        raise ValueError("shadow event task or privacy contract mismatch")
    event_id = payload.get("event_id")
    if not isinstance(event_id, str) or not re.fullmatch(r"[a-f0-9]{64}", event_id):
        raise ValueError("invalid shadow observation id")
    observed_at = payload.get("observed_at")
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)) or not math.isfinite(observed_at):
        raise ValueError("invalid shadow observation time")
    event_type = payload.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("invalid shadow event type")

    proposal = payload.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("missing shadow proposal state")
    proposal_action = proposal.get("action")
    proposal_status = proposal.get("status")
    reason_code = proposal.get("reason_code")
    if proposal_status == "proposed":
        if proposal_action not in {"recommend_pause", "recommend_continue"}:
            raise ValueError("invalid proposed action")
    elif proposal_status == "not_proposed":
        if proposal_action != "none":
            raise ValueError("invalid no-proposal action")
    else:
        raise ValueError("invalid proposal status")
    if not isinstance(reason_code, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", reason_code):
        raise ValueError("invalid proposal reason code")

    source_state = payload.get("source_state")
    if not isinstance(source_state, dict):
        raise ValueError("missing task signal metadata")
    status = source_state.get("task_status")
    has_blockers = source_state.get("has_blockers")
    has_next_action = source_state.get("has_next_action")
    if status not in TASK_STATUSES or type(has_blockers) is not bool or type(has_next_action) is not bool:
        raise ValueError("invalid task signal metadata")

    permission_check = payload.get("permission_check")
    if not isinstance(permission_check, dict) or permission_check != {
        "status": "not_evaluated",
        "would_be_denied": None,
    }:
        raise ValueError("unexpected permission check in client-neutral task observation")

    return {
        "schema": EXPORT_SCHEMA,
        "task_id": task_id,
        "sequence": sequence,
        "observation_id": event_id,
        "observed_at": float(observed_at),
        "event_type": event_type,
        "proposal": {
            "action": proposal_action,
            "status": proposal_status,
            "reason_code": reason_code,
        },
        "source_state": {
            "task_status": status,
            "has_blockers": has_blockers,
            "has_next_action": has_next_action,
        },
    }


def collect_shadow_observations(
    client: Any,
    *,
    root: str,
    task_id: str,
    after_seq: int,
    timeout: float,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    stream_id = f"task:{task_id}"
    for event_kind, event in client.stream_events(
        stream_id=stream_id,
        kind=SHADOW_KIND,
        after_seq=after_seq,
        timeout=timeout,
        root=root,
    ):
        projected = project_shadow_observation(task_id, event_kind, event)
        if projected is None:
            continue
        sequence = projected["sequence"]
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        observations.append(projected)
        if len(observations) > MAX_STREAM_EVENTS:
            raise ValueError("shadow export exceeded the bounded event count")
    observations.sort(key=lambda item: item["sequence"])
    return observations


def _validate_exported_observation(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("schema") != EXPORT_SCHEMA:
        raise ValueError("unsupported exported observation schema")
    task_id = row.get("task_id")
    sequence = row.get("sequence")
    if not isinstance(task_id, str) or not task_id or type(sequence) is not int or sequence < 1:
        raise ValueError("invalid exported observation identity")
    if not isinstance(row.get("observation_id"), str) or not re.fullmatch(r"[a-f0-9]{64}", row["observation_id"]):
        raise ValueError("invalid exported observation id")
    proposal = row.get("proposal")
    source_state = row.get("source_state")
    if not isinstance(proposal, dict) or proposal.get("status") not in {"proposed", "not_proposed"}:
        raise ValueError("invalid exported proposal")
    if proposal.get("action") not in {"recommend_pause", "recommend_continue", "none"}:
        raise ValueError("invalid exported proposal action")
    if (proposal["status"] == "not_proposed") != (proposal["action"] == "none"):
        raise ValueError("exported proposal status and action disagree")
    if not isinstance(source_state, dict) or source_state.get("task_status") not in TASK_STATUSES:
        raise ValueError("invalid exported source state")
    if type(source_state.get("has_blockers")) is not bool or type(source_state.get("has_next_action")) is not bool:
        raise ValueError("invalid exported source signals")
    return row


def _validate_annotation(row: Any) -> dict[str, Any]:
    required = {"task_id", "sequence", "expected_action", "reviewer_ref", "reviewed_at", "stage"}
    if not isinstance(row, dict) or set(row) != required:
        raise ValueError("annotation must contain exactly the six documented fields")
    if not isinstance(row["task_id"], str) or not row["task_id"]:
        raise ValueError("invalid annotation task_id")
    if type(row["sequence"]) is not int or row["sequence"] < 1:
        raise ValueError("invalid annotation sequence")
    if not isinstance(row["expected_action"], str) or row["expected_action"] not in EXPECTED_ACTIONS:
        raise ValueError("invalid expected_action")
    if not isinstance(row["stage"], str) or row["stage"] not in {"independent", "adjudication"}:
        raise ValueError("invalid annotation stage")
    reviewer_ref = row["reviewer_ref"]
    if not isinstance(reviewer_ref, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", reviewer_ref):
        raise ValueError("invalid pseudonymous reviewer_ref")
    reviewed_at = row["reviewed_at"]
    if not isinstance(reviewed_at, str):
        raise ValueError("reviewed_at must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reviewed_at must be a timezone-aware ISO timestamp")
    return row


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_shadow_annotations(
    observations: Iterable[dict[str, Any]],
    annotations: Iterable[dict[str, Any]],
    *,
    require_double_review: bool = False,
) -> dict[str, Any]:
    if type(require_double_review) is not bool:
        raise ValueError("require_double_review must be a boolean")
    observation_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for raw in observations:
        row = _validate_exported_observation(raw)
        key = (row["task_id"], row["sequence"])
        if key in observation_by_key:
            raise ValueError("duplicate exported observation")
        observation_by_key[key] = row

    labels_by_key: dict[tuple[str, int], list[str]] = defaultdict(list)
    adjudications_by_key: dict[tuple[str, int], str] = {}
    seen_annotations: set[tuple[str, int, str]] = set()
    for raw in annotations:
        row = _validate_annotation(raw)
        key = (row["task_id"], row["sequence"])
        if key not in observation_by_key:
            raise ValueError("annotation references an unknown observation")
        reviewer_key = (*key, row["reviewer_ref"])
        if reviewer_key in seen_annotations:
            raise ValueError("duplicate annotation for reviewer and observation")
        seen_annotations.add(reviewer_key)
        if row["stage"] == "independent":
            labels_by_key[key].append(row["expected_action"])
        elif key in adjudications_by_key:
            raise ValueError("duplicate adjudication for observation")
        else:
            adjudications_by_key[key] = row["expected_action"]

    for key, adjudicated_action in adjudications_by_key.items():
        independent_labels = labels_by_key.get(key, [])
        if len(independent_labels) < 2:
            raise ValueError("adjudication requires at least two independent reviewers")
        if len(set(independent_labels)) < 2:
            raise ValueError("adjudication requires an independent disagreement")

    if require_double_review:
        if not observation_by_key:
            raise ValueError("double-review gate requires observations")
        for key in observation_by_key:
            independent_labels = labels_by_key.get(key, [])
            if len(independent_labels) < 2:
                raise ValueError("double-review gate requires two independent reviewers for every observation")
            if len(set(independent_labels)) > 1 and key not in adjudications_by_key:
                raise ValueError("double-review gate requires adjudication for every disagreement")

    confusion = {
        action: {"true_positive": 0, "false_positive": 0, "false_negative": 0}
        for action in ("recommend_pause", "recommend_continue")
    }
    single_reviewer_cases = 0
    multi_reviewer_cases = 0
    unanimous_cases = 0
    unresolved_disagreements = 0
    adjudicated_cases = 0
    unclear_cases = 0
    evaluated_cases = 0
    exact_matches = 0
    abstained_proposals = 0
    for key, labels in labels_by_key.items():
        expected_values = set(labels)
        if len(labels) == 1:
            single_reviewer_cases += 1
        else:
            multi_reviewer_cases += 1
            if len(expected_values) == 1:
                unanimous_cases += 1
        if len(expected_values) != 1:
            if key not in adjudications_by_key:
                unresolved_disagreements += 1
                continue
            expected_action = adjudications_by_key[key]
            adjudicated_cases += 1
        else:
            expected_action = labels[0]
        if expected_action == "unclear":
            unclear_cases += 1
            continue
        evaluated_cases += 1
        observation = observation_by_key[key]
        proposal = observation["proposal"]["action"]
        if proposal == "none":
            abstained_proposals += 1
        if proposal == expected_action:
            exact_matches += 1
        for action, counts in confusion.items():
            predicted_positive = proposal == action
            expected_positive = expected_action == action
            if predicted_positive and expected_positive:
                counts["true_positive"] += 1
            elif predicted_positive:
                counts["false_positive"] += 1
            elif expected_positive:
                counts["false_negative"] += 1

    by_action: dict[str, dict[str, int | float | None]] = {}
    for action, counts in confusion.items():
        by_action[action] = {
            **counts,
            "precision": _ratio(counts["true_positive"], counts["true_positive"] + counts["false_positive"]),
            "recall": _ratio(counts["true_positive"], counts["true_positive"] + counts["false_negative"]),
        }
    annotated_observations = len(labels_by_key)
    return {
        "quality_status": "not_verified",
        "double_review_gate": "passed" if require_double_review else "not_requested",
        "reviewer_identity_status": "not_verified",
        "observation_count": len(observation_by_key),
        "annotated_observations": annotated_observations,
        "unannotated_observations": len(observation_by_key) - annotated_observations,
        "single_reviewer_cases": single_reviewer_cases,
        "multi_reviewer_cases": multi_reviewer_cases,
        "unanimous_cases": unanimous_cases,
        "unresolved_disagreements": unresolved_disagreements,
        "adjudicated_cases": adjudicated_cases,
        "unclear_cases": unclear_cases,
        "evaluated_cases": evaluated_cases,
        "exact_matches": exact_matches,
        "exact_match_rate": _ratio(exact_matches, evaluated_cases),
        "abstained_proposals": abstained_proposals,
        "abstention_rate": _ratio(abstained_proposals, evaluated_cases),
        "by_action": by_action,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
                raise ValueError(f"{path}:{line_number}: line exceeds size limit")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
            if len(rows) > MAX_JSONL_RECORDS:
                raise ValueError(f"{path}: record count exceeds size limit")
    return rows


def _export(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("--root must be an existing absolute repository directory")
    if not args.task_id or "/" in args.task_id or "\\" in args.task_id:
        raise ValueError("--task-id must be a single task identifier")
    if type(args.after_seq) is not int or args.after_seq < 0:
        raise ValueError("--after-seq must be a non-negative integer")
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
        raise ValueError("--timeout must be greater than zero and at most 60 seconds")

    from local_ai_hub.client import HubClient

    client = HubClient(config_path=args.config, auto_start=False)
    try:
        observations = collect_shadow_observations(
            client,
            root=str(root.resolve()),
            task_id=args.task_id,
            after_seq=args.after_seq,
            timeout=args.timeout,
        )
    finally:
        client.close()
    for row in observations:
        sys.stdout.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    return 0


def _score(args: argparse.Namespace) -> int:
    report = score_shadow_annotations(
        _read_jsonl(args.observations),
        _read_jsonl(args.annotations),
        require_double_review=args.require_double_review,
    )
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export and score metadata-only Agent OS shadow observations.")
    commands = parser.add_subparsers(dest="command", required=True)
    export_parser = commands.add_parser("export", help="Export one root/task-bound shadow event stream as JSONL.")
    export_parser.add_argument("--root", required=True)
    export_parser.add_argument("--task-id", required=True)
    export_parser.add_argument("--config")
    export_parser.add_argument("--after-seq", type=int, default=0)
    export_parser.add_argument("--timeout", type=float, default=1.0)
    export_parser.set_defaults(run=_export)
    score_parser = commands.add_parser("score", help="Validate annotations and print offline metrics as JSON.")
    score_parser.add_argument("--observations", required=True, type=Path)
    score_parser.add_argument("--annotations", required=True, type=Path)
    score_parser.add_argument(
        "--require-double-review",
        action="store_true",
        help="Require two independent reviewers for every observation and adjudication for each disagreement.",
    )
    score_parser.set_defaults(run=_score)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Exception as exc:
        sys.stderr.write(f"shadow-eval: {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
