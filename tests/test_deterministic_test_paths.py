import pytest

from local_ai_hub.deterministic_test_paths import is_test_file


@pytest.mark.parametrize("path", [
    "tests/test_demo.py",
    "src\\fixtures\\sample.json",
    "specs/client.ts",
    "src\\__tests__\\button.test.jsx",
    "test_cli.py",
    "mock_client.py",
    "src/net/http_test.go",
    "web/client.test.mjs",
])
def test_test_path_classifier_accepts_test_directories_prefixes_and_suffixes(path):
    assert is_test_file(path)


@pytest.mark.parametrize("path", [
    "src/testing/demo.py",
    "src/testimonials.py",
    "src/client.js",
    "src/TESTS_README.md",
])
def test_test_path_classifier_rejects_non_test_paths(path):
    assert not is_test_file(path)


def test_deterministic_module_preserves_private_classifier_alias():
    from local_ai_hub.deterministic import _is_test_file

    assert _is_test_file is is_test_file


def test_test_matrix_result_builder_preserves_complete_row_shape():
    from local_ai_hub.deterministic_test_paths import build_test_file_result

    cases = ["test_normalizes_path", "test_rejects_empty_path"]
    assert build_test_file_result(
        "tests/test_paths.py", "a" * 64, cases, True, ".py",
        ["pytest", "tests/test_paths.py"], "pytest tests/test_paths.py",
    ) == {
        "path": "tests/test_paths.py",
        "cases_count": 2,
        "cases": cases,
        "run_command": "pytest tests/test_paths.py",
        "run_argv": ["pytest", "tests/test_paths.py"],
        "content_sha256": "a" * 64,
        "cases_truncated": False,
        "cases_scan_complete": True,
        "case_detection": "python_test_function_name_heuristic",
    }


def test_test_matrix_result_builder_keeps_scan_and_display_truncation_separate():
    from local_ai_hub.deterministic_test_paths import build_test_file_result

    cases = [f"test_case_{index}" for index in range(16)]
    row = build_test_file_result(
        "tests/test_paths.py", "b" * 64, cases, False, ".py", [], "",
    )

    assert row["cases_count"] == 16
    assert row["cases"] == cases[:15]
    assert row["cases_truncated"] is True
    assert row["cases_scan_complete"] is False


def test_test_matrix_worker_dispatch_caps_pool_and_preserves_map_order(monkeypatch):
    import local_ai_hub.deterministic_test_paths as test_paths

    created_limits = []

    class RecordingExecutor:
        def __init__(self, *, max_workers):
            created_limits.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, worker, items):
            return map(worker, items)

    monkeypatch.setattr(test_paths, "ThreadPoolExecutor", RecordingExecutor, raising=False)

    assert test_paths.run_test_matrix_workers(lambda item: item * 2, list(range(10))) == [
        0, 2, 4, 6, 8, 10, 12, 14, 16, 18,
    ]
    assert created_limits == [8]


def test_test_matrix_worker_dispatch_uses_selected_count_for_small_batches(monkeypatch):
    import local_ai_hub.deterministic_test_paths as test_paths

    created_limits = []

    class RecordingExecutor:
        def __init__(self, *, max_workers):
            created_limits.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, worker, items):
            return map(worker, items)

    monkeypatch.setattr(test_paths, "ThreadPoolExecutor", RecordingExecutor, raising=False)

    assert test_paths.run_test_matrix_workers(str, [1, 2]) == ["1", "2"]
    assert created_limits == [2]


def test_test_matrix_target_selection_sorts_then_applies_count_limit(tmp_path):
    from local_ai_hub.deterministic_test_paths import select_test_matrix_targets

    targets = []
    for name, size in (("b_test.py", 3), ("c_test.py", 1), ("a_test.py", 2)):
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        targets.append((name, path, path.stat()))

    selected, incomplete, warnings = select_test_matrix_targets(
        targets, max_targets=2, max_total_bytes=7,
    )

    assert [item[0] for item in selected] == ["a_test.py", "b_test.py"]
    assert incomplete is True
    assert warnings == ["test_file_result_limit_reached"]


def test_test_matrix_target_selection_reserves_snapshot_lookahead_byte(tmp_path):
    from local_ai_hub.deterministic_test_paths import select_test_matrix_targets

    targets = []
    for name, size in (("b_test.py", 1), ("a_test.py", 2)):
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        targets.append((name, path, path.stat()))

    selected, incomplete, warnings = select_test_matrix_targets(
        targets, max_targets=10, max_total_bytes=4,
    )

    assert [item[0] for item in selected] == ["a_test.py"]
    assert incomplete is True
    assert warnings == ["test_file_total_byte_limit_reached"]


def test_test_matrix_row_collection_preserves_order_and_all_incomplete_signals():
    from local_ai_hub.deterministic_test_paths import collect_test_matrix_rows

    first = {"path": "tests/a_test.py", "cases_scan_complete": True}
    partial = {
        "path": "tests/b_test.py",
        "cases_truncated": True,
        "cases_scan_complete": False,
    }

    rows, incomplete, warnings = collect_test_matrix_rows([
        first, None, {"_omitted": "OSError"}, partial,
    ])

    assert rows == [first, partial]
    assert incomplete is True
    assert warnings == [
        "test_file_read_failed",
        "test_file_read_failed",
        "test_case_result_limit_reached",
        "test_case_scan_incomplete",
    ]


def test_test_matrix_row_collection_keeps_empty_complete_results_complete():
    from local_ai_hub.deterministic_test_paths import collect_test_matrix_rows

    rows, incomplete, warnings = collect_test_matrix_rows([])

    assert rows == []
    assert incomplete is False
    assert warnings == []


def test_test_matrix_response_builder_preserves_public_coverage_contract():
    from local_ai_hub.deterministic_test_paths import build_test_matrix_response

    rows = [{"path": "tests/test_a.py"}, {"path": "tests/test_b.py"}]
    assert build_test_matrix_response(
        "pytest", "pytest", rows, True,
        ["test_file_read_failed", "test_file_read_failed", "test_file_result_limit_reached"],
        max_depth=25, max_files=2000,
    ) == {
        "success": True,
        "framework": "pytest",
        "run_all_command": "pytest",
        "test_files_count": 2,
        "test_files": rows,
        "coverage": {
            "scan_complete": False,
            "scan_complete_within_scope": False,
            "scope": "current supported test files emitted by repo_tools iterator",
            "max_depth": 25,
            "max_files": 2000,
            "inventory_omissions_unknown": True,
            "warnings": ["test_file_read_failed", "test_file_result_limit_reached"],
        },
    }
