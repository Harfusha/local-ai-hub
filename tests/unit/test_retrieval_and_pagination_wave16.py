import math
import pytest
from local_ai_hub.retrieval import fuse_ranked_paths, reciprocal_rank
from local_ai_hub.search_pagination import (
    clamp_pagination,
    paginate_sequence,
    parse_pagination_mapping,
)


def test_fuse_ranked_paths_boolean_and_type_guards():
    groups = {
        "deterministic": [True, False, None, "valid/path/a.py", 123, {"bad": "type"}],
        "code_index": ["valid/path/a.py", "valid/path/b.py", True],
    }
    fused = fuse_ranked_paths(groups, limit=10)
    paths = [p for p, _ in fused]
    assert "True" not in paths
    assert "False" not in paths
    assert "valid/path/a.py" in paths
    assert "valid/path/b.py" in paths


def test_fuse_ranked_paths_invalid_limits_and_weights():
    groups = {"deterministic": ["src/main.py"]}
    for kwargs in ({"limit": True}, {"max_per_path": False}):
        with pytest.raises(ValueError):
            fuse_ranked_paths(groups, **kwargs)

    # invalid source_weights types
    fused2 = fuse_ranked_paths(groups, source_weights={"deterministic": float("inf")})
    assert len(fused2) == 1


def test_parse_pagination_mapping_overflow_error():
    # Passing float('inf') or float('-inf') must not raise unhandled OverflowError
    lim, off, err = parse_pagination_mapping({"limit": float("inf"), "offset": float("-inf")})
    assert err is not None or (isinstance(lim, int) and isinstance(off, int))
    assert 1 <= lim <= 200
    assert off >= 0


def test_paginate_sequence_invalid_types():
    # items not a sequence (e.g. generator or int or set)
    with pytest.raises(TypeError):
        paginate_sequence(12345)

    # generator
    gen = (x for x in range(10))
    with pytest.raises(TypeError):
        paginate_sequence(gen)
