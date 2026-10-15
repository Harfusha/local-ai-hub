from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path
import pytest
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


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


@pytest.mark.parametrize("fallback", [False, True])
def test_search_reads_candidate_files_concurrently_and_keeps_results(
    tmp_path: Path, monkeypatch, fallback: bool,
) -> None:
    names = ["alpha.py", "bravo.py", "charlie.py", "delta.py"]
    for name in names:
        (tmp_path / name).write_text(f"needle in {name}\nsecond line\n", encoding="utf-8")
    candidates = [(f"{name}", 1) for name in names]

    def make_tools() -> RepositoryTools:
        tools = RepositoryTools({"rag": {"extensions": [".py"]}})
        monkeypatch.setattr(
            tools,
            "_ripgrep_candidates",
            lambda _base, _terms, _limit, candidate_paths=None: (
                (None, False) if fallback else (candidates, False)
            ),
        )
        if fallback:
            monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args: (None, False))
            monkeypatch.setattr(
                tools, "iter_files", lambda _root, max_files: [tmp_path / name for name in names]
            )
        return tools

    expected = make_tools().search(str(tmp_path), "needle", limit=10)
    tools = make_tools()
    original_read_bytes = Path.read_bytes
    active = 0
    max_active = 0
    active_lock = threading.Lock()
    overlap = threading.Event()

    def tracked_read_bytes(path: Path) -> bytes:
        nonlocal active, max_active
        if path.parent == tmp_path and path.name in names:
            with active_lock:
                active += 1
                max_active = max(max_active, active)
                if active >= 2:
                    overlap.set()
            try:
                overlap.wait(timeout=0.2)
                return original_read_bytes(path)
            finally:
                with active_lock:
                    active -= 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)
    actual = tools.search(str(tmp_path), "needle", limit=10)

    assert actual == expected
    assert max_active >= 2
