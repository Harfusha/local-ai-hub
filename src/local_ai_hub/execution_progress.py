"""Bounded advisory detection of repeated checkpoint patterns.

No checkpoint is proof of completed work. The trace records only hashes,
not free text or source, and cannot affect the canonical completion gate.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

PROGRESS_STATE_KEY = "_verified_execution_progress"
MAX_CHECKPOINT_SAMPLES = 8
WINDOW_SECONDS = 900


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode("ascii")).hexdigest()


def progress_epoch(task: Any) -> str:
    return _digest({
        "owner": task.owner,
        "revision": task.checkpoint.state_data.get("contract_revision", 1),
        "receipts": dict(task.verification_receipts),
    })


def _valid_trace(raw: Any, epoch: str, now: float) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping) or raw.get("epoch") != epoch:
        return []
    samples = raw.get("samples")
    if type(samples) is not list or len(samples) > MAX_CHECKPOINT_SAMPLES:
        return []
    result = []
    for sample in samples:
        if (type(sample) is not dict or set(sample) != {"digest", "time", "request"}
                or type(sample["digest"]) is not str or len(sample["digest"]) != 64
                or type(sample["request"]) is not str or len(sample["request"]) not in (0, 64)
                or type(sample["time"]) not in (int, float)):
            return []
        if now - WINDOW_SECONDS <= sample["time"] <= now:
            result.append(sample)
    return result


def observe_checkpoint(task: Any, checkpoint: Any, *, now: float,
                       idempotency_key: str = "") -> dict[str, Any]:
    epoch = progress_epoch(task)
    samples = _valid_trace(task.checkpoint.state_data.get(PROGRESS_STATE_KEY), epoch, now)
    request = _digest(idempotency_key) if idempotency_key else ""
    if request and any(sample["request"] == request for sample in samples):
        return {"epoch": epoch, "samples": samples}
    digest = _digest({
        "phase": checkpoint.phase,
        "next_action": checkpoint.next_action,
        "paths": sorted(set(checkpoint.affected_paths)),
        "blockers": sorted(set(checkpoint.blockers)),
        "evidence": sorted(set(checkpoint.evidence_ids)),
    })
    return {"epoch": epoch, "samples": [*samples, {"digest": digest, "time": now,
                                                  "request": request}][-MAX_CHECKPOINT_SAMPLES:]}


def repeated_checkpoint_count(task: Any, *, now: float) -> int:
    """Count repetitions of the latest pattern in the current evidence epoch."""
    samples = _valid_trace(task.checkpoint.state_data.get(PROGRESS_STATE_KEY),
                           progress_epoch(task), now)
    if not samples:
        return 0
    latest = samples[-1]["digest"]
    return sum(sample["digest"] == latest for sample in samples)
