from __future__ import annotations

import concurrent.futures
from pathlib import Path
import pytest
from local_ai_hub.deterministic import DeterministicEngine


def test_test_matrix_reads_files_with_thread_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()

    for i in range(5):
        f = test_dir / f"test_module_{i}.py"
        f.write_text(f"def test_foo_{i}():\n    pass\ndef test_bar_{i}():\n    pass\n", encoding="utf-8")

    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    pool_called = {"count": 0, "max_workers": 0}
    orig_tpe = concurrent.futures.ThreadPoolExecutor

    class TrackedThreadPoolExecutor(orig_tpe):
        def __init__(self, *args, **kwargs):
            pool_called["count"] += 1
            pool_called["max_workers"] = kwargs.get("max_workers")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", TrackedThreadPoolExecutor)
    import local_ai_hub.deterministic as det_mod
    if hasattr(det_mod, "ThreadPoolExecutor"):
        monkeypatch.setattr(det_mod, "ThreadPoolExecutor", TrackedThreadPoolExecutor)

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.test_matrix(str(tmp_path))

    assert result["success"] is True
    assert result["framework"] == "pytest"
    assert len(result["test_files"]) == 5

    # Must have used ThreadPoolExecutor for concurrent file reads
    assert pool_called["count"] > 0, "ThreadPoolExecutor must be used to read files concurrently"
    assert pool_called["max_workers"] is not None and pool_called["max_workers"] <= 16


def test_test_matrix_parallel_read_preserves_deterministic_order_and_content(tmp_path: Path) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()

    expected_paths = []
    for i in range(8):
        rel = f"tests/test_{i:02d}.py"
        f = tmp_path / rel
        f.write_text(f"def test_case_{i}(): pass\n", encoding="utf-8")
        expected_paths.append(rel)

    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.test_matrix(str(tmp_path))

    assert result["success"] is True
    found_paths = [tf["path"] for tf in result["test_files"]]
    assert found_paths == sorted(expected_paths)
    for tf in result["test_files"]:
        assert len(tf["cases"]) == 1
        idx = int(tf["path"].split("_")[1].split(".")[0])
        assert tf["cases"][0] == f"test_case_{idx}"
