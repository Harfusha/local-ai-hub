"""Deferred edge coverage for bounded, canonical retrieval path fusion."""
from __future__ import annotations

import math

import pytest

from local_ai_hub.retrieval import fuse_ranked_paths


def test_path_spellings_canonicalize_before_backend_agreement():
    result = dict(fuse_ranked_paths({
        "deterministic": ["./src\\a.py"],
        "code_index": ["src//a.py"],
    }))

    assert list(result) == ["src/a.py"]
    assert result["src/a.py"] > (
        1.25 / 61.0 + 1.20 / 61.0
    )


def test_canonicalization_preserves_parent_segments_case_and_unc_paths():
    result = dict(fuse_ranked_paths({"lexical": [
        "./src//../A.py", "//server//share/./x.py", "Src/X.py",
        "src/x.py", ".", "./",
    ]}))

    assert set(result) == {
        "src/../A.py", "//server/share/x.py", "Src/X.py", "src/x.py",
    }
    assert "Src/X.py" in result and "src/x.py" in result


def test_malformed_groups_and_nonstring_entries_degrade_safely():
    def paths():
        yield object()
        yield "./src/valid.py"

    result = fuse_ranked_paths({
        "none": None,
        "text": "not/a/path/list.py",
        "mapping": {"src/key.py": 1},
        "scalar": 7,
        "generator": paths(),
    })

    assert [path for path, _score in result] == ["src/valid.py"]
    assert fuse_ranked_paths(None) == []


def test_caller_generator_consumption_is_bounded():
    consumed = 0

    def many_paths():
        nonlocal consumed
        while True:
            consumed += 1
            yield f"src/{consumed}.py"

    result = fuse_ranked_paths({"lexical": many_paths()}, limit=1)

    assert len(result) == 1
    assert consumed <= 128


@pytest.mark.parametrize("bad_limit", [None, True, False, 0, -1, "2"])
def test_limit_requires_positive_integer(bad_limit):
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        fuse_ranked_paths({}, limit=bad_limit)


@pytest.mark.parametrize("bad_limit", [None, True, 0, -1, "2"])
def test_max_per_path_requires_positive_integer(bad_limit):
    with pytest.raises(ValueError, match="max_per_path must be a positive integer"):
        fuse_ranked_paths({}, max_per_path=bad_limit)


def test_invalid_and_unrepresentably_large_weight_scales_are_ignored():
    groups = {"rag": ["src/a.py"], "lexical": ["src/b.py"]}
    baseline = fuse_ranked_paths(groups)

    tuned = fuse_ranked_paths(groups, source_weights={
        "rag": 10**10000,
        "lexical": math.nan,
    })

    assert tuned == baseline
