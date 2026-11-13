import sqlite3
import threading
from contextlib import closing

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.rag import RAGStore


def test_preemption_reduces_batch_until_progress_and_keeps_other_roots_independent(tmp_path):
    db = tmp_path / 'index.sqlite'
    roots = [tmp_path / 'one', tmp_path / 'two']
    with closing(sqlite3.connect(db)) as con:
        con.execute('CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)')
        con.execute('CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)')
        for root in roots:
            root.mkdir()
            for i in range(8):
                name = f'{i}.py'
                (root / name).write_text('text', encoding='utf-8')
                con.execute('INSERT INTO file_refs VALUES(?, ?, ?, 0, NULL, 0, 4, 0)', (str(root), name, name))
                con.execute('INSERT INTO source_index VALUES(?, ?, ?, ?)', (str(root), name, name, 'text'))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def __init__(self): self.batches = []
        def indexed_paths(self, *, workspace, paths): return set(paths)
        def prune_missing(self, root, workspace, all_paths): return 0
        def index_paths_step(self, root, *, workspace, paths, should_yield, content_overrides):
            self.batches.append((root, list(paths)))
            if len(paths) > 2:
                return {'success': True, 'preempted': True, 'processed_paths': []}
            return {'success': True, 'processed_paths': paths}

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {'rag_steps': 0}
    pre._connect, pre._yield = connect, lambda: False
    pre._record_progress = lambda *args: None
    pre._set_project = lambda *args, **kwargs: None
    pre._learned_priority_paths = lambda root: ()
    pre.cfg, pre.deterministic, pre.rag = {'rag_files_per_step': 8}, None, Rag()
    row = {'root': str(roots[0]), 'workspace': 'one'}

    assert pre._step_rag(row) is False
    assert pre._step_rag(row) is False
    assert pre._step_rag(row) is True
    assert [len(batch) for _, batch in pre.rag.batches] == [8, 4, 2]
    with closing(connect()) as con:
        assert con.execute('SELECT COUNT(*) FROM file_refs WHERE root=? AND rag_hash=content_hash', (str(roots[0]),)).fetchone()[0] == 2

    assert pre._step_rag({'root': str(roots[1]), 'workspace': 'two'}) is False
    assert len(pre.rag.batches[-1][1]) == 8

    for _ in range(3):
        assert pre._step_rag(row) is True
    assert pre._step_rag(row) is True  # No pending files: reset for the next pass.
    assert str(roots[0]) not in pre._rag_batch_limits
    assert pre._rag_batch_limits[str(roots[1])] == 4


def test_batch_recovers_after_sustained_progress(tmp_path):
    db = tmp_path / 'index.sqlite'
    root = tmp_path / 'repo'
    root.mkdir()
    with closing(sqlite3.connect(db)) as con:
        con.execute('CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)')
        con.execute('CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)')
        for i in range(20):
            name = f'{i:02}.py'
            (root / name).write_text('text', encoding='utf-8')
            con.execute('INSERT INTO file_refs VALUES(?, ?, ?, 0, NULL, 0, 4, 0)', (str(root), name, name))
            con.execute('INSERT INTO source_index VALUES(?, ?, ?, ?)', (str(root), name, name, 'text'))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def __init__(self): self.sizes = []
        def index_paths_step(self, root, *, workspace, paths, should_yield, content_overrides):
            self.sizes.append(len(paths))
            if len(self.sizes) <= 3 or len(self.sizes) == 9:
                return {'success': True, 'preempted': True, 'processed_paths': []}
            return {'success': True, 'processed_paths': paths}

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {'rag_steps': 0}
    pre._connect, pre._yield = connect, lambda: False
    pre._record_progress = lambda *args: None
    pre._learned_priority_paths = lambda root: ()
    pre.cfg, pre.deterministic, pre.rag = {'rag_files_per_step': 8}, None, Rag()
    row = {'root': str(root), 'workspace': 'repo'}
    for _ in range(14):
        pre._step_rag(row)
    assert pre.rag.sizes == [8, 4, 2, 1, 1, 1, 1, 2, 2, 1, 1, 1, 1, 2]
    pre._yield = lambda: True
    assert pre._step_rag(row) is False
    pre._yield = lambda: False
    for _ in range(3):
        assert pre._step_rag(row) is True
    assert pre._rag_batch_limits[str(root)] == 2
    assert pre._step_rag(row) is True
    assert pre._rag_batch_limits[str(root)] == 4


