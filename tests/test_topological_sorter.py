"""Unit tests for Topological Sorter with Tarjan SCC Cycle Breaking."""

from local_ai_hub.topological_sorter import topological_sort_with_cycles


def test_linear_topological_sort() -> None:
    # app depends on service, service depends on models
    deps = {
        "app.py": ["service.py"],
        "service.py": ["models.py"],
        "models.py": [],
    }
    res = topological_sort_with_cycles(deps)
    assert len(res.cycles_detected) == 0
    assert res.cycle_breaks_count == 0

    order = list(res.ordered_paths)
    # models must precede service, service must precede app
    assert order.index("models.py") < order.index("service.py")
    assert order.index("service.py") < order.index("app.py")


def test_circular_dependency_cycle_breaking() -> None:
    # Mutual recursion / cycle: a depends on b, b depends on c, c depends on a
    deps = {
        "a.py": ["b.py"],
        "b.py": ["c.py"],
        "c.py": ["a.py"],
        "main.py": ["a.py"],
    }
    res = topological_sort_with_cycles(deps)
    assert len(res.cycles_detected) >= 1
    assert res.cycle_breaks_count >= 1

    # All nodes must be present in ordered paths
    assert set(res.ordered_paths) == {"a.py", "b.py", "c.py", "main.py"}
    # main.py depends on a.py, so it should be after a.py (or at the end)
    assert len(res.ordered_paths) == 4
