from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

from local_ai_hub.cache import stable_hash
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.config import load_config
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub import repo_tools as repo_tools_module
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.tool_agent import ToolAwareLocalAgent


def cfg(tmp_path: Path):
    f = tmp_path / "config.toml"
    f.write_text(
        f'''[server]\nstate_dir="{(tmp_path / 'state').as_posix()}"\n[hardware]\nprofile="cpu"\n[preprocessing]\nenabled=false\nfs_watcher_enabled=false\nmax_preprocessing_projects=2\nauto_recheck_seconds=1800\n[local_tools]\nenabled=true\nbootstrap_deterministic_tools=true\ndirect_synthesis_confidence=0.90\n''',
        encoding="utf-8",
    )
    return load_config(str(f))


class Rag:
    index_reset = False
    def workspace_id(self, root): return "w"


class Scheduler:
    def foreground_busy(self): return False
    def background_allowed(self): return True
    def submit(self, model, *, source, execute, **kwargs): return execute()
    def note_background_yield(self): pass


class Runtime:
    def request(self, path, payload):
        return {"message": {"content": '{"summary":"cached intelligence used","confidence":0.97}'}, "total_duration": 1}


class Noop:
    def __getattr__(self, name): return lambda *a, **k: None


def test_search_successful_empty_accelerator_never_scans_repo(tmp_path: Path):
    config = cfg(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir()
    for i in range(150):
        (repo / f"f{i}.py").write_text(f"value_{i} = {i}\n", encoding="utf-8")
    tools = RepositoryTools(config)
    tools._ripgrep_candidates = lambda *a, **k: ([], False)  # successful accelerator miss
    tools._git_grep_candidates = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run fallback"))
    result = tools.search(str(repo), "definitely_missing_symbol", 5)
    assert result["success"] is True
    assert result["results"] == []
    assert result["engine"] == "ripgrep"
    assert result["scanned_files"] == 0


def test_git_repo_uses_ripgrep_before_git_grep_fallback_and_reads_exact_candidate(tmp_path: Path):
    config = cfg(tmp_path)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    source = repo / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("def needle(): return 1\n", encoding="utf-8")
    tools = RepositoryTools(config)
    calls: list[str] = []

    def git_grep(*_args, **_kwargs):
        calls.append("git-grep")
        return [("src/module.py", 1)], False

    def ripgrep(*_args, **_kwargs):
        calls.append("ripgrep")
        return None, True

    tools._git_grep_candidates = git_grep
    tools._ripgrep_candidates = ripgrep

    result = tools.search(str(repo), "needle", 5)

    assert calls == ["ripgrep", "git-grep"]
    assert result["success"] is True
    assert result["engine"] == "git-grep"
    assert result["results"][0]["path"] == "src/module.py"
    assert result["results"][0]["start_line"] == 1
def test_git_search_finds_untracked_file_with_ripgrep(tmp_path: Path):
    config = cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    source = repo / "src" / "new_module.py"
    source.parent.mkdir()
    source.write_text("def untracked_search_target(): return 1\n", encoding="utf-8")
    tools = RepositoryTools(config)

    result = tools.search(str(repo), "untracked_search_target", 5)

    assert result["success"] is True
    assert result["engine"] == "ripgrep"
    assert result["results"][0]["path"] == "src/new_module.py"
    assert result["results"][0]["start_line"] == 1


def test_ripgrep_timeout_cools_down_repo_and_keeps_search_bounded(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "max_files": 100,
            "prefer_git_files": False,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
            "ripgrep_timeout_seconds": 0.5,
            "ripgrep_slow_cooldown_seconds": 15,
        },
    })
    tools._rg = "rg"
    subprocess_calls = []

    def timeout(*_args, **_kwargs):
        subprocess_calls.append(True)
        raise subprocess.TimeoutExpired("rg", 0.5)

    def forbidden_scan(*_args, **_kwargs):
        raise AssertionError("timed-out accelerator must not trigger a Python scan")

    monkeypatch.setattr(repo_tools_module.subprocess, "run", timeout)
    monkeypatch.setattr(tools, "iter_files", forbidden_scan)

    first = tools.search(str(root), "missing_symbol", 5)
    second = tools.search(str(root), "another_missing_symbol", 5)

    assert first["engine"] == "bounded-accelerator-failure"
    assert second["engine"] == "bounded-accelerator-failure"
    assert first["retryable"] is True
    assert second["retryable"] is True
    assert subprocess_calls == [True]
    assert tools._git_stats["ripgrep_timeouts"] == 1
    assert tools._git_stats["ripgrep_cooldown_skips"] == 1

    tools._ripgrep_slow_until[str(root)] = 0.0
    monkeypatch.setattr(
        repo_tools_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["rg"], 1, stdout="", stderr=""),
    )
    recovered_candidates, recovered_failed = tools._ripgrep_candidates(root, ["needle"], 20)

    assert recovered_candidates == []
    assert recovered_failed is False
    assert str(root) not in tools._ripgrep_slow_until


def test_python_search_fallback_metric_is_separate_from_ripgrep_timeout(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "module.py").write_text("def target(): pass\n", encoding="utf-8")
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "prefer_git_files": False,
            "max_files": 5,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
        },
    })

    result = tools.search(str(root), "target", 5)

    assert result["engine"] == "python"
    stats = tools.snapshot_stats()["git_files"]
    assert stats["python_search_fallbacks"] == 1
    assert stats["ripgrep_timeouts"] == 0


def _insert_project(pre: ProjectPreprocessor, root: Path):
    now = time.time()
    with closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(root), "w", "running", "inventory", 0, 0, now, now, 0, 0, now, "test"),
        )
        con.commit()