def test_scheduler_foreground_wait_resets_recovery_streak(monkeypatch):
    import local_ai_hub.preprocess as preprocess

    monkeypatch.setattr(preprocess, 'set_current_thread_priority', lambda _: None)
    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre.cfg = {'startup_delay_seconds': 0, 'poll_seconds': 0.2}
    pre.cpu_priority = 'normal'
    pre.cpu_runs_during_foreground = False
    pre._stop, pre._paused = threading.Event(), threading.Event()
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {'loops': 0}
    pre._rag_batch_limits = {'one': 2, 'two': 4}
    pre._rag_batch_successes = {'one': 3, 'two': 2}
    pre._background_work_allowed = lambda: True
    pre._scheduler_background_allowed = lambda: False

    class Wake:
        def wait(self, timeout): pre._stop.set()
        def clear(self): pass

    pre._cpu_wakeup = Wake()
    pre._cpu_loop()
    assert pre._rag_batch_successes == {}
    assert pre._rag_batch_limits == {'one': 2, 'two': 4}


def test_removing_project_forgets_only_its_adaptive_batch_state():
    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._dirty_lock, pre._touch_lock = threading.RLock(), threading.RLock()
    pre._step_locks_guard, pre._hash_git_maps_lock = threading.RLock(), threading.RLock()
    pre._db_lock = threading.RLock()
    pre._dirty_paths, pre._watch_revisions, pre._last_touch = {}, {}, {}
    pre._step_locks, pre._hash_git_maps = {}, {}
    pre._missing_refs_checked_generations = set()
    pre._rag_batch_limits = {'one': 2, 'two': 4}
    pre._rag_batch_successes = {'one': 3, 'two': 1}

    pre._forget_project_runtime('one')

    assert pre._rag_batch_limits == {'two': 4}
    assert pre._rag_batch_successes == {'two': 1}
def test_real_rag_preemption_preserves_snapshot_and_reduces_batch(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    path = root / 'module.py'
    path.write_text('before = 1\n', encoding='utf-8')
    foreground = threading.Event()

    class Services:
        def __init__(self):
            self.calls = []

        def embed(self, texts, **_kwargs):
            batch = list(texts)
            self.calls.append(batch)
            if len(self.calls) == 2:
                foreground.set()
            return {'success': True, 'embedding_space_id': 'test-space',
                    'embeddings': [[0.25, 0.75] for _ in batch]}

    services = Services()
    rag = RAGStore({'server': {'state_dir': str(tmp_path / 'state')}, 'models': {},
                    'cpu_retrieval': {}, 'workspace_cache': {},
                    'rag': {'extensions': ['.py'], 'ignore_dirs': []}}, services)
    chunks = ['original chunk']
    monkeypatch.setattr(rag, '_chunks', lambda _text, path='': list(chunks))
    workspace = 'preemption-test'
    assert rag.index_paths_step(root=str(root), workspace=workspace, paths=['module.py'])['success']
    with closing(rag._connect()) as con:
        before = con.execute('SELECT chunk_no, text FROM chunks WHERE workspace=? ORDER BY chunk_no', (workspace,)).fetchall()

    path.write_text('after = 2\n', encoding='utf-8')
    chunks[:] = [f'replacement chunk {i}' for i in range(65)]
    db = tmp_path / 'index.sqlite'
    with closing(sqlite3.connect(db)) as con:
        con.execute('CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)')
        con.execute('CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)')
        con.execute('INSERT INTO file_refs VALUES(?, ?, ?, 0, NULL, 0, 10, 0)', (str(root), 'module.py', 'new-hash'))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {'rag_steps': 0}
    pre._connect, pre._yield = connect, foreground.is_set
    pre._record_progress = lambda *args: None
    pre._set_project = lambda *args, **kwargs: None
    pre._learned_priority_paths = lambda root: ()
    pre.cfg, pre.deterministic, pre.rag = {'rag_files_per_step': 8}, None, rag

    assert pre._step_rag({'root': str(root), 'workspace': workspace}) is False
    assert [len(batch) for batch in services.calls] == [1, 64]
    assert pre._rag_batch_limits[str(root)] == 4
    with closing(rag._connect()) as con:
        after = con.execute('SELECT chunk_no, text FROM chunks WHERE workspace=? ORDER BY chunk_no', (workspace,)).fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    with closing(connect()) as con:
        assert con.execute('SELECT rag_hash FROM file_refs').fetchone()[0] is None
