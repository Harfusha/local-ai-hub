import time
from pathlib import Path
import pytest
from local_ai_hub.preprocess_ingest import SinglePassIngestCache, IngestedFile
from local_ai_hub.repo_tools import RepositoryTools


def test_single_pass_ingest_caches_and_avoids_repeated_reads(tmp_path: Path):
    f = tmp_path / "hello.py"
    f.write_text("x = 1\ny = 2\n", encoding="utf-8")
    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)

    ingested1 = cache.get_or_ingest(tmp_path, "hello.py", tools)
    assert isinstance(ingested1, IngestedFile)
    assert ingested1.content_hash != ""
    assert ingested1.text == "x = 1\ny = 2"
    assert ingested1.lines == ("x = 1", "y = 2")
    assert ingested1.ast_tree is not None

    # Modify file on disk without invalidating cache
    f.write_text("x = 999\n", encoding="utf-8")
    ingested2 = cache.get_or_ingest(tmp_path, "hello.py", tools)
    # Should return cached version
    assert ingested2.text == "x = 1\ny = 2"
    assert ingested1 is ingested2

    # Invalidate and re-read
    cache.invalidate("hello.py", root=str(tmp_path))
    tools.invalidate_snapshot(f)
    ingested3 = cache.get_or_ingest(tmp_path, "hello.py", tools)
    assert ingested3.text == "x = 999"


@pytest.mark.parametrize('source,valid', [('x = 1\n', True), ('def broken(:\n', False)])
def test_text_only_ingest_defers_ast_until_default_request(tmp_path, monkeypatch, source, valid):
    import local_ai_hub.preprocess_ingest as module

    (tmp_path / 'lazy.py').write_text(source, encoding='utf-8')
    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)
    calls = []
    real_parse = module.ast.parse

    def parse(*args, **kwargs):
        calls.append(1)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(module.ast, 'parse', parse)
    item = cache.get_or_ingest(tmp_path, 'lazy.py', tools, parse_ast=False)
    assert item.ast_tree is None
    assert calls == []
    eager = cache.get_or_ingest(tmp_path, 'lazy.py', tools)
    assert eager is item
    assert (eager.ast_tree is not None) is valid
    assert len(calls) == 1
    assert cache.get_or_ingest(tmp_path, 'lazy.py', tools) is item
    assert len(calls) == 1


def test_deferred_ast_still_resolves_on_demand_imports(tmp_path):
    from local_ai_hub.code_index_demand import one_hop_related_files

    package = tmp_path / 'pkg'
    package.mkdir()
    (package / 'a.py').write_text('from . import b\n', encoding='utf-8')
    (package / 'b.py').write_text('value = 1\n', encoding='utf-8')
    tools = RepositoryTools({})
    cache = SinglePassIngestCache()
    item = cache.get_or_ingest(tmp_path, 'pkg/a.py', tools, parse_ast=False)
    assert item.ast_tree is None
    found = one_hop_related_files(tmp_path, ['pkg/a.py'], {'pkg/a.py', 'pkg/b.py'}, tools, ingest_cache=cache)
    assert found == ['pkg/b.py']
    assert item.ast_tree is not None


