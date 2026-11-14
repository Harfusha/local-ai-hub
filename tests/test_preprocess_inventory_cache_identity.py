from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock
import hashlib

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def test_unchanged_file_keeps_existing_cache_identity_when_git_map_appears(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": True}}
    repo = RepositoryTools(config)
    repo.git_blob_map = MagicMock(return_value={"example.py": "git:example"})
    rag = MagicMock()
    rag.workspace_id.return_value = "workspace"
    prep = ProjectPreprocessor(config, services=MagicMock(), rag=rag, scheduler=MagicMock(), runtime=MagicMock(), repo_tools=repo)
    prep.register(str(root))
    prep._yield = lambda: False
    stat = source.stat()
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,0,?,1,?,0)",
            (str(root.resolve()), "example.py", "old-content-digest", stat.st_size, stat.st_mtime_ns, "old-content-digest", "card-key"),
        )
        con.commit()
        row = dict(con.execute("SELECT * FROM projects WHERE root=?", (str(root.resolve()),)).fetchone())
    assert prep._step_inventory(row)
    with closing(prep._connect()) as con:
        actual = con.execute("SELECT content_hash,rag_hash,card_key FROM file_refs WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
    assert tuple(actual) == ("old-content-digest", "old-content-digest", "card-key")

    source.write_text("value = 200\n", encoding="utf-8")
    with closing(prep._connect()) as con:
        row = dict(con.execute("SELECT * FROM projects WHERE root=?", (str(root.resolve()),)).fetchone())
    assert prep._step_inventory(row)
    with closing(prep._connect()) as con:
        actual = con.execute("SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
    assert tuple(actual) == ("old-content-digest", 1)
    assert prep._step_hash(row)
    with closing(prep._connect()) as con:
        actual = con.execute("SELECT content_hash,needs_hash,card_key FROM file_refs WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
    assert tuple(actual) == (hashlib.sha256(source.read_bytes()).hexdigest(), 0, None)


def test_legacy_git_identity_converges_to_stable_lexical_cache(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "example.py"
    source.write_bytes(b"value = 1\r\n")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": True}}
    repo = RepositoryTools(config)
    repo.git_blob_map = MagicMock(return_value={"example.py": "git:legacy"})
    rag = MagicMock()
    rag.workspace_id.return_value = "workspace"
    prep = ProjectPreprocessor(config, services=MagicMock(), rag=rag, scheduler=MagicMock(), runtime=MagicMock(), repo_tools=repo)
    prep.register(str(root))
    prep._yield = lambda: False
    stat = source.stat()
    with closing(prep._connect()) as con:
        con.execute("INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,generation,updated_at) VALUES(?,?,?,?,?,0,1,0)",
                    (str(root.resolve()), "example.py", "git:legacy", stat.st_size, stat.st_mtime_ns))
        con.commit()
        row = dict(con.execute("SELECT * FROM projects WHERE root=?", (str(root.resolve()),)).fetchone())
    assert prep._step_inventory(row)
    assert prep._step_hash(row)
    assert prep._step_lexical(row)
    with closing(prep._connect()) as con:
        ref = con.execute("SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
        indexed = con.execute("SELECT content_hash FROM source_index WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert tuple(ref) == (digest, 0)
    assert indexed[0] == digest
    assert prep._find_lexical_pending(str(root.resolve()), 10) == []
    with closing(prep._connect()) as con:
        row = dict(con.execute("SELECT * FROM projects WHERE root=?", (str(root.resolve()),)).fetchone())
    assert prep._step_inventory(row)
    with closing(prep._connect()) as con:
        ref = con.execute("SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
        indexed = con.execute("SELECT content_hash FROM source_index WHERE root=? AND path=?", (str(root.resolve()), "example.py")).fetchone()
    assert tuple(ref) == (digest, 0)
    assert indexed[0] == digest
    assert prep._find_lexical_pending(str(root.resolve()), 10) == []


def test_hash_retries_when_file_changes_during_snapshot_read(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "example.py"
    original = b"value = 1\n"
    current = b"value = 2\n"
    source.write_bytes(original)
    config = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": True}}
    repo = RepositoryTools(config)
    real_hash = repo._hash_file_only
    calls = 0

    def edit_after_first_read(path: Path) -> str:
        nonlocal calls
        digest = real_hash(path)
        calls += 1
        if calls == 1:
            source.write_bytes(current)
        return digest

    repo._hash_file_only = edit_after_first_read
    rag = MagicMock()
    rag.workspace_id.return_value = "workspace"
    prep = ProjectPreprocessor(config, services=MagicMock(), rag=rag, scheduler=MagicMock(), runtime=MagicMock(), repo_tools=repo)
    prep.register(str(root))
    prep._yield = lambda: False
    stat = source.stat()
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,1,1,?,0)",
            (str(root.resolve()), "example.py", hashlib.sha256(original).hexdigest(), stat.st_size, stat.st_mtime_ns, "old-card"),
        )
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,0)",
            (str(root.resolve()), "example.py", hashlib.sha256(original).hexdigest(), original.decode()),
        )
        con.execute(
            "INSERT INTO source_fts(root,path,content) VALUES(?,?,?)",
            (str(root.resolve()), "example.py", "example.py\n" + original.decode()),
        )
        con.commit()
        row = dict(con.execute("SELECT * FROM projects WHERE root=?", (str(root.resolve()),)).fetchone())

    assert prep._step_hash(row)

    with closing(prep._connect()) as con:
        actual = con.execute(
            "SELECT content_hash,needs_hash,card_key FROM file_refs WHERE root=? AND path=?",
            (str(root.resolve()), "example.py"),
        ).fetchone()
        stale_index = con.execute(
            "SELECT 1 FROM source_index WHERE root=? AND path=?",
            (str(root.resolve()), "example.py"),
        ).fetchone()
        stale_fts = con.execute(
            "SELECT 1 FROM source_fts WHERE root=? AND path=?",
            (str(root.resolve()), "example.py"),
        ).fetchone()
    assert tuple(actual) == (hashlib.sha256(current).hexdigest(), 0, None)
    assert stale_index is None
    assert stale_fts is None
    assert calls == 2


def test_rag_does_not_publish_cached_text_after_unwatched_edit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "example.py"
    old_text = "value = 1\n"
    current_text = "value = 2\n"
    source.write_text(current_text, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": True}}

    class CapturingRag:
        def __init__(self) -> None:
            self.indexed_overrides = None

        def workspace_id(self, _root):
            return "workspace"

        def index_paths_step(self, _root, *, workspace, paths, should_yield, content_overrides):
            self.indexed_overrides = content_overrides
            return {"success": True, "processed_paths": paths}

        def indexed_paths(self, *, workspace, paths):
            return set()

        def remove_paths(self, *, workspace, paths):
            return None

    rag = CapturingRag()
    prep = ProjectPreprocessor(config, services=MagicMock(), rag=rag, scheduler=MagicMock(), runtime=MagicMock(), repo_tools=RepositoryTools(config))
    prep.register(str(root))
    prep._yield = lambda: False
    resolved = str(root.resolve())
    old_hash = hashlib.sha256(old_text.encode()).hexdigest()
    stat = source.stat()
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,0,'',1,0)",
            (resolved, "example.py", old_hash, stat.st_size, stat.st_mtime_ns),
        )
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,0)",
            (resolved, "example.py", old_hash, old_text),
        )
        con.execute(
            "INSERT INTO source_fts(root,path,content) VALUES(?,?,?)",
            (resolved, "example.py", "example.py\n" + old_text),
        )
        con.commit()

    assert prep._step_rag({"root": resolved, "workspace": "workspace", "generation": 1})

    with closing(prep._connect()) as con:
        ref = con.execute(
            "SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?",
            (resolved, "example.py"),
        ).fetchone()
        source_index = con.execute(
            "SELECT 1 FROM source_index WHERE root=? AND path=?",
            (resolved, "example.py"),
        ).fetchone()
        source_fts = con.execute(
            "SELECT 1 FROM source_fts WHERE root=? AND path=?",
            (resolved, "example.py"),
        ).fetchone()
    assert tuple(ref) == (old_hash, 1)
    assert source_index is None
    assert source_fts is None
    assert rag.indexed_overrides is None

    assert prep._step_hash({"root": resolved, "generation": 1})
    assert prep._step_lexical({"root": resolved, "generation": 1})
    current_hash, _ = prep.repo_tools._read_snapshot(source)
    with closing(prep._connect()) as con:
        indexed = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (resolved, "example.py"),
        ).fetchone()
        fts = con.execute(
            "SELECT content FROM source_fts WHERE root=? AND path=?",
            (resolved, "example.py"),
        ).fetchone()
    assert tuple(indexed) == (current_hash, current_text.rstrip())
    assert fts[0] == "example.py\n" + current_text.rstrip()

    restarted = ProjectPreprocessor(config, services=MagicMock(), rag=rag, scheduler=MagicMock(), runtime=MagicMock(), repo_tools=RepositoryTools(config))
    with closing(restarted._connect()) as con:
        persisted = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (resolved, "example.py"),
        ).fetchone()
    assert tuple(persisted) == (current_hash, current_text.rstrip())


