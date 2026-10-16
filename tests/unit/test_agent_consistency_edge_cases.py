from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_consistency import (
    AdaptiveContextPack,
    AgentConsistencyGuard,
    ConsistencyRequest,
    ContractMapping,
    GuardWarning,
    ReuseCandidate,
    _bounded_sequence,
    _memory_value,
    _safe_float,
    _safe_int,
    _text,
)


def test_text_null_bytes_and_negative_limit() -> None:
    assert _text("hello\x00world", 20) == "helloworld"
    assert _text("hello", 0) == ""
    assert _text("hello", -5) == ""


def test_safe_int_and_safe_float_reject_booleans_and_non_finite() -> None:
    assert _safe_int(True, 42) == 42
    assert _safe_int(False, 42) == 42
    assert _safe_int(float("inf"), 10) == 10
    assert _safe_int(float("nan"), 10) == 10

    assert _safe_float(True, 1.5) == 1.5
    assert _safe_float(False, 1.5) == 1.5
    assert _safe_float(float("nan"), 2.5) == 2.5
    assert _safe_float(float("-inf"), 2.5) == 2.5


def test_bounded_sequence_rejects_strings_bytes_and_mappings() -> None:
    assert _bounded_sequence("string_input") == ()
    assert _bounded_sequence(b"bytes_input") == ()
    assert _bounded_sequence({"a": 1, "b": 2}) == ()
    assert _bounded_sequence([1, 2, 3], -1) == ()
    assert _bounded_sequence([1, 2, 3], 2) == (1, 2)


def test_memory_value_sanitizes_nan_inf_and_cycles() -> None:
    cyclic: dict[str, object] = {"score": float("nan"), "inf_val": float("inf"), "ok": 1.5}
    cyclic["self"] = cyclic

    result = _memory_value(cyclic)
    cyclic.clear()
    assert result["score"] == 0.0
    assert result["inf_val"] == 0.0
    assert result["ok"] == 1.5
    assert result["self"] == "<cycle>"


def test_record_finding_and_metadata_preserve_single_string_paths_and_evidence(tmp_path: Path) -> None:
    recorded = []

    class FakeMemoryStore:
        enabled = True

        def record(self, rec, **kwargs):
            recorded.append(rec)
            return rec

    guard = AgentConsistencyGuard(memory_store=FakeMemoryStore())
    req = guard._request_from_metadata(None, root=str(tmp_path), changed_paths="src/app.py")
    assert req is not None
    assert req.changed_paths == ("src/app.py",)

    rec = guard.record_finding(
        req,
        finding={"code": "test_finding"},
        evidence_ids="ev-single-1",
        path_refs="src/app.py",
        symbol_refs="my_func",
        confidence=float("nan"),
        retention_seconds=float("nan"),
    )
    assert rec is not None
    assert rec.evidence_ids == ("ev-single-1",)
    assert rec.path_refs == ("src/app.py",)
    assert rec.symbol_refs == ("my_func",)
    assert rec.confidence == 1.0


def test_record_metric_overflow_bool_and_reset() -> None:
    guard = AgentConsistencyGuard()
    assert guard.record_metric("reuse_candidates", float("inf")) == 0  # type: ignore[arg-type]
    assert guard.record_metric("reuse_candidates", True) == 0  # type: ignore[arg-type]
    assert guard.record_metric("reuse_candidates", 5) == 5
    guard.reset_metrics()
    assert guard.metrics_snapshot()["reuse_candidates"] == 0


def test_consistency_dataclasses_inspection_helpers(tmp_path: Path) -> None:
    req = ConsistencyRequest(
        root=str(tmp_path),
        changed_paths=("src/a.py",),
        override_reason="needed for migration",
        approval=True,
    )
    assert req.has_changed_paths() is True
    assert req.has_override() is True
    assert req.is_approved() is True

    empty_req = ConsistencyRequest(root=str(tmp_path))
    assert empty_req.has_changed_paths() is False
    assert empty_req.has_override() is False
    assert empty_req.is_approved() is False

    cand = ReuseCandidate("c1", "backend", "src/a.py", evidence_ids=("ev1",))
    assert cand.has_evidence() is True
    assert ReuseCandidate("c2", "backend", "src/b.py").has_evidence() is False

    mapping_ok = ContractMapping("endpoint", status="matched")
    assert mapping_ok.is_matched() is True
    assert mapping_ok.has_mismatches() is False

    mapping_bad = ContractMapping("response", status="mismatch", mismatches=("field_x",))
    assert mapping_bad.is_matched() is False
    assert mapping_bad.has_mismatches() is True

    warn_info = GuardWarning("info", "note", "info message")
    assert warn_info.is_blocking() is False
    assert warn_info.has_evidence() is False

    warn_bound = GuardWarning("boundary", "new_sym", "boundary message", evidence_ids=("ev1",), requires_approval=True)
    assert warn_bound.is_blocking() is True
    assert warn_bound.has_evidence() is True

    pack = AdaptiveContextPack(
        reuse_candidates=(cand,),
        warnings=(warn_info,),
        model_warnings=(warn_bound,),
    )
    assert pack.has_reuse_candidates() is True
    assert pack.has_warnings() is True
    assert pack.warning_count() == 2
