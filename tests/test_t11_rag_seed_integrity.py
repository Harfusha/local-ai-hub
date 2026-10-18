from __future__ import annotations

import sqlite3
import time
import json
import os
import subprocess
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.rag import RAGStore
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.hardware import profile_overrides


class _Rag:
    def workspace_id(self, _root: str) -> str:
        return "test-workspace"


class _Scheduler:
    def background_allowed(self) -> bool:
        return True

    def foreground_busy(self) -> bool:
        return False


class _SyntheticEmbeddingServices:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []
        self.embedded_items = 0

    def embed(self, texts, *, query: bool = False, **_kwargs):
        batch = list(texts)
        self.batch_sizes.append(len(batch))
        self.embedded_items += len(batch)
        return {
            "success": True,
            "embeddings": [[1.0, float(index % 7 + 1)] for index, _text in enumerate(batch)],
            "embedding_space_id": "synthetic-benchmark-v1",
        }


@pytest.fixture
def preprocessor_factory():
    instances: list[ProjectPreprocessor] = []

    def create(state_dir: Path) -> tuple[ProjectPreprocessor, RepositoryTools]:
        config = {
            "server": {"state_dir": str(state_dir)},
            "preprocessing": {"enabled": False, "discover_worktrees": False},
        }
        repo_tools = RepositoryTools(config)
        pre = ProjectPreprocessor(
            config,
            services=None,
            rag=_Rag(),
            scheduler=_Scheduler(),
            runtime=None,
            repo_tools=repo_tools,
        )
        instances.append(pre)
        return pre, repo_tools

    yield create
    for pre in instances:
        pre.close()


def _insert_parent_ref(
    pre: ProjectPreprocessor,
    root: str,
    path: Path,
    digest: str,
    *,
    card_key: str = "parent-card",
    rag_hash: str = "parent-rag-hash",
) -> None:
    stat = path.stat()
    now = time.time()
    with closing(pre._connect()) as con:
        con.execute(
            """INSERT INTO file_refs(
                root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at
            ) VALUES(?,?,?,?,?,0,?,1,?,?)""",
            (root, path.name, digest, stat.st_size, stat.st_mtime_ns, rag_hash, card_key, now),
        )
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
            (root, path.name, digest, path.read_text(encoding="utf-8"), now),
        )
        con.commit()


def _insert_child_ref(
    pre: ProjectPreprocessor,
    root: str,
    path: Path,
    *,
    digest: str = "child-hash",
    card_key: str = "child-card",
    rag_hash: str = "child-rag-hash",
) -> None:
    stat = path.stat()
    now = time.time()
    with closing(pre._connect()) as con:
        con.execute(
            """INSERT INTO file_refs(
                root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at
            ) VALUES(?,?,?,?,?,0,?,2,?,?)""",
            (root, path.name, digest, stat.st_size, stat.st_mtime_ns, rag_hash, card_key, now),
        )
        con.commit()


def test_parent_seed_reuses_only_matching_file_cache_and_never_rag_hash(tmp_path: Path, preprocessor_factory) -> None:
    pre, repo_tools = preprocessor_factory(tmp_path / "state")
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    parent_file = parent / "module.py"
    child_file = child / "module.py"
    content = "value = 'same'\n"
    parent_file.write_text(content, encoding="utf-8")
    child_file.write_text(content, encoding="utf-8")
    digest = repo_tools._hash_file_only(parent_file)
    _insert_parent_ref(pre, pre._root(str(parent)), parent_file, digest)

    stats = pre._seed_from_parent(str(child), str(parent))

    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT content_hash,card_key,rag_hash FROM file_refs WHERE root=? AND path=?",
            (pre._root(str(child)), "module.py"),
        ).fetchone()
        source = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (pre._root(str(child)), "module.py"),
        ).fetchone()
    assert stats["file_refs"] == 1
    assert row is not None
    assert row["content_hash"] == digest
    assert row["card_key"] == "parent-card"
    assert row["rag_hash"] in (None, "")
    assert source is not None
    assert source["content_hash"] == digest
    assert source["text"] == content


