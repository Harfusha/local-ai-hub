from __future__ import annotations

import math
import pytest

from local_ai_hub import response_protocol
from local_ai_hub import retrieval


def test_response_protocol_edge_cases():
    # _dense with boolean limit
    assert response_protocol._dense("hello", limit=True) == ""  # type: ignore

    # project_response with boolean max_output_tokens
    payload = {"success": True, "status": "ok", "summary": "test summary"}
    res = response_protocol.project_response(payload, max_output_tokens=True)  # type: ignore
    assert res["success"] is True

    # default_profile helper
    assert response_protocol.default_profile() == "compact"


def test_retrieval_fuse_ranked_paths_edge_cases():
    # None or non-mapping groups
    assert retrieval.fuse_ranked_paths(None) == []  # type: ignore
    assert retrieval.fuse_ranked_paths("invalid") == []  # type: ignore
    assert retrieval.fuse_ranked_paths({}) == []

    # Paths with null bytes and invalid elements
    groups = {
        "deterministic": ["src/app\x00.py", None, ""],  # type: ignore
        "code_index": ["src/app.py", "src/util.py"],
        "invalid_paths": None,  # type: ignore
    }
    ranked = retrieval.fuse_ranked_paths(groups)
    assert len(ranked) >= 1
    paths = [p for p, _ in ranked]
    assert "src/app.py" in paths
    assert all("\x00" not in p for p in paths)

    # Limit=1 and Boolean limit fallback
    ranked_limit = retrieval.fuse_ranked_paths(groups, limit=1)
    assert len(ranked_limit) == 1
    ranked_bool = retrieval.fuse_ranked_paths(groups, limit=True)  # type: ignore
    assert len(ranked_bool) >= 1

    # Helpers
    weights = retrieval.default_backend_weights()
    assert "deterministic" in weights
    assert weights["deterministic"] > 1.0

    rr = retrieval.reciprocal_rank(0)
    assert 0.0 < rr < 1.0
