from contextlib import closing
from types import SimpleNamespace
import sys
import threading

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.operational_mode import publish_preprocessing_ready, set_operational_mode
from local_ai_hub.preprocess import PREPROCESS_ANALYZER_VERSION, ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def test_background_worker_fails_closed_when_mode_module_is_unavailable(monkeypatch):
    worker = object.__new__(IdleGPUWorker)
    worker.config = {"server": {"state_dir": "unused"}}
    worker.idle_seconds = 30.0
    monkeypatch.setitem(sys.modules, "local_ai_hub.operational_mode", SimpleNamespace())
    assert worker.ready() is False
    assert worker._configure_parallel_for_mode() is False
    assert worker._idle_grace() == 30.0
    worker._setup_lock = threading.RLock()
    worker._configure_parallel_for_mode = lambda: True
    result = worker.generate_many([{}], preprocessing=True)
    assert result[0]["success"] is False
    assert result[0]["error_code"] == "operational_mode_paused"


def test_unchanged_inventory_does_not_skip_pending_stub_enrichment(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "notes.md").write_text("A useful explanation of a project component.\n", encoding="utf-8")
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"enabled": False, "reject_temp_projects": False,
                             "exclusive": {"enrich_stub_cards": True}}}
    rag = SimpleNamespace(index_reset=False, workspace_id=lambda path: "workspace")
    prep = ProjectPreprocessor(cfg, _Noop(), rag, _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        assert prep.register(str(root))["success"] is True
        project = dict(prep._project_row(str(root)))
        assert prep._step_inventory(project) is True
        with closing(prep._connect()) as con:
            con.execute("INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                        ("stub", "hash", "deterministic-stub", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 0))
            con.execute("UPDATE file_refs SET content_hash='hash',rag_hash='hash',needs_hash=0,card_key='stub' WHERE root=?", (str(root),))
            con.execute("UPDATE projects SET status='complete',phase='inventory',last_complete_at=1 WHERE root=?", (str(root),))
            con.commit()
        row = dict(prep._project_row(str(root)))
        assert prep._step_inventory(row) is True
        assert prep._project_row(str(root))["phase"] == "complete"
        snapshot = set_operational_mode(tmp_path / "state", "preprocessing")
        publish_preprocessing_ready(tmp_path / "state", snapshot)
        prep._consume_dirty_paths = lambda _root: {"notes.md"}
        prep._step_incremental_inventory = lambda *_args: (_ for _ in ()).throw(AssertionError("stub enrichment was skipped"))
        row = dict(prep._project_row(str(root)))
        row["phase"] = "inventory"
        assert prep._step_inventory(row) is True
        assert prep._project_row(str(root))["phase"] != "complete"
        with closing(prep._connect()) as con:
            con.execute("UPDATE projects SET status='running',phase='files' WHERE root=?", (str(root),))
            con.commit()
        prep.background_gpu = SimpleNamespace(ready=lambda: False)
        status = prep.status(str(root))["projects"][0]
        assert status["pending_stub_cards"] == 1
        assert status["phase_progress_pct"] == 0
        assert "Waiting" in status["waiting_reason"]
        assert "100% ready" not in status["active_detail"]
    finally:
        prep.close()


def test_exclusive_enriches_stub_without_removing_it_on_model_failure(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "notes.md").write_text("A useful explanation of a project component.\n", encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False, "model": "configured-model", "disable_llm_card_synthesis": True,
                          "prefer_deterministic_cards": False, "exclusive": {"enrich_stub_cards": True}},
        "background_gpu": {"file_batch_size": 1},
    }
    result = [{"success": False, "error": "model unavailable"}]
    calls = []
    gpu = SimpleNamespace(ready=lambda: True, generate_many=lambda tasks, **kw: calls.append(kw) or result)
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(), RepositoryTools(cfg), background_gpu=gpu)
    try:
        with closing(prep._connect()) as con:
            con.execute("INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                        ("stub", "hash", "deterministic-stub", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 0))
            con.execute("INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                        ("bad", "hash", "configured-model", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 10))
            con.execute("INSERT INTO file_refs(root,path,content_hash,size,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (str(root), "notes.md", "hash", 45, 0, 1, "stub", 0))
            con.commit()
        assert prep._find_next_files(str(root), 1) == []
        snapshot = set_operational_mode(tmp_path / "state", "preprocessing")
        publish_preprocessing_ready(tmp_path / "state", snapshot)
        prep.cfg["exclusive"]["enrich_stub_cards"] = False
        assert prep._find_next_files(str(root), 1) == []
        assert prep._pending_stub_cards(str(root)) == 0
        prep.cfg["exclusive"]["enrich_stub_cards"] = True
        assert prep._pending_stub_cards(str(root)) == 1
        assert len(prep._find_next_files(str(root), 1)) == 1
        read_file = prep.repo_tools.file_slice
        monkeypatch.setattr(prep.repo_tools, "file_slice", lambda *args, **kwargs: {"success": False})
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == "stub"
        monkeypatch.setattr(prep.repo_tools, "file_slice", read_file)
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == "stub"
            assert con.execute("SELECT COUNT(*) FROM content_cards WHERE card_key='stub'").fetchone()[0] == 1
        result[:] = [{"success": True, "data": {"purpose": "malformed"}}]
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == "stub"
            con.execute("UPDATE file_refs SET card_key=NULL WHERE root=?", (str(root),))
            con.commit()
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] is None
            con.execute("UPDATE file_refs SET card_key='stub' WHERE root=?", (str(root),))
            con.commit()
        result[:] = [{"success": True, "model": "wrong-model", "data": {"purpose": "documented component", "symbols": [], "dependencies": [],
                                                                           "side_effects": [], "risks": [], "tests": [], "keywords": []}}]
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == "stub"
        result[0]["model"] = "configured-model"
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            attached = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            assert attached != "stub"
            assert con.execute("SELECT COUNT(*) FROM content_cards WHERE card_key='stub'").fetchone()[0] == 1
        assert prep._pending_stub_cards(str(root)) == 0
        assert calls == [{"preprocessing": True}] * 5
    finally:
        prep.close()