def test_parent_seed_uses_actual_same_head_worktree_blobs_and_rejects_dirty_child(
    tmp_path: Path, preprocessor_factory
) -> None:
    pre, repo_tools = preprocessor_factory(tmp_path / "state")
    parent = tmp_path / "parent"
    child = tmp_path / "worktrees" / "feature"
    parent.mkdir()
    child.parent.mkdir()

    def git(root: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(parent, "init", "--quiet")
    git(parent, "config", "user.email", "test@example.invalid")
    git(parent, "config", "user.name", "Test")
    parent_file = parent / "module.py"
    parent_file.write_text("value = 1\n", encoding="utf-8")
    git(parent, "add", "module.py")
    git(parent, "commit", "--quiet", "-m", "seed baseline")
    git(parent, "worktree", "add", "--quiet", "--detach", str(child), "HEAD")

    parent_head = git(parent, "rev-parse", "HEAD")
    assert git(child, "rev-parse", "HEAD") == parent_head
    parent_root = pre._root(str(parent))
    child_root = pre._root(str(child))
    parent_hash = repo_tools.git_blob_map(parent_root)["module.py"]
    assert parent_hash.startswith("git:")
    _insert_parent_ref(pre, parent_root, parent_file, parent_hash)

    seeded = pre._seed_from_parent(child_root, parent_root)

    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT content_hash,needs_hash,rag_hash,card_key FROM file_refs WHERE root=? AND path=?",
            (child_root, "module.py"),
        ).fetchone()
        source = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (child_root, "module.py"),
        ).fetchone()
    assert seeded["file_refs"] == 1
    assert row["content_hash"] == parent_hash
    assert row["needs_hash"] == 0
    assert row["rag_hash"] in (None, "")
    assert row["card_key"] == "parent-card"
    assert source["text"] == parent_file.read_text(encoding="utf-8")

    child_file = child / "module.py"
    child_file.write_text("value = 2\n", encoding="utf-8")
    assert child_file.stat().st_size == parent_file.stat().st_size
    rejected = pre._seed_from_parent(child_root, parent_root)

    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT content_hash,needs_hash,rag_hash,card_key FROM file_refs WHERE root=? AND path=?",
            (child_root, "module.py"),
        ).fetchone()
        source = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (child_root, "module.py"),
        ).fetchone()
    assert rejected["file_refs"] == 0
    assert git(child, "rev-parse", "HEAD") == parent_head
    assert row["content_hash"] == ""
    assert row["needs_hash"] == 1
    assert row["rag_hash"] in (None, "")
    assert row["card_key"] is None
    assert source is None


def test_parent_seed_rejects_same_size_dirty_child_and_stale_source_text(tmp_path: Path, preprocessor_factory) -> None:
    pre, repo_tools = preprocessor_factory(tmp_path / "state")
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    parent_file = parent / "module.py"
    child_file = child / "module.py"
    parent_file.write_text("value = 1\n", encoding="utf-8")
    child_file.write_text("value = 2\n", encoding="utf-8")
    assert parent_file.stat().st_size == child_file.stat().st_size
    digest = repo_tools._hash_file_only(parent_file)
    _insert_parent_ref(pre, pre._root(str(parent)), parent_file, digest)

    pre._seed_from_parent(str(child), str(parent))

    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT content_hash,card_key,rag_hash FROM file_refs WHERE root=? AND path=?",
            (pre._root(str(child)), "module.py"),
        ).fetchone()
        source = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (pre._root(str(child)), "module.py"),
        ).fetchone()
    assert row is None
    assert source is None


