from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.preprocess_ingest import SinglePassIngestCache
from local_ai_hub.repo_tools import RepositoryTools


def test_cache_key_includes_content_hash(tmp_path: Path):
    cache = SinglePassIngestCache(max_entries=10)
    root_str = str(tmp_path)
    h1 = "1111111111111111111111111111111111111111111111111111111111111111"
    h2 = "2222222222222222222222222222222222222222222222222222222222222222"

    key_with_hash = cache._key("module.py", root=root_str, content_hash=h1)
    assert h1 in key_with_hash
    assert "module.py" in key_with_hash

    # Put version 1
    cache.put("module.py", text="v1_content", content_hash=h1, root=root_str)

    # Lookup with matching hash succeeds
    item1 = cache.get("module.py", root=root_str, content_hash=h1)
    assert item1 is not None
    assert item1.content_hash == h1
    assert cache.has("module.py", root=root_str, content_hash=h1) is True

    # Lookup with mismatching hash returns None
    assert cache.get("module.py", root=root_str, content_hash=h2) is None
    assert cache.has("module.py", root=root_str, content_hash=h2) is False

    # Invalidate by root and path removes it
    cache.invalidate("module.py", root=root_str)
    assert cache.has("module.py", root=root_str, content_hash=h1) is False


def test_put_evicts_stale_hash_for_same_path_and_root(tmp_path: Path):
    cache = SinglePassIngestCache(max_entries=10)
    root_str = str(tmp_path)
    text1 = "def f(): return 1\n"
    text2 = "def f(): return 2\n"
    h1 = hashlib.sha256(text1.encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(text2.encode("utf-8")).hexdigest()

    cache.put("func.py", text=text1, content_hash=h1, root=root_str)
    assert len(cache) == 1
    assert cache.get("func.py", root=root_str, content_hash=h1) is not None

    # Put updated version 2 for the same file in same root
    cache.put("func.py", text=text2, content_hash=h2, root=root_str)
    assert len(cache) == 1
    assert cache.get("func.py", root=root_str, content_hash=h1) is None
    item2 = cache.get("func.py", root=root_str, content_hash=h2)
    assert item2 is not None
    assert item2.text == text2


def test_cross_root_isolation_with_identical_filenames(tmp_path: Path):
    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    (proj_a / "index.py").write_text("APP = 'Alpha'\n", encoding="utf-8")
    (proj_b / "index.py").write_text("APP = 'Beta'\n", encoding="utf-8")

    ha = hashlib.sha256((proj_a / "index.py").read_bytes()).hexdigest()
    hb = hashlib.sha256((proj_b / "index.py").read_bytes()).hexdigest()

    cache = SinglePassIngestCache(max_entries=10)
    tools = RepositoryTools({})

    item_a = cache.get_or_ingest(proj_a, "index.py", tools)
    item_b = cache.get_or_ingest(proj_b, "index.py", tools)

    assert item_a.content_hash == ha
    assert item_b.content_hash == hb
    assert item_a.text.strip() == "APP = 'Alpha'"
    assert item_b.text.strip() == "APP = 'Beta'"

    # Cross-root query with specific hash
    assert cache.get("index.py", root=str(proj_a), content_hash=ha) is not None
    assert cache.get("index.py", root=str(proj_b), content_hash=ha) is None
    assert cache.get("index.py", root=str(proj_a), content_hash=hb) is None
    assert cache.get("index.py", root=str(proj_b), content_hash=hb) is not None


def test_get_or_ingest_with_expected_hash_invalidates_stale_cache(tmp_path: Path):
    f = tmp_path / "target.py"
    f.write_text("val = 1\n", encoding="utf-8")
    h1 = hashlib.sha256(f.read_bytes()).hexdigest()

    cache = SinglePassIngestCache(max_entries=10)
    tools = RepositoryTools({})

    ingested1 = cache.get_or_ingest(tmp_path, "target.py", tools, expected_hash=h1)
    assert ingested1.content_hash == h1

    # Modify file directly on disk without watcher
    f.write_text("val = 2\n", encoding="utf-8")
    h2 = hashlib.sha256(f.read_bytes()).hexdigest()

    # Requesting with expected_hash=h2 should miss cache, re-read and return fresh
    ingested2 = cache.get_or_ingest(tmp_path, "target.py", tools, expected_hash=h2)
    assert ingested2.content_hash == h2
    assert ingested2.text == "val = 2"
    assert cache.get("target.py", root=str(tmp_path), content_hash=h1) is None


def test_e2e_two_projects_shared_preprocessor_no_watcher_invalidation(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    import sqlite3
    import threading
    from local_ai_hub.preprocess import ProjectPreprocessor

    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    file_a = proj_a / "service.py"
    file_b = proj_b / "service.py"
    file_a.write_text("SERVICE = 'A_v1'\n", encoding="utf-8")
    file_b.write_text("SERVICE = 'B_v1'\n", encoding="utf-8")

    ha1 = hashlib.sha256(file_a.read_bytes()).hexdigest()
    hb1 = hashlib.sha256(file_b.read_bytes()).hexdigest()

    db_path = tmp_path / "test_pre.db"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE projects(root TEXT PRIMARY KEY, phase TEXT, generation INTEGER)")
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, rag_hash TEXT, card_key TEXT, needs_hash INTEGER, updated_at REAL, PRIMARY KEY(root, path))")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT, updated_at REAL, PRIMARY KEY(root, path))")
        con.execute("CREATE TABLE source_fts(root TEXT, path TEXT, content TEXT)")
        con.execute("CREATE TABLE content_cards(content_hash TEXT, analyzer_version TEXT, card_key TEXT)")
        con.execute("INSERT INTO projects VALUES(?, 'hash', 1)", (str(proj_a),))
        con.execute("INSERT INTO projects VALUES(?, 'hash', 1)", (str(proj_b),))
        con.execute("INSERT INTO file_refs VALUES(?, 'service.py', ?, '', NULL, 0, 0)", (str(proj_a), ha1))
        con.execute("INSERT INTO file_refs VALUES(?, 'service.py', ?, '', NULL, 0, 0)", (str(proj_b), hb1))
        con.commit()

    def connect():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre.cfg = {"hash_files_per_step": 10, "lexical_files_per_step": 10}
    pre.deterministic = None
    pre._connect = connect
    pre._db_lock = threading.RLock()
    pre._stats_lock = threading.RLock()
    pre._stats = {"hashed_files": 0}
    pre._record_progress = lambda *a: None
    pre.repo_tools = RepositoryTools({})
    pre.ingest_cache = SinglePassIngestCache()
    pre._hash_git_maps = {}
    pre._hash_git_maps_lock = threading.RLock()
    pre._set_project = lambda r, **kw: None
    pre._prune_missing_file_refs = lambda r: None

    with ThreadPoolExecutor(max_workers=2) as pool:
        pre._cpu_pool = pool
        pre._hash_pool = lambda: pool

        # Run lexical for project A
        assert pre._step_lexical({"root": str(proj_a)}) is True
        # Run lexical for project B
        assert pre._step_lexical({"root": str(proj_b)}) is True

        with closing(connect()) as con:
            row_a = con.execute("SELECT content_hash, text FROM source_index WHERE root=? AND path='service.py'", (str(proj_a),)).fetchone()
            row_b = con.execute("SELECT content_hash, text FROM source_index WHERE root=? AND path='service.py'", (str(proj_b),)).fetchone()
            assert row_a["content_hash"] == ha1
            assert "A_v1" in row_a["text"]
            assert row_b["content_hash"] == hb1
            assert "B_v1" in row_b["text"]

        # Modify project A file on disk without watcher event
        file_a.write_text("SERVICE = 'A_v2_updated'\n", encoding="utf-8")
        ha2 = hashlib.sha256(file_a.read_bytes()).hexdigest()

        # Mark needs_hash=1 for project A
        with closing(connect()) as con:
            con.execute("UPDATE file_refs SET needs_hash=1 WHERE root=? AND path='service.py'", (str(proj_a),))
            con.commit()

        # Run hash phase on project A
        assert pre._step_hash({"root": str(proj_a), "generation": 1}) is True

        # Ingest cache for A should be invalidated, but B's cache preserved
        assert pre.ingest_cache.get("service.py", root=str(proj_a), content_hash=ha1) is None
        assert pre.ingest_cache.get("service.py", root=str(proj_b), content_hash=hb1) is not None

        # Run lexical phase on project A
        assert pre._step_lexical({"root": str(proj_a)}) is True

        # Verify source_index for project A has updated content, and project B is untouched
        with closing(connect()) as con:
            row_a2 = con.execute("SELECT content_hash, text FROM source_index WHERE root=? AND path='service.py'", (str(proj_a),)).fetchone()
            row_b2 = con.execute("SELECT content_hash, text FROM source_index WHERE root=? AND path='service.py'", (str(proj_b),)).fetchone()
            assert row_a2["content_hash"] == ha2
            assert "A_v2_updated" in row_a2["text"]
            assert row_b2["content_hash"] == hb1
            assert "B_v1" in row_b2["text"]