def test_same_relative_path_keeps_root_scoped_current_search_content(tmp_path: Path) -> None:
    roots = (tmp_path / "root-a", tmp_path / "root-b")
    texts = ("ROOT_A_MARKER = 'alpha'\n", "ROOT_B_MARKER = 'beta'\n")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": True}}
    rag = MagicMock()
    rag.workspace_id.side_effect = lambda root: str(root)
    prep = ProjectPreprocessor(
        config, services=MagicMock(), rag=rag, scheduler=MagicMock(),
        runtime=MagicMock(), repo_tools=RepositoryTools(config),
    )
    prep._yield = lambda: False

    for root, text in zip(roots, texts):
        root.mkdir()
        source = root / "example.py"
        source.write_text(text, encoding="utf-8")
        resolved = str(root.resolve())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        stat = source.stat()
        prep.register(resolved)
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,generation,updated_at) "
                "VALUES(?,?,?,?,?,0,1,0)",
                (resolved, "example.py", digest, stat.st_size, stat.st_mtime_ns),
            )
            con.commit()
        assert prep._step_lexical({"root": resolved, "generation": 1})

    repo = RepositoryTools(config)
    for root, own_text, other_text in (
        (roots[0], "ROOT_A_MARKER", "ROOT_B_MARKER"),
        (roots[1], "ROOT_B_MARKER", "ROOT_A_MARKER"),
    ):
        result = repo.search(str(root), own_text)
        assert result["success"] is True
        assert any(own_text in item["text"] for item in result["results"])
        assert all(other_text not in item["text"] for item in result["results"])

    restarted = ProjectPreprocessor(
        config, services=MagicMock(), rag=rag, scheduler=MagicMock(),
        runtime=MagicMock(), repo_tools=RepositoryTools(config),
    )
    with closing(restarted._connect()) as con:
        indexed = con.execute(
            "SELECT root,text FROM source_index WHERE path='example.py' ORDER BY root"
        ).fetchall()
    assert [(row["root"], row["text"]) for row in indexed] == [
        (str(root.resolve()), text.rstrip()) for root, text in sorted(zip(roots, texts), key=lambda pair: str(pair[0].resolve()))
    ]


def test_completed_project_reports_actual_coverage(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": True}}
    rag = MagicMock()
    rag.workspace_id.return_value = "workspace"
    prep = ProjectPreprocessor(config, services=MagicMock(), rag=rag, scheduler=MagicMock(), runtime=MagicMock(), repo_tools=RepositoryTools(config))
    prep.register(str(root))
    with closing(prep._connect()) as con:
        con.execute("UPDATE projects SET phase='complete', status='complete' WHERE root=?", (str(root.resolve()),))
        con.execute("INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,generation,updated_at) VALUES(?,?,?,1,1,0,1,0)", (str(root.resolve()), "example.py", "digest"))
        con.commit()
    prep._status_cache.clear()
    project = prep.status(str(root))["projects"][0]
    assert project["files"] == 1, project
    assert project["hashed_files"] == 1
    assert project["rag_files"] == 0
    assert project["file_cards"] == 0
