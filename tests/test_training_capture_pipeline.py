from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path
import pytest

from local_ai_hub.laya_training_collector import LayaTrainingCollector
from local_ai_hub.reranker import Reranker
from local_ai_hub.app import LocalAIApp


class _MockCrossEncoder:
    def __init__(self, scores: list[float]):
        self.model = SimpleNamespace(config=SimpleNamespace(_commit_hash="c" * 40))
        self.scores = scores

    def predict(self, pairs, **_kwargs):
        return self.scores[:len(pairs)]


def test_reranker_captures_training_triplets(tmp_path: Path) -> None:
    triplet_file = tmp_path / "retrieval_triplets.jsonl"
    collector = LayaTrainingCollector(
        triplet_inbox_path=triplet_file,
        enabled=True,
    )

    reranker = Reranker(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"reranker": "test-reranker", "reranker_backend": "torch", "reranker_device": "cpu"},
            "features": {"reranker": True},
            "cache": {"reranker": False},
        },
        training_collector=collector,
    )
    reranker._model = _MockCrossEncoder([0.95, 0.10])
    reranker.active_backend = "torch"
    reranker.active_device = "cpu"

    docs = ["def acquire_lock(): pass", "def send_email(): pass"]
    res = reranker.rerank(query="acquire lock in multi-threaded code", documents=docs)

    assert res["success"] is True
    assert len(res["results"]) == 2

    assert collector.flush(timeout=2.0) is True
    assert triplet_file.exists()

    lines = [json.loads(line) for line in triplet_file.read_text(encoding="utf-8").strip().splitlines() if line]
    assert len(lines) == 1
    sample = lines[0]
    assert sample["query"] == "acquire lock in multi-threaded code"
    assert sample["positive"] == "def acquire_lock(): pass"
    assert sample["negative"] == "def send_email(): pass"
    assert sample["metadata"]["pos_score"] == 0.95
    assert sample["metadata"]["neg_score"] == 0.10

    collector.close()


class _DummyApp:
    def __init__(self, collector):
        self.training_collector = collector
        self.telemetry = SimpleNamespace(record_laya_decision=lambda *args, **kwargs: True)
        self.logger = SimpleNamespace(debug=lambda *args: None, warning=lambda *args: None)

    _record_laya_runtime_decision = LocalAIApp._record_laya_runtime_decision


def test_app_laya_observation_records_decision(tmp_path: Path) -> None:
    laya_file = tmp_path / "laya_inbox.jsonl"
    collector = LayaTrainingCollector(
        laya_inbox_path=laya_file,
        enabled=True,
    )
    app = _DummyApp(collector)

    request = SimpleNamespace(
        category=SimpleNamespace(value="model_route"),
        state={"task": "refactor", "files": 5},
        repository_id="repo1",
        task_id="task_123",
        session_id="sess_abc",
    )
    decision = SimpleNamespace(
        suggestion="qwen2.5-coder:7b",
        metadata=lambda: {"category": "model_route", "suggestion": "qwen2.5-coder:7b"},
    )

    recorded = app._record_laya_runtime_decision(request, decision)
    assert recorded is True

    assert collector.flush(timeout=2.0) is True
    assert laya_file.exists()

    lines = [json.loads(line) for line in laya_file.read_text(encoding="utf-8").strip().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["category"] == "model_route"
    assert lines[0]["expected"] == "qwen2.5-coder:7b"
    assert lines[0]["state"]["files"] == 5

    collector.close()


def test_backfill_from_telemetry_db(tmp_path: Path) -> None:
    laya_file = tmp_path / "laya_backfill.jsonl"
    db_file = tmp_path / "test_telemetry.sqlite3"

    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, name TEXT, metrics_json TEXT)")
    con.execute(
        "INSERT INTO snapshots (name, metrics_json) VALUES (?, ?)",
        ("laya_decision", json.dumps({
            "status": "success",
            "category": "completion_gap",
            "suggestion": "ready",
            "task_id": "task_xyz",
            "session_id": "sess_xyz",
            "reason_codes": ["EVIDENCE_SUFFICIENT"],
        }))
    )
    con.commit()
    con.close()

    collector = LayaTrainingCollector(
        laya_inbox_path=laya_file,
        enabled=True,
    )

    count = collector.backfill_from_telemetry(db_file)
    assert count == 1

    lines = [json.loads(line) for line in laya_file.read_text(encoding="utf-8").strip().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["category"] == "completion_gap"
    assert lines[0]["expected"] == "ready"

    collector.close()


def test_verification_receipt_records_dpo_pair(tmp_path: Path) -> None:
    dpo_file = tmp_path / "dpo_receipts.jsonl"
    collector = LayaTrainingCollector(
        dpo_inbox_path=dpo_file,
        enabled=True,
    )

    collector.record_dpo_pair(
        category="verification_receipt",
        prompt="Task task_123 criterion: pytest passing",
        chosen=json.dumps({"task_id": "task_123", "passed": True}),
        rejected="",
        verification_passed=True,
        metadata={"receipt_id": "rcpt_001", "evidence_id": "ev_001"},
    )

    assert collector.flush(timeout=2.0) is True
    assert dpo_file.exists()

    lines = [json.loads(line) for line in dpo_file.read_text(encoding="utf-8").strip().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["category"] == "verification_receipt"
    assert lines[0]["verification_passed"] is True
    assert lines[0]["metadata"]["receipt_id"] == "rcpt_001"

    collector.close()
