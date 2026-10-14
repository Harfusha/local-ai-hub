from __future__ import annotations

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def _engine(tmp_path):
    return DeterministicEngine(config={"server": {"state_dir": str(tmp_path / "state")}})


def _write_modules(root, imports):
    for module, dependencies in imports.items():
        lines = [f"import {dependency}" for dependency in dependencies]
        (root / f"{module}.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_defaults_bound_dense_cycle_graph_and_report_incomplete(tmp_path):
    _write_modules(tmp_path, {
        **{f"cycle_{i:03d}a": [f"cycle_{i:03d}b"] for i in range(51)},
        **{f"cycle_{i:03d}b": [f"cycle_{i:03d}a"] for i in range(51)},
    })

    result = _engine(tmp_path).find_circular_dependencies(str(tmp_path))

    assert result["success"] is True
    assert len(result["cycles"]) == 50
    assert result["truncated"] is True
    assert result["complete"] is False


def test_depth_limit_keeps_unvisited_cutoff_nodes_for_shallower_roots(tmp_path):
    imports = {f"deep_{i:02d}": [f"deep_{i + 1:02d}"] for i in range(16)}
    imports["deep_16"] = ["deep_15"]
    imports["z_cycle_a"] = ["z_cycle_b"]
    imports["z_cycle_b"] = ["z_cycle_a"]
    imports["deep_15"].append("z_cycle_a")
    _write_modules(tmp_path, imports)

    result = _engine(tmp_path).find_circular_dependencies(str(tmp_path))

    assert any(cycle["cycle"] == ["z_cycle_a", "z_cycle_b", "z_cycle_a"] for cycle in result["cycles"])
    assert result["truncated"] is True
    assert result["complete"] is False


def test_custom_depth_allows_closing_backedge_at_boundary(tmp_path):
    _write_modules(tmp_path, {f"node_{i:02d}": [f"node_{(i + 1) % 15:02d}"] for i in range(15)})

    result = _engine(tmp_path).find_circular_dependencies(str(tmp_path), max_depth=15)

    assert len(result["cycles"]) == 1
    assert result["cycles"][0]["length"] == 15
    assert result["truncated"] is False
    assert result["complete"] is True


def test_custom_limits_and_exact_cycle_limit(tmp_path):
    _write_modules(tmp_path, {"a": ["b"], "b": ["a"], "c": ["d"], "d": ["c"]})

    result = _engine(tmp_path).find_circular_dependencies(str(tmp_path), max_depth=2, max_cycles=2)

    assert len(result["cycles"]) == 2
    assert result["truncated"] is False
    assert result["complete"] is True


@pytest.mark.parametrize("kwargs", [{"max_depth": 0}, {"max_cycles": 0}, {"max_depth": True}, {"max_cycles": 1.5}, {"max_depth": 10000}])
def test_invalid_limits_are_rejected(tmp_path, kwargs):
    with pytest.raises(ValueError):
        _engine(tmp_path).find_circular_dependencies(str(tmp_path), **kwargs)