def test_parent_seed_invalidates_previously_inherited_state_for_dirty_child(tmp_path: Path, preprocessor_factory) -> None:
    pre, repo_tools = preprocessor_factory(tmp_path / "state")
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    parent_file = parent / "module.py"
    child_file = child / "module.py"
    parent_file.write_text("value = 1\n", encoding="utf-8")
    child_file.write_text("value = 2\n", encoding="utf-8")
    assert parent_file.stat().st_size == child_file.stat().st_size
    digest = repo_tools._hash_file_only(parent_file)
    parent_root = pre._root(str(parent))
    child_root = pre._root(str(child))
    _insert_parent_ref(pre, parent_root, parent_file, digest)
    _insert_child_ref(
        pre,
        child_root,
        child_file,
        digest=digest,
        card_key="parent-card",
        rag_hash="parent-rag-hash",
    )
    with closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
            (child_root, child_file.name, digest, "stale parent text", time.time()),
        )
        con.commit()

    pre._seed_from_parent(child_root, parent_root)

    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT content_hash,needs_hash,card_key,rag_hash FROM file_refs WHERE root=? AND path=?",
            (child_root, child_file.name),
        ).fetchone()
        source = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (child_root, child_file.name),
        ).fetchone()
    assert row["content_hash"] == ""
    assert row["needs_hash"] == 1
    assert row["card_key"] is None
    assert row["rag_hash"] in (None, "")
    assert source is None


def test_parallel_parent_seed_is_idempotent_and_preserves_existing_child_row(tmp_path: Path, preprocessor_factory) -> None:
    state = tmp_path / "state"
    pre_a, repo_tools = preprocessor_factory(state)
    pre_b, _ = preprocessor_factory(state)
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    parent_file = parent / "module.py"
    child_file = child / "module.py"
    content = "value = 'same'\n"
    parent_file.write_text(content, encoding="utf-8")
    child_file.write_text(content, encoding="utf-8")
    digest = repo_tools._hash_file_only(parent_file)
    parent_root = pre_a._root(str(parent))
    child_root = pre_a._root(str(child))
    _insert_parent_ref(pre_a, parent_root, parent_file, digest)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pre: pre._seed_from_parent(child_root, parent_root),
            (pre_a, pre_b),
        ))

    with closing(pre_a._connect()) as con:
        rows = con.execute(
            "SELECT content_hash,card_key,rag_hash FROM file_refs WHERE root=? AND path=?",
            (child_root, "module.py"),
        ).fetchall()
    assert len(rows) == 1
    assert sum(result["file_refs"] for result in results) == 1
    assert rows[0]["content_hash"] == digest
    assert rows[0]["card_key"] == "parent-card"
    assert rows[0]["rag_hash"] in (None, "")

    with closing(pre_a._connect()) as con:
        con.execute(
            """UPDATE file_refs SET content_hash='child-hash',card_key='child-card',rag_hash='child-rag-hash'
               WHERE root=? AND path=?""",
            (child_root, child_file.name),
        )
        con.commit()
    preserved = pre_a._seed_from_parent(child_root, parent_root)
    with closing(pre_a._connect()) as con:
        row = con.execute(
            "SELECT content_hash,card_key,rag_hash FROM file_refs WHERE root=? AND path=?",
            (child_root, "module.py"),
        ).fetchone()
    assert preserved["file_refs"] == 0
    assert row["content_hash"] == "child-hash"
    assert row["card_key"] == "child-card"
    assert row["rag_hash"] == "child-rag-hash"


