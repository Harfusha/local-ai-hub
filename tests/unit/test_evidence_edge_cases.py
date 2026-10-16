from __future__ import annotations

import hashlib
from pathlib import Path

from local_ai_hub.evidence import EvidenceStore, is_current_evidence_id, is_evidence_id
from local_ai_hub.evidence_contract import (
    evidence_meta,
    has_evidence_ids,
    is_stale_evidence_meta,
)


def test_evidence_contract_single_string_null_bytes_and_helpers() -> None:
    meta_str = evidence_meta(
        source="  determ\x00inistic  ",
        repository_revision=" rev\x00-123 ",
        evidence_ids="E0123456789abcdef0123",
        stale=False,
        status="  SUCCESS\x00 ",
    )
    assert meta_str["source"] == "deterministic"
    assert meta_str["repository_revision"] == "rev-123"
    assert meta_str["evidence_ids"] == ["E0123456789abcdef0123"]
    assert meta_str["stale"] is False
    assert meta_str["status"] == "success"
    assert has_evidence_ids(meta_str) is True
    assert is_stale_evidence_meta(meta_str) is False

    meta_stale = evidence_meta(
        source=True,  # type: ignore[arg-type]
        repository_revision=False,  # type: ignore[arg-type]
        evidence_ids=["  E\x001 ", "E1", "", None],
        stale=True,
        status="success",
    )
    assert meta_stale["source"] == ""
    assert meta_stale["repository_revision"] == ""
    assert meta_stale["evidence_ids"] == ["E1"]
    assert meta_stale["stale"] is True
    assert meta_stale["status"] == "stale"
    assert is_stale_evidence_meta(meta_stale) is True

    meta_empty = evidence_meta("src", "rev", None, False, "")
    assert has_evidence_ids(meta_empty) is False
    assert is_stale_evidence_meta("not-a-dict") is False
    assert has_evidence_ids("not-a-dict") is False


def test_evidence_store_nan_inf_surrogates_and_helpers(tmp_path: Path) -> None:
    store = EvidenceStore(
        tmp_path / "state",
        max_entries=float("nan"),  # type: ignore[arg-type]
    )
    assert store.max_entries == 100_000
    assert store.count() == 0

    bool_store = EvidenceStore(
        tmp_path / "state_bool",
        max_entries=False,  # type: ignore[arg-type]
    )
    assert bool_store.max_entries == 100_000

    assert store.put(str(tmp_path), None) is None  # type: ignore[arg-type]

    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")
    fhash = hashlib.sha256(src.read_bytes()).hexdigest()

    eid = store.put(
        str(repo),
        {
            "path": "mod.py",
            "file_sha256": fhash,
            "start_line": float("nan"),
            "end_line": "invalid",
            "text": "x = 1\ud800",
        },
    )
    assert eid is not None
    assert is_evidence_id(eid) is True
    assert store.has(eid) is True
    assert store.has("E00000000000000000000") is False
    assert store.count() == 1

    fetched = store.get(f"  {eid}\x00 ")
    assert fetched["success"] is True
    assert fetched["start_line"] == 1
    assert fetched["end_line"] == 1
    assert "\ud800" not in fetched["text"]
    assert is_current_evidence_id(eid, store) is True

    batch = store.put_many(
        str(repo),
        [
            "not-a-dict",  # type: ignore[list-item]
            {
                "path": "mod.py",
                "file_sha256": fhash,
                "start_line": 5,
                "end_line": 2,
                "text": "line\ud800",
            },
        ],
    )
    assert len(batch) == 1
    assert "evidence_id" in batch[0]
    batch_fetched = store.get(batch[0]["evidence_id"])
    assert batch_fetched["start_line"] == 5
    assert batch_fetched["end_line"] == 5

    store.clear()
    assert store.count() == 0
    assert store.has(eid) is False
