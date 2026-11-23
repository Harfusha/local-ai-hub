"""Continuous Active Learning Daemon for Self-Sustaining Dataset Growth.

Captures real-world development events (verification outcomes, grounding corrections,
and code edits) into an append-only inbox. Automatically extracts and curates
training samples to expand the fine-tuning gold dataset without manual intervention.
"""

from __future__ import annotations

import json
import logging
# import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveLearningSample:
    """One captured real-world development interaction for continuous learning."""

    sample_id: str
    root: str
    file_path: str
    feedback_type: str  # "test_success", "grounding_correction", "diff_update"
    prompt_context: str
    target_card: Mapping[str, Any]
    source_sha256: str
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["target_card"] = dict(self.target_card)
        return d


class ActiveLearningInbox:
    """Thread-safe persistent collector for continuous active learning data."""

    def __init__(self, inbox_path: str | Path | None = None) -> None:
        self.inbox_path = Path(inbox_path or "state/active_learning_inbox.jsonl")
        self._lock = threading.Lock()

    def record_sample(
        self,
        root: str,
        file_path: str,
        feedback_type: str,
        prompt_context: str,
        target_card: Mapping[str, Any],
        source_sha256: str,
    ) -> ActiveLearningSample:
        """Capture one interaction into the active learning inbox."""
        import hashlib
        sid_raw = f"{file_path}:{source_sha256}:{time.time()}"
        sid = hashlib.sha256(sid_raw.encode("utf-8")).hexdigest()[:16]

        sample = ActiveLearningSample(
            sample_id=sid,
            root=root,
            file_path=str(file_path),
            feedback_type=feedback_type,
            prompt_context=prompt_context[:4000],
            target_card=target_card,
            source_sha256=source_sha256,
            timestamp=time.time(),
        )

        try:
            self.inbox_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, open(self.inbox_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(sample.to_dict()) + "\n")
        except Exception as exc:
            logger.warning("Failed to record active learning sample: %s", exc)

        return sample

    def count_samples(self) -> int:
        """Count total accumulated samples in the inbox."""
        if not self.inbox_path.exists():
            return 0
        with self._lock, open(self.inbox_path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    def curate_batch(self, min_samples: int = 10) -> list[dict[str, Any]]:
        """Extract and format accumulated samples into chat instruction format."""
        if not self.inbox_path.exists():
            return []

        curated: list[dict[str, Any]] = []
        with self._lock, open(self.inbox_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    s = json.loads(line)
                    curated.append({
                        "id": s["sample_id"],
                        "messages": [
                            {"role": "system", "content": "Complete the file card using CURRENT SOURCE as authority and DETERMINISTIC BASELINE as starting facts."},
                            {"role": "user", "content": s["prompt_context"]},
                            {"role": "assistant", "content": json.dumps(s["target_card"], ensure_ascii=False)},
                        ],
                    })
                except Exception:
                    continue

        return curated