def test_lexical_step_indexes_text_without_parsing_python_ast(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    import hashlib
    import sqlite3
    import threading
    import local_ai_hub.preprocess_ingest as module
    from local_ai_hub.preprocess import ProjectPreprocessor

    source = tmp_path / 'a.py'
    source.write_text('x = 1\n', encoding='utf-8')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    db = tmp_path / 'index.db'
    with closing(sqlite3.connect(db)) as con:
        con.execute('CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER)')
        con.execute('CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT, updated_at REAL, PRIMARY KEY(root,path))')
        con.execute('CREATE TABLE source_fts(root TEXT, path TEXT, content TEXT)')
        con.execute('INSERT INTO file_refs VALUES(?,?,?,0)', (str(tmp_path), 'a.py', digest))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    calls = []
    real_parse = module.ast.parse
    monkeypatch.setattr(module.ast, 'parse', lambda *a, **kw: (calls.append(1), real_parse(*a, **kw))[1])
    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre.cfg, pre.deterministic = {}, None
    pre._connect = connect
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats, pre._record_progress = {}, lambda *a: None
    pre.repo_tools = RepositoryTools({})
    pre.ingest_cache = SinglePassIngestCache()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pre._cpu_pool = pool
        assert pre._step_lexical({'root': str(tmp_path)}) is True
    assert calls == []
    with closing(connect()) as con:
        assert con.execute('SELECT content_hash,text FROM source_index').fetchone()[:] == (digest, 'x = 1')
    assert pre.ingest_cache.get('a.py', root=str(tmp_path)).ast_tree is None


def test_text_only_leader_and_ast_waiter_share_ingest(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    (tmp_path / 'a.py').write_text('x = 1\n', encoding='utf-8')
    tools, cache = RepositoryTools({}), SinglePassIngestCache()
    entered, release, waiter_started = threading.Event(), threading.Event(), threading.Event()
    real_read = tools._read_snapshot
    reads = []

    def blocked_read(*args, **kwargs):
        reads.append(1)
        entered.set()
        assert release.wait(5)
        return real_read(*args, **kwargs)

    def eager():
        waiter_started.set()
        return cache.get_or_ingest(tmp_path, 'a.py', tools)

    monkeypatch.setattr(tools, '_read_snapshot', blocked_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_ingest, tmp_path, 'a.py', tools, parse_ast=False)
        assert entered.wait(5)
        second = pool.submit(eager)
        assert waiter_started.wait(5)
        release.set()
        lazy_item, eager_item = first.result(timeout=5), second.result(timeout=5)
    assert reads == [1]
    assert eager_item is lazy_item
    assert eager_item.ast_tree is not None


def test_concurrent_ast_requests_share_one_parse(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import local_ai_hub.preprocess_ingest as module

    (tmp_path / 'a.py').write_text('x = 1\n', encoding='utf-8')
    tools, cache = RepositoryTools({}), SinglePassIngestCache()
    item = cache.get_or_ingest(tmp_path, 'a.py', tools, parse_ast=False)
    gate = threading.Barrier(5)
    entered, repeated, release = threading.Event(), threading.Event(), threading.Event()
    calls = []
    real_parse = module.ast.parse

    def blocked_parse(*args, **kwargs):
        calls.append(1)
        entered.set()
        if len(calls) > 1:
            repeated.set()
        assert release.wait(5)
        return real_parse(*args, **kwargs)

    def request():
        gate.wait(timeout=5)
        return cache.get_with_ast('a.py', root=str(tmp_path))

    monkeypatch.setattr(module.ast, 'parse', blocked_parse)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(request) for _ in range(4)]
        gate.wait(timeout=5)
        assert entered.wait(5)
        repeated.wait(0.5)
        release.set()
        results = [f.result(timeout=5) for f in futures]
    assert calls == [1]
    assert all(result is item and result.ast_tree is not None for result in results)


def test_ast_lock_timeout_parses_without_releasing_an_unowned_lock(tmp_path):
    (tmp_path / 'a.py').write_text('x = 1\n', encoding='utf-8')
    tools, cache = RepositoryTools({}), SinglePassIngestCache()
    item = cache.get_or_ingest(tmp_path, 'a.py', tools, parse_ast=False)
    waits = []

    class TimedOutLock:
        def acquire(self, timeout):
            waits.append(timeout)
            return False

        def release(self):
            raise AssertionError('unowned lock must not be released')

    item._ast_lock = TimedOutLock()
    assert cache.get_with_ast('a.py', root=str(tmp_path)) is item
    assert item.ast_tree is not None
    assert waits == [30.0]


@pytest.mark.parametrize('eager_ingest', [False, True])
def test_invalidation_during_ast_parse_does_not_restore_old_cache_entry(tmp_path, monkeypatch, eager_ingest):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import local_ai_hub.preprocess_ingest as module

    path = tmp_path / 'a.py'
    path.write_text('x = 1\n', encoding='utf-8')
    tools, cache = RepositoryTools({}), SinglePassIngestCache()
    old = cache.get_or_ingest(tmp_path, 'a.py', tools, parse_ast=False)
    entered, release = threading.Event(), threading.Event()
    real_parse = module.ast.parse

    def blocked_parse(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(module.ast, 'parse', blocked_parse)
    with ThreadPoolExecutor(max_workers=1) as pool:
        if eager_ingest:
            pending = pool.submit(cache.get_or_ingest, tmp_path, 'a.py', tools)
        else:
            pending = pool.submit(cache.get_with_ast, 'a.py', root=str(tmp_path))
        assert entered.wait(5)
        cache.invalidate('a.py', root=str(tmp_path))
        tools.invalidate_snapshot(path)
        path.write_text('x = 222\n', encoding='utf-8')
        current = cache.get_or_ingest(tmp_path, 'a.py', tools, parse_ast=False)
        release.set()
        assert pending.result(timeout=5) is (current if eager_ingest else None)
    assert current is not old
    assert current.text == 'x = 222'
    assert (current.ast_tree is not None) is eager_ingest
    assert cache.get('a.py', root=str(tmp_path)) is current


def test_demand_reloads_source_if_invalidated_during_ast_parse(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import local_ai_hub.preprocess_ingest as module
    from local_ai_hub.code_index_demand import one_hop_related_files

    package = tmp_path / 'pkg'
    package.mkdir()
    source = package / 'a.py'
    source.write_text('from . import b\n', encoding='utf-8')
    for name in ('b.py', 'c.py'):
        (package / name).write_text('value = 1\n', encoding='utf-8')
    tools, cache = RepositoryTools({}), SinglePassIngestCache()
    cache.get_or_ingest(tmp_path, 'pkg/a.py', tools, parse_ast=False)
    entered, release = threading.Event(), threading.Event()
    real_parse = module.ast.parse

    def blocked_parse(text, *args, **kwargs):
        if text == 'from . import b':
            entered.set()
            assert release.wait(5)
        return real_parse(text, *args, **kwargs)

    monkeypatch.setattr(module.ast, 'parse', blocked_parse)
    eligible = {'pkg/a.py', 'pkg/b.py', 'pkg/c.py'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(one_hop_related_files, tmp_path, ['pkg/a.py'], eligible, tools, ingest_cache=cache)
        assert entered.wait(5)
        cache.invalidate('pkg/a.py', root=str(tmp_path))
        tools.invalidate_snapshot(source)
        source.write_text('from . import c\n', encoding='utf-8')
        release.set()
        assert pending.result(timeout=5) == ['pkg/c.py']


def test_single_pass_ingest_lru_bounds(tmp_path: Path):
    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=3)
    for i in range(5):
        p = tmp_path / f"file_{i}.txt"
        p.write_text(f"content {i}\n", encoding="utf-8")
        cache.get_or_ingest(tmp_path, f"file_{i}.txt", tools)

    assert len(cache) <= 3
    # file_0 and file_1 should have been evicted
    assert cache.has("file_4.txt")
    assert cache.has("file_3.txt")


def test_single_pass_ingest_concurrent_single_flight(tmp_path: Path):
    import concurrent.futures
    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)
    p = tmp_path / "shared.py"
    p.write_text("shared_var = 42\n", encoding="utf-8")

    read_count = 0
    original_read = tools._read_snapshot

    def counting_read(target, **kwargs):
        nonlocal read_count
        read_count += 1
        time.sleep(0.05)  # simulate disk read latency
        return original_read(target, **kwargs)

    tools._read_snapshot = counting_read

    def worker():
        return cache.get_or_ingest(tmp_path, "shared.py", tools)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(worker) for _ in range(5)]
        results = [f.result() for f in futures]

    assert len(results) == 5
    assert all(r is results[0] for r in results)
    # Single-flight should have coalesced concurrent calls so disk was only read once
    assert read_count == 1

