from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_task_models import (
    MAX_TRAINING_DATASET_BYTES,
    TaskStatus,
    _canonical_repository_root,
    _task_matches_scope,
)
from .json_utils import dumps as json_dumps


TaskStore = None


class TaskTrainingMixin:
    def curate_training_dataset(
        self,
        output_path: str,
        min_receipts: int = 1,
        format: str = "jsonl",
        *,
        repo_root: str | Path | None = None,
        task_id: str | None = None,
        include_laya_candidates: bool = False,
        candidate_file_path: str | None = None,
    ) -> dict[str, Any]:
        """Export completed, verified tasks; Laya candidates use their state_dir store."""
        if include_laya_candidates or candidate_file_path is not None:
            raise ValueError("repo-root Laya JSONL import is retired; use the state_dir candidate lifecycle")
        if task_id is not None and (not isinstance(task_id, str) or not task_id or task_id != task_id.strip() or "\x00" in task_id):
            raise ValueError("task_id must be a nonempty canonical string when supplied")
        if not isinstance(format, str) or format not in {"json", "jsonl"}:
            raise ValueError("format must be json or jsonl")
        scoped_root = Path(_canonical_repository_root(repo_root))
        if type(include_laya_candidates) is not bool:
            raise ValueError("include_laya_candidates must be a boolean")
        if candidate_file_path is not None and (
            type(candidate_file_path) is not str or "\x00" in candidate_file_path
        ):
            raise ValueError("candidate_file_path must be a string path")
        if candidate_file_path is not None and not include_laya_candidates:
            raise ValueError("candidate_file_path requires explicit opt-in")
        if include_laya_candidates:
            from .laya_decisions import DecisionCategory, allowed_decision_options

            if candidate_file_path is None or not candidate_file_path.strip():
                raise ValueError("candidate_file_path is required for explicit opt-in")
            if format != "jsonl":
                raise ValueError("Laya candidate export supports jsonl only")
            source_requested = Path(candidate_file_path).expanduser()
            if not source_requested.is_absolute():
                source_requested = scoped_root / source_requested
            source_file = source_requested.resolve(strict=True)
            if not source_file.is_relative_to(scoped_root):
                raise ValueError("candidate_file_path must remain inside repo_root")
            requested_output = Path(str(output_path or "")).expanduser()
            if not str(output_path or "").strip():
                raise ValueError("output_path is required")
            if not requested_output.is_absolute():
                requested_output = scoped_root / requested_output
            out_file = requested_output.resolve(strict=False)
            if out_file == scoped_root or not out_file.is_relative_to(scoped_root):
                raise ValueError("output_path must remain inside repo_root")
            if source_file == out_file:
                raise ValueError("candidate input and output paths must differ")
            raw_candidates = source_file.read_bytes()
            if len(raw_candidates) > MAX_TRAINING_DATASET_BYTES:
                raise ValueError(f"candidate file exceeds {MAX_TRAINING_DATASET_BYTES} byte limit")
            known_tasks = {
                item.task_id
                for item in self.list_tasks(limit=5000).tasks
                if _task_matches_scope(item, str(scoped_root), None)
            }
            candidate_rows: list[dict[str, Any]] = []
            seen_candidate_ids: set[str] = set()
            expected_fields = {
                "candidate_id", "task_id", "category", "input_text",
                "annotations", "label_provenance",
            }
            for line_number, raw_line in enumerate(raw_candidates.splitlines(), start=1):
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ValueError(f"invalid candidate JSONL at line {line_number}") from exc
                if type(row) is not dict or set(row) != expected_fields:
                    raise ValueError(f"candidate schema invalid at line {line_number}")
                strings = ("candidate_id", "task_id", "category", "input_text")
                if any(type(row[name]) is not str or not row[name].strip() or "\x00" in row[name] for name in strings):
                    raise ValueError(f"candidate schema invalid at line {line_number}")
                if len(row["candidate_id"]) > 128 or len(row["category"]) > 64 or len(row["input_text"]) > 4096:
                    raise ValueError(f"candidate field exceeds limit at line {line_number}")
                if row["category"].strip() != row["category"] or not row["category"].isascii() or not all(
                    char.isalnum() or char in "._-" for char in row["category"]
                ):
                    raise ValueError(f"candidate category invalid at line {line_number}")
                try:
                    decision_category = DecisionCategory(row["category"])
                    category_options = allowed_decision_options(decision_category)
                except ValueError as exc:
                    raise ValueError(f"candidate category or label invalid at line {line_number}") from exc
                if row["task_id"].strip() != row["task_id"] or row["task_id"] not in known_tasks:
                    raise ValueError(f"candidate task is outside repo_root at line {line_number}")
                if row["candidate_id"] in seen_candidate_ids:
                    raise ValueError(f"duplicate candidate_id at line {line_number}")
                seen_candidate_ids.add(row["candidate_id"])
                annotations = row["annotations"]
                provenance = row["label_provenance"]
                if type(annotations) is not dict or set(annotations) != {"annotator_a", "annotator_b", "adjudicated"}:
                    raise ValueError(f"candidate annotation schema invalid at line {line_number}")
                if type(provenance) is not dict or set(provenance) != {"annotator_a", "annotator_b", "adjudicator"}:
                    raise ValueError(f"candidate provenance schema invalid at line {line_number}")
                if any(value not in category_options for value in annotations.values() if type(value) is str):
                    raise ValueError(f"candidate category or label invalid at line {line_number}")
                for values in (annotations, provenance):
                    if any(type(value) is not str or not value.strip() or len(value) > 256 or "\x00" in value for value in values.values()):
                        raise ValueError(f"candidate labels and provenance must be bounded strings at line {line_number}")
                candidate_rows.append({
                    "candidate_id": row["candidate_id"],
                    "task_id": row["task_id"],
                    "group_id": row["task_id"],
                    "category": row["category"],
                    "input_text": row["input_text"],
                    "annotations": annotations,
                    "label_provenance": provenance,
                    "label_status": "caller_attested",
                })
            payload = "".join(json_dumps(item, ensure_ascii=False) + "\n" for item in candidate_rows)
            if len(payload.encode("utf-8")) > MAX_TRAINING_DATASET_BYTES:
                raise ValueError(f"training dataset exceeds {MAX_TRAINING_DATASET_BYTES} byte limit")
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file = out_file.resolve(strict=False)
            if not out_file.is_relative_to(scoped_root) or out_file == source_file:
                raise ValueError("output_path must remain inside repo_root and differ from candidate input")
            out_file.write_text(payload, encoding="utf-8")
            return {
                "success": True,
                "count": len(candidate_rows),
                "dataset_count": len(candidate_rows),
                "output_path": str(out_file),
                "format": "jsonl",
                "dataset_kind": "laya_candidates",
            }
        tasks = [
            task for task in self.list_tasks(status=TaskStatus.COMPLETED, limit=5000).tasks
            if _task_matches_scope(task, str(scoped_root), task_id)
        ]
        samples: list[dict[str, Any]] = []
        estimated_bytes = 0

        for t in tasks:
            if len(t.verification_receipts) < min_receipts:
                continue
            criteria_str = "\n".join(f"- {c}" for c in t.contract.acceptance_criteria) if t.contract.acceptance_criteria else "All tests pass"
            constraints_str = "\n".join(f"- {c}" for c in t.contract.constraints) if t.contract.constraints else "None"
            affected = ", ".join(t.checkpoint.affected_paths) if t.checkpoint.affected_paths else "repository"
            next_act = t.checkpoint.next_action or "Task completed and verified"
            receipts_list = list(t.verification_receipts.keys())

            instruction = f"Implement engineering task: {t.contract.goal}"
            input_text = f"Acceptance criteria:\n{criteria_str}\n\nConstraints:\n{constraints_str}"
            output_text = f"Action taken:\nModified {affected}.\nVerification receipts validated: {', '.join(receipts_list)}.\nOutcome: {next_act}"

            sample = {
                "instruction": instruction,
                "prompt": instruction,
                "input": input_text,
                "output": output_text,
                "task_id": t.task_id,
                "created_at": t.created_at,
                "status": t.status.value,
            }
            estimated_bytes += len(json_dumps(sample, ensure_ascii=False).encode("utf-8")) + 1
            if estimated_bytes > MAX_TRAINING_DATASET_BYTES:
                raise ValueError(
                    f"training dataset exceeds {MAX_TRAINING_DATASET_BYTES} byte limit"
                )
            samples.append(sample)

        requested_output = Path(str(output_path or "")).expanduser()
        if not str(output_path or "").strip():
            raise ValueError("output_path is required")
        if not requested_output.is_absolute():
            requested_output = scoped_root / requested_output
        out_file = requested_output.resolve(strict=False)
        if out_file == scoped_root or not out_file.is_relative_to(scoped_root):
            raise ValueError("output_path must remain inside repo_root")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file = out_file.resolve(strict=False)
        if out_file == scoped_root or not out_file.is_relative_to(scoped_root):
            raise ValueError("output_path must remain inside repo_root")

        if format == "json":
            payload = json_dumps(samples, indent=2, ensure_ascii=False)
        else:
            payload = "".join(json_dumps(item, ensure_ascii=False) + "\n" for item in samples)
        if len(payload.encode("utf-8")) > MAX_TRAINING_DATASET_BYTES:
            raise ValueError(f"training dataset exceeds {MAX_TRAINING_DATASET_BYTES} byte limit")
        out_file.write_text(payload, encoding="utf-8")

        return {
            "success": True,
            "count": len(samples),
            "dataset_count": len(samples),
            "output_path": str(out_file),
            "format": format,
        }

