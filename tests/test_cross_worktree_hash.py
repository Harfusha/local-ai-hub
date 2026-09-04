import time
from contextlib import closing
from pathlib import Path
import subprocess

from local_ai_hub.config import load_config
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.rag import RAGStore, _fragment_hash
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def _config(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'''[server]\nstate_dir="{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile="cpu"\n[preprocessing]\nenabled=false\nfs_watcher_enabled=false\nhash_files_per_step=2\n''',
        encoding="utf-8",
    )
    return load_config(str(cfg))


class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _Rag:
    index_reset = False


def _insert_project(pre: ProjectPreprocessor, root: Path):
    now = time.time()
    with closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(root), "w", "running", "hash", 0, 0, now, now, 0, 0, now, "test"),
        )
        for i in range(4):
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (str(root), f"f{i}.py", "old", 1, 1, 1, None, 0, None, now),
            )
        con.commit()


def test_hash_phase_reuses_one_git_probe_map_across_batches(tmp_path: Path):
    config = _config(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    for i in range(4):
        (root / f"f{i}.py").write_text(f"value = {i}\n", encoding="utf-8")
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Noop(), _Noop(), tools)
    calls = 0

    def blob_map(_root):
        nonlocal calls
        calls += 1
        return {f"f{i}.py": f"git:f{i}" for i in range(4)}

    tools.git_blob_map = blob_map
    try:
        _insert_project(pre, root)
        assert pre._step_hash(dict(pre._project_row(str(root))))
        assert pre._step_hash(dict(pre._project_row(str(root))))
        assert calls == 1
    finally:
        pre.close()


def test_new_clean_worktree_seeds_git_hash_without_byte_read(tmp_path: Path):
    config = _config(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, capture_output=True)
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Noop(), _Noop(), tools)
    tools._hash_file_only = lambda _path: (_ for _ in ()).throw(AssertionError("clean file must not be byte-hashed"))
    try:
        _insert_project_for_inventory(pre, root)
        assert pre._step_inventory(dict(pre._project_row(str(root))))
        with closing(pre._connect()) as con:
            row = con.execute(
                "SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path='app.py'",
                (str(root),),
            ).fetchone()
        assert row[0].startswith("git:")
        assert row[1] == 0
    finally:
        pre.close()


def test_new_worktree_links_existing_content_card(tmp_path: Path):
    config = _config(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, capture_output=True)
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Noop(), _Noop(), tools)
    try:
        _insert_project_for_inventory(pre, root)
        now = time.time()
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                ("card-existing", "git:blob-app", "test", "1", "{}", now, now, 0),
            )
            con.commit()
        tools.git_blob_map = lambda _root: {"app.py": "git:blob-app"}
        assert pre._step_inventory(dict(pre._project_row(str(root))))
        with closing(pre._connect()) as con:
            card = con.execute(
                "SELECT card_key FROM file_refs WHERE root=? AND path='app.py'",
                (str(root),),
            ).fetchone()[0]
        assert card == "card-existing"
    finally:
        pre.close()


def _insert_project_for_inventory(pre: ProjectPreprocessor, root: Path):
    now = time.time()
    with closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(root), "w", "running", "inventory", 0, 0, now, now, 0, 0, now, "test"),
        )
        con.commit()


def test_dirty_and_untracked_files_still_use_byte_hash(tmp_path: Path):
    config = _config(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    tracked = root / "app.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, capture_output=True)
    tracked.write_text("value = 2\n", encoding="utf-8")
    (root / "new.py").write_text("value = 3\n", encoding="utf-8")
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Noop(), _Noop(), tools)
    calls = 0
    original_hash = tools._hash_file_only

    def counted_hash(path):
        nonlocal calls
        calls += 1
        return original_hash(path)

    tools._hash_file_only = counted_hash
    try:
        _insert_project_for_inventory(pre, root)
        assert pre._step_inventory(dict(pre._project_row(str(root))))
        with closing(pre._connect()) as con:
            rows = con.execute(
                "SELECT path,needs_hash FROM file_refs WHERE root=? ORDER BY path",
                (str(root),),
            ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [("app.py", 1), ("new.py", 1)]
        assert pre._step_hash(dict(pre._project_row(str(root))))
        assert calls == 2
    finally:
        pre.close()


def test_code_and_deterministic_reuse_blob_without_read(tmp_path: Path):
    config = _config(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    tools = RepositoryTools(config)
    code = CodeIndex(config, tools)
    deterministic = DeterministicEngine(config, tools, code)
    content_hash = "git:cached-blob"
    code._parse_blob_put(content_hash, "python", [], [], [])
    deterministic._fact_blob_put(content_hash, "python", [])
    tools._read_snapshot = lambda _path: (_ for _ in ()).throw(AssertionError("cache hit must not read file"))
    try:
        code_result = code.update_files_batch(str(root), [("app.py", content_hash)])
        deterministic_result = deterministic.update_files_batch(str(root), [("app.py", content_hash)])
        assert code_result["success"] is True
        assert deterministic_result["success"] is True
    finally:
        pass


def test_rag_reuses_source_text_without_read(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "app.py"
    path.write_text("def cached():\n    return 1\n", encoding="utf-8")
    services = _Noop()
    services.embed = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("embedding must be reused"))
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {}, "cpu_retrieval": {}, "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
        },
        services,
        _Noop(),
    )
    text = path.read_text(encoding="utf-8")
    fragment = _fragment_hash(text)
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
            (store._scope_key("tenant"), "old", "old.py", 0, fragment, text, "[1,0]"),
        )
        con.commit()
    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(AssertionError("source text override must avoid read")))
    result = store.index_paths_step(
        str(root), "tenant", "new", ["app.py"], content_overrides={"app.py": text}
    )
    assert result["success"] is True
    assert result["reused_chunks"] == 1