def test_tenant_shaped_rag_schema_requires_offline_conversion(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "rag.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """CREATE TABLE chunks(
                tenant TEXT NOT NULL, workspace TEXT NOT NULL, path TEXT NOT NULL,
                chunk_no INTEGER NOT NULL, content_hash TEXT NOT NULL, text TEXT NOT NULL,
                embedding TEXT NOT NULL, embedding_space TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(tenant,workspace,path,chunk_no)
            )"""
        )
        con.execute(
            "INSERT INTO chunks VALUES('legacy-owner','repo:one','old.py',0,'old-hash','old text','[1.0,0.0]','space')"
        )
        con.execute(
            """CREATE TABLE files(
                tenant TEXT NOT NULL, workspace TEXT NOT NULL, path TEXT NOT NULL,
                mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, content_hash TEXT NOT NULL,
                PRIMARY KEY(tenant,workspace,path)
            )"""
        )

    store_config = {
        "server": {"state_dir": str(state_dir)},
        "models": {},
        "cpu_retrieval": {},
        "workspace_cache": {},
        "rag": {},
        "features": {"reranker": False},
    }
    with pytest.raises(RuntimeError, match="explicit offline conversion required"):
        RAGStore(store_config)

    with closing(sqlite3.connect(db_path)) as con:
        row = con.execute("SELECT tenant,workspace,path,text FROM chunks").fetchone()
        columns = {str(item[1]) for item in con.execute("PRAGMA table_info(chunks)")}
    assert row == ("legacy-owner", "repo:one", "old.py", "old text")
    assert "tenant" in columns


def test_incremental_same_size_edit_clears_card_and_rag_hash(tmp_path: Path, preprocessor_factory) -> None:
    pre, repo_tools = preprocessor_factory(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    digest = repo_tools._hash_file_only(path)
    stat = path.stat()
    now = time.time()
    root = pre._root(str(repo))
    with closing(pre._connect()) as con:
        con.execute(
            """INSERT INTO file_refs(
                root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at
            ) VALUES(?,?,?,?,?,0,?,1,?,?)""",
            (root, path.name, digest, stat.st_size, stat.st_mtime_ns, digest, "old-card", now),
        )
        con.execute(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
            (root, path.name, digest, "value = 1\n", now),
        )
        con.commit()

    path.write_text("value = 2\n", encoding="utf-8")
    assert path.stat().st_size == stat.st_size
    pre._step_incremental_inventory({"root": root, "generation": 1}, {"module.py"})

    with closing(pre._connect()) as con:
        row = con.execute(
            "SELECT content_hash,card_key,rag_hash FROM file_refs WHERE root=? AND path=?",
            (root, path.name),
        ).fetchone()
        source = con.execute(
            "SELECT content_hash,text FROM source_index WHERE root=? AND path=?",
            (root, path.name),
        ).fetchone()
    assert row["content_hash"] == repo_tools._hash_file_only(path)
    assert row["card_key"] is None
    assert row["rag_hash"] in (None, "")
    assert source is None


def test_t11_ingestion_batch_benchmark(tmp_path: Path, preprocessor_factory) -> None:
    if os.environ.get("T11_RAG_BENCHMARK") != "1":
        pytest.skip("set T11_RAG_BENCHMARK=1 to run synthetic RAG batch and seed measurements")

    file_count = 128
    seed_state = tmp_path / "seed-state"
    seed_pre, seed_repo_tools = preprocessor_factory(seed_state)
    parent = tmp_path / "seed-parent"
    child = tmp_path / "seed-child"
    parent.mkdir()
    child.mkdir()
    parent_root = seed_pre._root(str(parent))
    child_root = seed_pre._root(str(child))
    seed_rows = []
    source_rows = []
    now = time.time()
    for index in range(file_count):
        rel = f"doc-{index:03}.py"
        parent_file = parent / rel
        child_file = child / rel
        content = f"def doc_{index}():\n    return 'seed benchmark {index}'\n"
        parent_file.write_text(content, encoding="utf-8")
        child_file.write_text(content, encoding="utf-8")
        digest = seed_repo_tools._hash_file_only(parent_file)
        stat = parent_file.stat()
        seed_rows.append((parent_root, rel, digest, stat.st_size, stat.st_mtime_ns, 0, None, 1, f"card-{index}", now))
        source_rows.append((parent_root, rel, digest, content, now))
    with closing(seed_pre._connect()) as con:
        con.executemany(
            """INSERT INTO file_refs(
                root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            seed_rows,
        )
        con.executemany(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
            source_rows,
        )
        con.commit()
    tracemalloc.start()
    seed_started = time.perf_counter()
    seeded = seed_pre._seed_from_parent(child_root, parent_root)
    seed_elapsed = time.perf_counter() - seed_started
    _, seed_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert seeded["file_refs"] == file_count

    integrated = profile_overrides(
        "integrated", {"ram": {"total_gb": 16.0, "available_gb": 8.0}, "gpus": []}
    )
    batch_cases = (("explicit-128", 128), ("integrated-profile", int(integrated["preprocessing"]["rag_files_per_step"])))
    measurements = []
    for label, files_per_step in batch_cases:
        state_dir = tmp_path / label / "state"
        root = tmp_path / label / "repo"
        state_dir.mkdir(parents=True)
        root.mkdir(parents=True)
        service = _SyntheticEmbeddingServices()
        rag_config = {
            "server": {"state_dir": str(state_dir)},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 1024, "chunk_overlap_chars": 0},
            "features": {"reranker": False},
        }
        rag = RAGStore(rag_config, service)
        pre_config = {
            "server": {"state_dir": str(state_dir)},
            "preprocessing": {"enabled": False, "rag_files_per_step": files_per_step},
        }
        repo_tools = RepositoryTools(pre_config)
        pre = ProjectPreprocessor(
            pre_config, services=None, rag=rag, scheduler=_Scheduler(), runtime=None, repo_tools=repo_tools
        )
        repo_root = pre._root(str(root))
        workspace = rag.workspace_id(repo_root)
        file_rows = []
        lexical_rows = []
        for index in range(file_count):
            rel = f"doc-{index:03}.py"
            path = root / rel
            content = f"def doc_{index}():\n    return 'rag batch benchmark {index}'\n"
            path.write_text(content, encoding="utf-8")
            digest = repo_tools._hash_file_only(path)
            stat = path.stat()
            file_rows.append((repo_root, rel, digest, stat.st_size, stat.st_mtime_ns, 0, None, 1, now))
            lexical_rows.append((repo_root, rel, digest, content, now))
        with closing(pre._connect()) as con:
            con.executemany(
                """INSERT INTO file_refs(
                    root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                file_rows,
            )
            con.executemany(
                "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
                lexical_rows,
            )
            con.commit()

        steps = 0
        tracemalloc.start()
        started = time.perf_counter()
        while True:
            pre._step_rag({"root": repo_root, "workspace": workspace, "generation": 1})
            steps += 1
            with closing(pre._connect()) as con:
                pending = int(con.execute(
                    "SELECT COUNT(*) FROM file_refs WHERE root=? AND COALESCE(rag_hash,'')<>content_hash",
                    (repo_root,),
                ).fetchone()[0])
            if pending == 0:
                break
            assert steps <= file_count
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append({
            "label": label,
            "files_per_step": files_per_step,
            "files": file_count,
            "steps": steps,
            "elapsed_ms": round(elapsed * 1000.0, 3),
            "files_per_second": round(file_count / max(elapsed, 1e-9), 2),
            "peak_traced_mib": round(peak / (1024 * 1024), 3),
            "embed_calls": len(service.batch_sizes),
            "max_embed_batch": max(service.batch_sizes, default=0),
            "embedded_items": service.embedded_items,
            "backend": "synthetic deterministic embedder; not model throughput",
        })
        assert steps == (file_count + files_per_step - 1) // files_per_step
        assert service.embedded_items == file_count
        assert max(service.batch_sizes, default=0) <= files_per_step
        pre.close()

    print("T11_RAG_INGEST_BENCHMARK=" + json.dumps({
        "seed": {
            "files": file_count,
            "inserted": seeded["file_refs"],
            "elapsed_ms": round(seed_elapsed * 1000.0, 3),
            "files_per_second": round(file_count / max(seed_elapsed, 1e-9), 2),
            "peak_traced_mib": round(seed_peak / (1024 * 1024), 3),
        },
        "rag_batches": measurements,
    }, sort_keys=True))
