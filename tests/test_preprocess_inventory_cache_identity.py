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