def test_preprocessor_minor_edit_is_incremental_and_mtime_only_keeps_card(tmp_path: Path):
    config = cfg(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir()
    path = repo / "app.py"; path.write_text("answer = 1\n", encoding="utf-8")
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, Noop(), Rag(), Scheduler(), Runtime(), tools)
    try:
        _insert_project(pre, repo)
        row = dict(pre._project_row(str(repo)))
        assert pre._step_inventory(row)
        assert pre._step_hash(dict(pre._project_row(str(repo))))
        with closing(pre._connect()) as con:
            con.execute("UPDATE file_refs SET card_key='card-1' WHERE root=? AND path='app.py'", (str(repo),))
            con.execute("UPDATE projects SET last_complete_at=?,status='complete',phase='inventory' WHERE root=?", (time.time(), str(repo)))
            con.commit()
        # metadata-only touch must not discard a content-addressed card
        st = path.stat(); os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
        before = dict(pre._project_row(str(repo)))
        assert pre._step_inventory(before)
        mid = dict(pre._project_row(str(repo)))
        assert mid["generation"] == before["generation"]
        assert pre._step_hash(mid)
        with closing(pre._connect()) as con:
            card = con.execute("SELECT card_key FROM file_refs WHERE root=? AND path='app.py'", (str(repo),)).fetchone()[0]
        assert card == "card-1"
        # a one-file content edit is still incremental, but its own card is invalidated
        path.write_text("answer = 12345\n", encoding="utf-8")
        before = dict(pre._project_row(str(repo)))
        assert pre._step_inventory(before)
        mid = dict(pre._project_row(str(repo)))
        assert mid["generation"] == before["generation"]
        assert pre._step_hash(mid)
        with closing(pre._connect()) as con:
            card = con.execute("SELECT card_key FROM file_refs WHERE root=? AND path='app.py'", (str(repo),)).fetchone()[0]
        assert card is None
    finally:
        pre.close()


def test_batch_indexes_share_sha256_and_single_deterministic_generation(tmp_path: Path):
    config = cfg(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir()
    tools = RepositoryTools(config)
    code = CodeIndex(config, tools)
    det = DeterministicEngine(config, tools, code)
    items = []
    for i in range(12):
        raw = f"def f{i}():\n    return {i}\n".encode()
        (repo / f"m{i}.py").write_bytes(raw)
        items.append((f"m{i}.py", hashlib.sha256(raw).hexdigest()))
    cr = code.update_files_batch(str(repo), items)
    dr = det.update_files_batch(str(repo), items)
    assert cr["files_processed"] == 12
    assert dr["updated"] == 12
    with closing(code._connect()) as con:
        stored = dict(con.execute("SELECT path,content_hash FROM files WHERE root=?", (str(repo),)).fetchall())
    assert stored == dict(items)
    assert det._generation(str(repo)) == 1


class MiniCache:
    def __init__(self): self.data = {}
    def get_or_compute(self, key, fn):
        if key in self.data: return self.data[key], True, False
        value = fn(); self.data[key] = value; return value, False, False


class Pre:
    def __init__(self): self.compact_calls = 0
    def touch_if_registered(self, root): return True
    def context_revision(self, root): return "ctx-1"
    def compact_context(self, root, task, max_chars):
        self.compact_calls += 1
        return '{"project":{"architecture":"precomputed"}}'
    def lookup(self, *a, **k): return {"success": True, "preprocessed": True}


class Services:
    def __init__(self, config, tools):
        from local_ai_hub.model_policy import ModelExecutionPolicy
        self.repo_tools = tools; self.scheduler = Scheduler(); self.runtime = Runtime(); self.generation_cache = MiniCache()
        self.model_policy = ModelExecutionPolicy(config); self.det_calls = 0; self.code_calls = 0
    def _repo_cache_state(self, root): return {"fingerprint": "repo-1", "kind": "test"}
    def deterministic_query(self, root, task, limit):
        self.det_calls += 1
        return {"success": True, "direct_answer": True, "confidence": 0.97, "facts": [{"name":"A"}], "evidence": []}
    def code_query(self, root, task, limit):
        self.code_calls += 1
        return {"success": True, "symbols": [{"name":"A","path":"a.py"}]}


def test_local_agent_checks_exact_cache_before_bootstrap_and_prompts_with_preprocessed_data(tmp_path: Path):
    config = cfg(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "a.py").write_text("class A: pass\n", encoding="utf-8")
    tools = RepositoryTools(config); pre = Pre(); services = Services(config, tools)
    class RR:
        def workspace_id(self, root): return "w"
    agent = ToolAwareLocalAgent(config, services, pre, RR(), deterministic=object(), code_index=object())
    first = agent.run("qwen2.5-coder:3b-instruct-q5_K_M", "worker", "where is A", str(repo), "t", 128, 5)
    assert first["success"] is True
    assert first["tool_agent"]["direct_synthesis"] is True
    assert first["tool_agent"]["preprocessed"] is True
    assert services.det_calls == 1 and services.code_calls == 1 and pre.compact_calls == 1
    second = agent.run("qwen2.5-coder:3b-instruct-q5_K_M", "worker", "where is A", str(repo), "t", 128, 5)
    assert second["tool_agent_cache"]["hit"] is True
    assert services.det_calls == 1 and services.code_calls == 1 and pre.compact_calls == 1


def test_git_grep_searches_source_files_when_rag_extensions_are_unconfigured(tmp_path: Path):
    config = {"server": {"state_dir": str(tmp_path / "state")}, "search": {"max_files": 100}}
    repo = tmp_path / "repo"
    source = repo / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("def needle(): return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    result = RepositoryTools(config).search(str(repo), "needle", limit=5)

    assert result["success"] is True
    assert result["engine"] == "ripgrep"
    assert result["results"][0]["path"] == "src/module.py"
    assert result["results"][0]["start_line"] == 1
