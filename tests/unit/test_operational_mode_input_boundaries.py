"""Deferred branch-97 boundary regressions; no real mode or CUDA changes."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub.operational_mode import (
    _empty_torch_cuda_cache, load_operational_mode, set_operational_mode,
)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_state_path_never_defaults_to_active_or_writes_cwd(value, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    snapshot = load_operational_mode(value)
    assert snapshot.degraded is True
    assert snapshot.mode == "maintenance"
    with pytest.raises(ValueError, match="nonempty path"):
        set_operational_mode(value, "active")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [None, True, "3", float("nan"), float("inf"), -1, 0,
                                  pytest.param(10**1000, id="huge_int")])
def test_invalid_or_expired_timeout_never_calls_cuda(value, monkeypatch):
    cuda = SimpleNamespace(is_available=Mock(), empty_cache=Mock())
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    result = _empty_torch_cuda_cache(value)
    assert result["success"] is False
    assert result["verified"] is False
    cuda.is_available.assert_not_called()
    cuda.empty_cache.assert_not_called()
