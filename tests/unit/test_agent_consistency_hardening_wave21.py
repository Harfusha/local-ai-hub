from __future__ import annotations

import math
import pytest
from local_ai_hub.agent_consistency import (
    ConsistencyRequest,
    ReuseCandidate,
    ContractMapping,
    GuardWarning,
    AdaptiveContextPack,
    _safe_int,
    _safe_float,
    _safe_bool,
    _text,
)


def test_safe_primitives_strict_typing_and_overflow():
    # Booleans must never masquerade as ints or floats
    assert _safe_int(True, default=0) == 0
    assert _safe_int(False, default=0) == 0
    assert _safe_float(True, default=0.0) == 0.0
    assert _safe_float(False, default=0.0) == 0.0

    # Overflows and non-finites must safely yield defaults
    assert _safe_int(float("inf"), default=42) == 42
    assert _safe_int("1" * 10000, default=-1) == -1
    assert _safe_float(float("nan"), default=1.5) == 1.5
    assert _safe_float("nan", default=2.5) == 2.5
    assert _safe_float(float("inf"), default=3.5) == 3.5
    assert _safe_float("inf", default=4.5) == 4.5

    # Safe bool handling
    assert _safe_bool("truthy", default=False) is True
    assert _safe_bool("off", default=True) is False
    assert _safe_bool(None, default=False) is False


def test_text_null_byte_sanitization():
    assert _text("hello\x00world") == "helloworld"
    assert _text("path/\x00to/\x00file") == "path/to/file"
    assert _text(None) == ""


def test_reuse_candidate_hardening_and_from_dict():
    candidate = ReuseCandidate(
        candidate_id="cand\x00_1",
        kind="function\x00",
        path="src/utils.py\x00",
        symbol="fetch_data\x00",
        line=True,  # type: ignore[arg-type]  # bool should not become line 1
        score=True,  # type: ignore[arg-type]  # bool should not become score 1.0
        reason="reusable logic\x00",
        evidence_ids=("ev\x001", ""),
        suitable="yes",  # type: ignore[arg-type]
    )
    assert candidate.candidate_id == "cand_1"
    assert candidate.kind == "function"
    assert candidate.path == "src/utils.py"
    assert candidate.symbol == "fetch_data"
    assert candidate.line == 0
    assert candidate.score == 0.0
    assert candidate.reason == "reusable logic"
    assert candidate.evidence_ids == ("ev1",)
    assert candidate.suitable is True

    # from_dict and roundtrip
    d = candidate.to_dict()
    assert isinstance(d, dict)
    recovered = ReuseCandidate.from_dict(d)
    assert recovered.candidate_id == "cand_1"
    assert recovered.path == "src/utils.py"
    assert recovered.suitable is True

    # Non-mapping input fallback
    fallback = ReuseCandidate.from_dict("invalid")  # type: ignore[arg-type]
    assert isinstance(fallback, ReuseCandidate)
    assert fallback.candidate_id == ""


def test_contract_mapping_from_dict_and_sanitization():
    mapping = ContractMapping(
        kind="endpoint\x00",
        endpoint="GET /api/v1/users\x00",
        backend_path="src/api.py\x00",
        frontend_path="web/client.ts\x00",
        backend_symbol="get_users\x00",
        frontend_symbol="fetchUsers\x00",
        backend_fields=("id\x00", "name"),
        status="matched\x00",
    )
    assert mapping.kind == "endpoint"
    assert mapping.endpoint == "GET /api/v1/users"
    assert mapping.backend_path == "src/api.py"
    assert mapping.status == "matched"
    assert mapping.backend_fields == ("id", "name")

    d = mapping.to_dict()
    assert isinstance(d, dict)
    recovered = ContractMapping.from_dict(d)
    assert recovered.kind == "endpoint"
    assert recovered.endpoint == "GET /api/v1/users"

    fallback = ContractMapping.from_dict(None)  # type: ignore[arg-type]
    assert isinstance(fallback, ContractMapping)
    assert fallback.kind == ""


def test_guard_warning_from_dict():
    warning = GuardWarning(
        severity="warning\x00",
        code="W001\x00",
        message="drift detected\x00",
        evidence_ids=("ev\x001",),
        affected_paths=("src/main.py\x00",),
        recommended_action="align types\x00",
        requires_approval="true",  # type: ignore[arg-type]
    )
    assert warning.severity == "warning"
    assert warning.code == "W001"
    assert warning.message == "drift detected"
    assert warning.requires_approval is True

    d = warning.to_dict()
    recovered = GuardWarning.from_dict(d)
    assert recovered.code == "W001"
    assert recovered.requires_approval is True

    fallback = GuardWarning.from_dict(123)  # type: ignore[arg-type]
    assert isinstance(fallback, GuardWarning)
    assert fallback.severity == ""


def test_consistency_request_and_pack_from_dict(tmp_path):
    root_dir = tmp_path / "repo"
    root_dir.mkdir()

    req = ConsistencyRequest(
        root=str(root_dir),
        task_id="task\x00_1",
        query="test query\x00",
        phase="edit",
        workspace="ws\x001",
        tenant="tenant-a",
        token_budget=True,  # type: ignore[arg-type]  # bool should not become budget 1
    )
    assert req.task_id == "task_1"
    assert req.query == "test query"
    assert req.token_budget == 2400  # default when bool is passed

    d = req.to_dict()
    recovered = ConsistencyRequest.from_dict(d)
    assert recovered.task_id == "task_1"
    assert recovered.tenant == "tenant-a"

    with pytest.raises(TypeError):
        ConsistencyRequest.from_dict(None)

    # AdaptiveContextPack
    cand = ReuseCandidate(candidate_id="c1", kind="fn", path="a.py")
    warn = GuardWarning(severity="info", code="I1", message="info msg")
    pack = AdaptiveContextPack(
        reuse_candidates=(cand,),
        warnings=(warn,),
        repo_revision="rev\x001",
        stale="truthy",  # type: ignore[arg-type]
    )
    assert pack.repo_revision == "rev1"
    assert pack.stale is True

    pack_dict = pack.to_dict()
    recovered_pack = AdaptiveContextPack.from_dict(pack_dict)
    assert len(recovered_pack.reuse_candidates) == 1
    assert recovered_pack.reuse_candidates[0].candidate_id == "c1"
    assert len(recovered_pack.warnings) == 1
    assert recovered_pack.warnings[0].code == "I1"
    assert recovered_pack.stale is True

    fallback_pack = AdaptiveContextPack.from_dict("invalid")  # type: ignore[arg-type]
    assert isinstance(fallback_pack, AdaptiveContextPack)
