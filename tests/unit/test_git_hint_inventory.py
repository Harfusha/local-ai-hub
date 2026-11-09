import subprocess

import pytest

from local_ai_hub import repo_tools
from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("pathspec", ["../outside", "/outside", "\\outside", "//server/share", "C:/absolute", "C:relative", "a/../b", "a/./b", "bad\x00path", ""])
def test_git_hint_pathspec_rejects_unsafe_input_before_spawn(tmp_path, monkeypatch, pathspec):
    (tmp_path / ".git").mkdir()
    tools = RepositoryTools({"search": {"prefer_git_files": True}})
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *_a, **_k: pytest.fail("unexpected Git process"))
    assert tools._git_files(tmp_path, pathspecs=(pathspec,)) is None


def test_git_hint_pathspec_is_literal_and_does_not_pollute_general_cache(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / "visible.py").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    tools = RepositoryTools({"search": {"prefer_git_files": True, "max_files": 50}})
    hints = tools._git_files(tmp_path, pathspecs=(":(glob)**",))
    assert hints is not None and hints == []
    normal = tools._git_files(tmp_path)
    assert normal is not None
    assert [p.name for p in normal] == ["visible.py"]


def test_distinct_hint_queries_do_not_accumulate_flight_locks(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    tools = RepositoryTools({"search": {"prefer_git_files": True, "max_files": 50}})
    for number in range(10):
        assert tools._git_files(tmp_path, pathspecs=(f"missing_{number}.py",)) == []
    assert len(tools._git_files_flights) <= 1


def test_concurrent_hint_inventories_keep_their_own_paths(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    for name in ("first.py", "second.py"):
        (tmp_path / name).write_text("value=1\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    tools = RepositoryTools({"search": {"prefer_git_files": True, "max_files": 50}})
    barrier = Barrier(2, timeout=5)
    def run(name):
        barrier.wait()
        return tools._git_files(tmp_path, pathspecs=(name,))
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(run, "first.py")
        right = pool.submit(run, "second.py")
        assert [p.name for p in left.result(timeout=10)] == ["first.py"]
        assert [p.name for p in right.result(timeout=10)] == ["second.py"]
