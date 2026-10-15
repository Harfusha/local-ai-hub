from local_ai_hub.agent_routing import RoutingEngine
from local_ai_hub.agent_verification import ChangeIntent


def _change(paths: tuple[str, ...]) -> ChangeIntent:
    return ChangeIntent(change_id="test-change", task_id="test-task", affected_paths=paths)


def test_existing_posix_python_test_path_is_selected_verbatim():
    selected = RoutingEngine().select_tests(_change(("tests/unit/test_feature.py",)))
    assert selected.selected_tests == ("tests/unit/test_feature.py",)
    assert selected.flaky_candidates == ()
    assert selected.synthetic_passes == ()


def test_windows_python_test_path_normalizes_separators_and_keeps_flaky_match():
    engine = RoutingEngine()
    engine.mark_flake("C:/repo/tests/unit/test_feature.py::test_current")

    selected = engine.select_tests(_change((r"C:\repo\tests\unit\test_feature.py",)))

    assert selected.selected_tests == ("C:/repo/tests/unit/test_feature.py",)
    assert selected.flaky_candidates == ("C:/repo/tests/unit/test_feature.py::test_current",)
    assert selected.synthetic_passes == ()


def test_source_mapping_and_existing_test_paths_deduplicate_without_broad_name_rule():
    engine = RoutingEngine()
    engine.mark_flake("tests/test_feature.py::test_mapped")
    engine.mark_flake("tests/unit/test_feature.py::test_current")

    selected = engine.select_tests(_change((
        "src/feature.py",
        r"tests\unit\test_feature.py",
        "tests/unit/test_feature.py",
        "src/test_widget.py",
        "tests/unit/test_widget.ts",
    )))

    assert selected.selected_tests == (
        "tests/test_feature.py",
        "tests/unit/test_feature.py",
        "tests/test_test_widget.py",
    )
    assert set(selected.flaky_candidates) == {
        "tests/test_feature.py::test_mapped",
        "tests/unit/test_feature.py::test_current",
    }
    assert len(selected.flaky_candidates) == 2
    assert selected.synthetic_passes == ()


def test_empty_affected_paths_stays_empty():
    selected = RoutingEngine().select_tests(_change(()))
    assert selected.selected_tests == ()
    assert selected.flaky_candidates == ()
    assert selected.synthetic_passes == ()
