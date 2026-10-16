from pathlib import Path

import pytest

from local_ai_hub import repo_tools
from local_ai_hub.process_utils import run_hidden


@pytest.mark.parametrize("exceed_inventory_bound", [False, True])
@pytest.mark.parametrize("exact", [False, True])
def test_exact_git_inventory_closes_pipe_on_success_and_bound_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exceed_inventory_bound: bool, exact: bool,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    run_hidden(["git", "init", "--quiet", str(root)], check=True, capture_output=True, timeout=10)
    (root / "a.py").write_text("needle = 1\n", encoding="utf-8")
    (root / "b.py").write_text("needle = 2\n", encoding="utf-8")
    processes = []
    start_process = repo_tools.popen_managed

    def capture_process(*args, **kwargs):
        process = start_process(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(repo_tools, "popen_managed", capture_process)
    if exact and exceed_inventory_bound:
        monkeypatch.setattr(repo_tools, "MAX_EXACT_GIT_PATHS", 1)
    tools = repo_tools.RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    if exact:
        result = tools.search(str(root), "needle", limit=1, exact_count=True)
        assert result["success"] is (not exceed_inventory_bound), result
        if not exceed_inventory_bound:
            assert result["total_matches"] == 2
            assert result["has_more"] is True
    else:
        inventory = tools._git_files(root, max_files=1 if exceed_inventory_bound else None)
        assert inventory is not None
        assert inventory.complete is (not exceed_inventory_bound)
        assert len(inventory) == (1 if exceed_inventory_bound else 2)
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed
