import sqlite3
import threading
from contextlib import closing

from local_ai_hub.preprocess import ProjectPreprocessor


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
