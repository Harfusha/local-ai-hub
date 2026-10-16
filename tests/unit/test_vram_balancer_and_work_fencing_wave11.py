from __future__ import annotations

import pytest

from local_ai_hub.vram_balancer import VRAMBalancer
from local_ai_hub.work_fencing import (
    _overlaps,
    are_paths_disjoint,
    is_safe_lease_path,
    normalize_paths,
)


def test_vram_balancer_safe_numeric_and_null_bytes(monkeypatch) -> None:
    balancer = VRAMBalancer()

    # _safe_float must not coerce bool to float
    assert balancer._safe_float(True, default=0.0) == 0.0
    assert balancer._safe_float(False, default=5.0) == 5.0
    assert balancer._safe_float(float("nan"), default=3.0) == 3.0

    monkeypatch.setattr(balancer, "status", lambda: {"context_budget_factor": 1.0, "pressure_level": "normal"})
    for budget in (float("nan"), True, -500):
        with pytest.raises(ValueError):
            balancer.recommended_context_budget(budget)
    assert balancer.recommended_context_budget(10**1000) == 10**1000
    with pytest.raises(ValueError):
        balancer.pin_model("qwen-pinned\x00", ttl_seconds=60)
    assert balancer.is_model_pinned("qwen-pinned\x00") is False
    res = balancer.pin_model("qwen-pinned", ttl_seconds=60)
    assert res["pinned"] is True
    assert res["model"] == "qwen-pinned"
    assert balancer.is_model_pinned("qwen-pinned") is True

    # Inspection helpers
    assert balancer.is_sampling() is False
    assert balancer.active_pinned_model() == "qwen-pinned"
    assert isinstance(balancer.current_pressure_level(), str)


def test_work_fencing_normalize_paths_rejects_scalar_string() -> None:
    # Passing a single string scalar instead of a sequence must be rejected
    with pytest.raises(ValueError, match="sequence"):
        normalize_paths("src/single_file.py")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="sequence"):
        normalize_paths(b"src/single_file.py")  # type: ignore[arg-type]


def test_work_fencing_overlaps_and_disjoint_helpers() -> None:
    # None or empty sequences must return False
    assert _overlaps(None, ["src/a.py"]) is False  # type: ignore[arg-type]
    assert _overlaps(["src/a.py"], None) is False  # type: ignore[arg-type]
    assert _overlaps([], []) is False

    # are_paths_disjoint
    assert are_paths_disjoint(["src/a.py"], ["src/b.py"]) is True
    assert are_paths_disjoint(["src/a.py"], ["src/a.py"]) is False
    assert are_paths_disjoint(["src"], ["src/nested/file.py"]) is False


def test_work_fencing_is_safe_lease_path() -> None:
    assert is_safe_lease_path("src/module/file.py") is True
    assert is_safe_lease_path("valid_file.txt") is True

    # Unsafe paths
    assert is_safe_lease_path(None) is False
    assert is_safe_lease_path(123) is False
    assert is_safe_lease_path("") is False
    assert is_safe_lease_path("/abs/path.py") is False
    assert is_safe_lease_path("C:\\Windows\\path.py") is False
    assert is_safe_lease_path("src/../escape.py") is False
    assert is_safe_lease_path("src/./curr.py") is False
    assert is_safe_lease_path("src//double_slash.py") is False
    assert is_safe_lease_path("src/file\x00.py") is False
