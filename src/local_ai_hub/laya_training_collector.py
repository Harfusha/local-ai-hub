"""Laya Universal Telemetry & Self-Supervised Training Collector.

Continuously captures real-world interaction signals and downstream verification
receipts into structured datasets for model fine-tuning and alignment:
1. Laya Classification & Routing Dataset:
   {state, questions, expected, gold} compatible with upstream ModernBERT fine-tuning.
2. Direct Preference Optimization (DPO) Dataset:
   {prompt, chosen, rejected, metadata} for Qwen 1.5B/3B/7B alignment.
3. Reranker & Embeddings Code Triplets:
   {query, positive, negative, metadata} for BGE / Cross-Encoder fine-tuning.

Ensures thread-safe append-only persistence, deduplication, and zero I/O blocking.
"""

from __future__ import annotations

from collections import deque
import hashlib
import json
import logging
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"bearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"gho_[A-Za-z0-9]{30,}"),
    re.compile(r"password\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
]


def _redact_sensitive(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    res = text
    for pat in _SENSITIVE_PATTERNS:
        res = pat.sub("[REDACTED_SECRET]", res)
    return res


def _determine_split(key: str) -> str:
    val = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 10
    if val == 9:
        return "test"
    if val == 8:
        return "val"
    return "train"


@dataclass(frozen=True)
class LayaTrainingSample:
    sample_id: str
    category: str
    state: dict[str, Any]
    questions: dict[str, str]
    expected: str
    gold: dict[str, float]
    label_source: str = "verified_receipt"
    prediction: str | None = None
    observed_outcome: str | None = None
    verification_receipt: dict[str, Any] | None = None
    human_label: str | None = None
    teacher_model: str | None = None
    split: str = "train"
    schema_version: int = 2
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DPOPairSample:
    pair_id: str
    category: str
    prompt: str
    chosen: str
    rejected: str
    verification_passed: bool
    metadata: dict[str, Any]
    split: str = "train"
    schema_version: int = 2
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalTripletSample:
    triplet_id: str
    query: str
    positive: str
    negative: str
    metadata: dict[str, Any]
    split: str = "train"
    schema_version: int = 2
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LayaTrainingCollector:
    """Universal persistent collector for continuous self-improving dataset generation.

    Uses an asynchronous non-blocking memory queue with background batch writing
    and a bounded LRU ring buffer for deduplication to ensure zero request-thread latency.
    """

    def __init__(
        self,
        laya_inbox_path: str | Path | None = None,
        dpo_inbox_path: str | Path | None = None,
        triplet_inbox_path: str | Path | None = None,
        enabled: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self.laya_inbox = Path(laya_inbox_path or "state/laya_training_inbox.jsonl")
        self.dpo_inbox = Path(dpo_inbox_path or "state/dpo_training_inbox.jsonl")
        self.triplet_inbox = Path(triplet_inbox_path or "state/retrieval_triplets.jsonl")
        self._lock = threading.Lock()
        self._laya_count = 0
        self._dpo_count = 0
        self._triplet_count = 0

        # Bounded LRU ring buffer for deduplication (O(1) lookup, fixed memory footprint)
        self._seen_hashes_queue: deque[str] = deque(maxlen=20000)
        self._seen_hashes_set: set[str] = set()

        # Asynchronous non-blocking queue & background worker
        self._queue: queue.Queue[tuple[Path, dict[str, Any]] | None] = queue.Queue(maxsize=10000)
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

        if self.enabled:
            self._ensure_dirs()
            self._worker_thread = threading.Thread(
                target=self._worker_loop, name="laya-collector-writer", daemon=True
            )
            self._worker_thread.start()

    def _ensure_dirs(self) -> None:
        """Create storage directories if they do not exist."""
        if not self.enabled:
            return
        try:
            self.laya_inbox.parent.mkdir(parents=True, exist_ok=True)
            self.dpo_inbox.parent.mkdir(parents=True, exist_ok=True)
            self.triplet_inbox.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.debug("Failed ensuring directories for training collector: %s", exc)

    def _is_and_mark_seen(self, h: str) -> bool:
        """Check if hash was already recorded and register it in bounded LRU buffer."""
        with self._lock:
            if h in self._seen_hashes_set:
                return True
            if len(self._seen_hashes_queue) == self._seen_hashes_queue.maxlen:
                oldest = self._seen_hashes_queue.popleft()
                self._seen_hashes_set.discard(oldest)
            self._seen_hashes_queue.append(h)
            self._seen_hashes_set.add(h)
            return False

    def record_laya_decision(
        self,
        category: str,
        state: Mapping[str, Any],
        question_text: str,
        expected_choice: str,
        confidence_distribution: Mapping[str, float] | None = None,
        *,
        label_source: str | None = None,
        prediction: str | None = None,
        observed_outcome: str | None = None,
        verification_receipt: Mapping[str, Any] | None = None,
        human_label: str | None = None,
        teacher_model: str | None = None,
        split: str | None = None,
    ) -> LayaTrainingSample | None:
        """Record one typed routing/context decision for Laya ModernBERT fine-tuning."""
        if not self.enabled:
            return None

        clean_question = _redact_sensitive(question_text)
        state_dict = {
            k: _redact_sensitive(v) if isinstance(v, str) else v
            for k, v in state.items()
        }
        receipt_dict = dict(verification_receipt) if verification_receipt is not None else None

        # Determine effective split (deterministic across repos/tasks)
        effective_split = split or _determine_split(f"{category}:{clean_question}")

        # LAH-014: Ground-truth contamination prevention.
        # Populate gold labels ONLY from verified test/retrieval-oracle/human correction.
        # Failed predictions or unverified model outputs must NEVER become gold truth.
        if receipt_dict is not None:
            if receipt_dict.get("passed", False):
                effective_source = label_source or "verified_receipt"
                effective_gold = dict(confidence_distribution or {expected_choice: 1.0})
                pred = prediction or expected_choice
                outcome = observed_outcome or "passed_verification"
            else:
                effective_source = label_source or "failed_verification"
                effective_gold = {}
                pred = prediction or expected_choice
                outcome = observed_outcome or "failed_verification"
        elif human_label:
            effective_source = label_source or "human_correction"
            effective_gold = {human_label: 1.0}
            expected_choice = human_label
            pred = prediction or expected_choice
            outcome = observed_outcome or "human_verified"
        elif label_source in ("retrieval_oracle", "oracle", "ground_truth", "synthetic_oracle"):
            effective_source = label_source
            effective_gold = dict(confidence_distribution or {expected_choice: 1.0})
            pred = prediction or expected_choice
            outcome = observed_outcome or "oracle_verified"
        else:
            effective_source = label_source or "model_prediction"
            pred = prediction or expected_choice
            outcome = observed_outcome or "unverified_prediction"
            effective_gold = {}

        raw_repr = f"{category}:{clean_question}:{expected_choice}:{effective_source}:{sorted(state_dict.items())}"
        h = hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()
        sid = f"laya_{h[:16]}"

        sample = LayaTrainingSample(
            sample_id=sid,
            category=category,
            state=state_dict,
            questions={"category": category, "query": clean_question},
            expected=expected_choice,
            gold=effective_gold,
            label_source=effective_source,
            prediction=pred,
            observed_outcome=outcome,
            verification_receipt=receipt_dict,
            human_label=human_label,
            teacher_model=teacher_model,
            split=effective_split,
            schema_version=2,
            timestamp=time.time(),
        )

        if self._is_and_mark_seen(h):
            return sample

        with self._lock:
            self._laya_count += 1

        try:
            self._queue.put_nowait((self.laya_inbox, sample.to_dict()))
        except queue.Full:
            logger.debug("Laya collector queue full, dropping sample")

        return sample

    def record_dpo_pair(
        self,
        category: str,
        prompt: str,
        chosen: str,
        rejected: str,
        verification_passed: bool = True,
        metadata: Mapping[str, Any] | None = None,
        split: str | None = None,
    ) -> DPOPairSample | None:
        """Record a chosen vs rejected code pair derived from verification receipts."""
        if not self.enabled:
            return None

        clean_prompt = _redact_sensitive(prompt)
        clean_chosen = _redact_sensitive(chosen)
        clean_rejected = _redact_sensitive(rejected)
        meta = dict(metadata or {})
        if not verification_passed:
            meta["failed_verification"] = True
        effective_split = split or _determine_split(clean_prompt)

        raw_repr = f"{category}:{clean_prompt[:100]}:{clean_chosen[:100]}:{clean_rejected[:100]}"
        h = hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()
        pid = f"dpo_{h[:16]}"

        sample = DPOPairSample(
            pair_id=pid,
            category=category,
            prompt=clean_prompt,
            chosen=clean_chosen,
            rejected=clean_rejected,
            verification_passed=verification_passed,
            metadata=meta,
            split=effective_split,
            schema_version=2,
            timestamp=time.time(),
        )

        if self._is_and_mark_seen(h):
            return sample

        with self._lock:
            self._dpo_count += 1

        try:
            self._queue.put_nowait((self.dpo_inbox, sample.to_dict()))
        except queue.Full:
            logger.debug("DPO collector queue full, dropping sample")

        return sample

    def record_retrieval_triplet(
        self,
        query: str,
        positive: str,
        negative: str,
        metadata: Mapping[str, Any] | None = None,
        split: str | None = None,
    ) -> RetrievalTripletSample | None:
        """Record (query, positive, hard_negative) triplet for Reranker and Embeddings fine-tuning."""
        if not self.enabled:
            return None

        clean_query = _redact_sensitive(query)
        clean_pos = _redact_sensitive(positive)
        clean_neg = _redact_sensitive(negative)
        meta = dict(metadata or {})
        effective_split = split or _determine_split(clean_query)

        raw_repr = f"triplet:{clean_query[:100]}:{clean_pos[:100]}:{clean_neg[:100]}"
        h = hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()
        tid = f"trip_{h[:16]}"

        sample = RetrievalTripletSample(
            triplet_id=tid,
            query=clean_query,
            positive=clean_pos,
            negative=clean_neg,
            metadata=meta,
            split=effective_split,
            schema_version=2,
            timestamp=time.time(),
        )

        if self._is_and_mark_seen(h):
            return sample

        with self._lock:
            self._triplet_count += 1

        try:
            self._queue.put_nowait((self.triplet_inbox, sample.to_dict()))
        except queue.Full:
            logger.debug("Triplet collector queue full, dropping sample")

        return sample

    def _worker_loop(self) -> None:
        """Background daemon loop batching writes to disk."""
        batch: list[tuple[Path, dict[str, Any]]] = []
        while not self._stop_event.is_set() or not self._queue.empty() or batch:
            try:
                if not batch:
                    try:
                        item = self._queue.get(timeout=0.2)
                        if item is None:
                            self._queue.task_done()
                            break
                        batch.append(item)
                    except queue.Empty:
                        pass

                while len(batch) < 64:
                    try:
                        item = self._queue.get_nowait()
                        if item is None:
                            self._queue.task_done()
                            break
                        batch.append(item)
                    except queue.Empty:
                        break

                if batch:
                    self._write_batch(batch)
                    for _ in batch:
                        self._queue.task_done()
                    batch.clear()

            except Exception as exc:
                logger.debug("Error in training collector worker loop: %s", exc)
                time.sleep(0.05)

    def _write_batch(self, batch: list[tuple[Path, dict[str, Any]]]) -> None:
        """Batch write formatted samples grouped by inbox target file."""
        grouped: dict[Path, list[str]] = {}
        for path, data in batch:
            grouped.setdefault(path, []).append(json.dumps(data, ensure_ascii=False) + "\n")

        for path, lines in grouped.items():
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.writelines(lines)
            except Exception as exc:
                logger.debug("Failed writing batch to %s: %s", path, exc)

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until all queued samples are persisted to disk."""
        if not self.enabled:
            return True
        deadline = time.monotonic() + max(0.05, float(timeout))
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self) -> None:
        """Gracefully stop collector worker after flushing."""
        if not self.enabled:
            return
        self.flush(timeout=1.0)
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            self._worker_thread.join(timeout=1.0)

    def get_stats(self) -> dict[str, Any]:
        """Return cumulative training samples collected in session."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "laya_samples_collected": self._laya_count,
                "dpo_pairs_collected": self._dpo_count,
                "retrieval_triplets_collected": self._triplet_count,
                "total_samples": self._laya_count + self._dpo_count + self._triplet_count,
                "laya_inbox_path": str(self.laya_inbox),
                "dpo_inbox_path": str(self.dpo_inbox),
                "triplet_inbox_path": str(self.triplet_inbox),
                "queue_pending": self._queue.qsize() if self.enabled else 0,
            }
