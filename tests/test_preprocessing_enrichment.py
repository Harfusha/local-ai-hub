from contextlib import closing
import hashlib
import tomllib
import time
from pathlib import Path
from types import SimpleNamespace
import sys
import threading

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.operational_mode import publish_preprocessing_ready, set_operational_mode
from local_ai_hub.preprocess import PREPROCESS_ANALYZER_VERSION, ProjectPreprocessor, _RetryablePreprocessingError
from local_ai_hub.config import load_config
from local_ai_hub.hardware import PROFILE_OVERRIDES
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.scheduler import QueueFullError


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
               "preprocessing": {"enabled": False, "model": "configured-model", "reject_temp_projects": False,
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
        assert prep._project_row(str(root))["phase"] != "complete"
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
        "preprocessing": {"enabled": False, "model": "configured-model", "disable_llm_card_synthesis": False,
                          "prefer_deterministic_cards": False, "exclusive": {"enrich_stub_cards": True}},
        "background_gpu": {"file_batch_size": 1},
    }
    result = [{"success": False, "error": "model unavailable"}]
    calls = []
    digest = hashlib.sha256((root / "notes.md").read_bytes()).hexdigest()
    gpu = SimpleNamespace(ready=lambda: True, generate_many=lambda tasks, **kw: calls.append(kw) or result)
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(), RepositoryTools(cfg), background_gpu=gpu)
    try:
        with closing(prep._connect()) as con:
            con.execute("INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                            ("stub", digest, "deterministic-stub", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 0))
            con.execute("INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                            ("bad", digest, "configured-model", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 10))
            con.execute("INSERT INTO file_refs(root,path,content_hash,size,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            (str(root), "notes.md", digest, 45, 0, 1, "stub", 0))
            con.commit()
        assert len(prep._find_next_files(str(root), 1)) == 1
        assert prep._pending_stub_cards(str(root)) == 1
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
            enrichment = con.execute(
                "SELECT status,attempts,last_error FROM file_card_enrichment WHERE content_hash=?",
                (digest,),
            ).fetchone()
            assert tuple(enrichment) == ("failed", 1, "model unavailable")
            assert con.execute("SELECT COUNT(*) FROM content_cards WHERE card_key='stub'").fetchone()[0] == 1
            con.execute("UPDATE file_card_enrichment SET status='pending',attempts=0,retry_after=0 WHERE content_hash=?", (digest,))
            con.commit()
        result[:] = [{"success": True, "data": {"purpose": "malformed"}}]
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == "stub"
            con.execute("UPDATE file_card_enrichment SET status='pending',attempts=0,retry_after=0 WHERE content_hash=?", (digest,))
            con.execute("UPDATE file_refs SET card_key=NULL WHERE root=?", (str(root),))
            con.commit()
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            fallback_key = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            assert con.execute("SELECT model FROM content_cards WHERE card_key=?", (fallback_key,)).fetchone()[0] == "deterministic-stub"
            con.execute("UPDATE file_card_enrichment SET status='pending',attempts=0,retry_after=0 WHERE content_hash=?", (digest,))
            con.commit()
        result[:] = [{"success": True, "model": "wrong-model", "data": {"purpose": "documented component", "symbols": [], "dependencies": [],
                                                                           "side_effects": [], "risks": [], "tests": [], "keywords": []}}]
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == fallback_key
            con.execute("UPDATE file_card_enrichment SET status='pending',attempts=0,retry_after=0 WHERE content_hash=?", (digest,))
            con.commit()
        result[0]["model"] = "configured-model"
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            attached = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            assert attached != "stub"
            assert con.execute("SELECT COUNT(*) FROM content_cards WHERE card_key=?", (fallback_key,)).fetchone()[0] == 1
        assert prep._pending_stub_cards(str(root)) == 0
        assert calls == [{"preprocessing": True}] * 5
    finally:
        prep.close()


def test_disabled_background_gpu_uses_scheduler_for_stub_enrichment(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = b"A useful explanation of a project component.\n"
    (root / "notes.md").write_bytes(source)
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False, "model": "configured-model", "disable_llm_card_synthesis": False,
                          "prefer_deterministic_cards": False, "exclusive": {"enrich_stub_cards": True}},
        "background_gpu": {"enabled": False, "file_batch_size": 1},
    }
    digest = hashlib.sha256(source).hexdigest()
    fallback_calls = []
    gpu = SimpleNamespace(
        enabled=False,
        ready=lambda: False,
        generate_many=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disabled GPU worker used")),
    )
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=gpu)
    try:
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                ("stub", digest, "deterministic-stub", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 0),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (str(root), "notes.md", digest, len(source), 0, 1, "stub", 0),
            )
            con.commit()
        snapshot = set_operational_mode(tmp_path / "state", "preprocessing")
        publish_preprocessing_ready(tmp_path / "state", snapshot)

        def fallback(*args):
            fallback_calls.append(args)
            return {"success": True, "model": "configured-model", "data": _enriched_card()}

        prep._run_background_generate = fallback
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        assert len(fallback_calls) == 1
        with closing(prep._connect()) as con:
            row = con.execute(
                "SELECT c.model,c.card_json FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?",
                (str(root),),
            ).fetchone()
        assert row[0] == "configured-model"
        assert "Verified source summary" in row[1]
    finally:
        prep.close()


def test_disabled_background_gpu_generation_uses_foreground_scheduler(tmp_path, monkeypatch):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"model": "configured-model"},
        "background_gpu": {"enabled": False},
    }
    submitted = []

    class Scheduler:
        def foreground_busy(self):
            return False

        def submit(self, model, *, execute, **kwargs):
            submitted.append((model, kwargs))
            return execute()

    class Policy:
        def profile(self, *_args, **_kwargs):
            return SimpleNamespace(prompt_budget_tokens=4096)

        def apply_payload(self, _model, payload, **_kwargs):
            return payload, SimpleNamespace(prompt_budget_tokens=4096)

    class Runtime:
        def request_interruptible(self, *_args, **_kwargs):
            return {"response": '{"purpose":"Verified summary","symbols":[],"dependencies":[],"side_effects":[],"risks":[],"tests":[],"keywords":[]}'}

    gpu = SimpleNamespace(
        enabled=False,
        generate=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("disabled GPU worker used")),
    )
    services = SimpleNamespace(model_policy=Policy())
    prep = ProjectPreprocessor(cfg, services, _Noop(), Scheduler(), Runtime(), RepositoryTools(cfg), background_gpu=gpu)
    try:
        prep._gpu_yield = lambda: False
        import local_ai_hub.operational_mode as operational_mode
        monkeypatch.setattr(operational_mode, "load_operational_mode", lambda _state_dir: SimpleNamespace())
        monkeypatch.setattr(operational_mode, "preprocessing_mode_ready", lambda *_args: True)
        monkeypatch.setattr(operational_mode, "operational_mode_gate_error", lambda *_args: None)
        result = prep._run_background_generate("configured-model", "prompt", "system", {"type": "object"}, 32, "preprocess:file-card")
        assert result["success"] is True, result
        assert result["model"] == "configured-model"
        assert len(submitted) == 1
        assert submitted[0][0] == "configured-model"
        assert submitted[0][1]["background"] is True
    finally:
        prep.close()


def test_disabled_background_gpu_can_still_use_ready_cpu_fallback():
    calls = []
    gpu = SimpleNamespace(
        enabled=False,
        ready=lambda: True,
        generate=lambda **kwargs: calls.append(kwargs) or {"success": True, "model": "cpu-model"},
    )
    prep = object.__new__(ProjectPreprocessor)
    prep.config = {"server": {}}
    prep.background_gpu = gpu
    prep._gpu_yield = lambda: False
    result = prep._run_background_generate("cpu-model", "prompt", "system", {}, 16, "preprocess:file-card")
    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0]["preprocessing"] is True


def _card_ref(prep, root, path, source, card_key=None):
    digest = hashlib.sha256(source).hexdigest()
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?)",
            (str(root), path, digest, len(source), 1, card_key, 0),
        )
        con.commit()
    return digest


def _enriched_card():
    return {
        "purpose": "Verified source summary",
        "symbols": ["Thing"],
        "dependencies": [],
        "side_effects": [],
        "risks": [],
        "tests": [],
        "keywords": ["thing"],
    }


def test_deterministic_card_is_saved_before_source_enrichment(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = b"class Thing:\n    pass\n"
    (root / "thing.py").write_bytes(source)
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"model": "configured-model", "disable_llm_card_synthesis": False}}
    calls = []

    class _Deterministic:
        def file_card(self, _root, _path):
            return {"success": True, "card": {"purpose": "provisional Thing", "symbols": ["Thing"]}}

    def generate(tasks, **_kwargs):
        with closing(prep._connect()) as con:
            row = con.execute(
                "SELECT c.model FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?",
                (str(root),),
            ).fetchone()
        assert row[0] == "deterministic"
        calls.extend(tasks)
        return [{"success": True, "model": "configured-model", "data": _enriched_card()}]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate)
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), deterministic=_Deterministic(), background_gpu=gpu)
    try:
        digest = _card_ref(prep, root, "thing.py", source)
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        assert len(calls) == 1
        assert calls[0]["source"] == "preprocess:file-card"
        assert "provisional Thing" in calls[0]["prompt"]
        assert "class Thing" in calls[0]["prompt"]
        assert prep._content_card_key(digest)
        with closing(prep._connect()) as con:
            row = con.execute(
                "SELECT c.model,c.card_json FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?",
                (str(root),),
            ).fetchone()
        assert row[0] == "configured-model"
        assert "Verified source summary" in row[1]
    finally:
        prep.close()


def test_old_deterministic_cache_hit_does_not_skip_enrichment(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = b"# old cached source\n"
    (root / "notes.md").write_bytes(source)
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"model": "configured-model", "disable_llm_card_synthesis": False}}
    calls = []
    gpu = SimpleNamespace(ready=lambda: True,
                          generate_many=lambda tasks, **_kw: calls.extend(tasks) or [
                              {"success": True, "model": "configured-model", "data": _enriched_card()}])
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=gpu)
    try:
        digest = hashlib.sha256(source).hexdigest()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                ("legacy-deterministic", digest, "deterministic", PREPROCESS_ANALYZER_VERSION,
                 '{"purpose":"old provisional","symbols":[],"dependencies":[],"side_effects":[],"risks":[],"tests":[],"keywords":[]}', 0, 0, 1),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?)",
                (str(root), "notes.md", digest, len(source), 1, "legacy-deterministic", 0),
            )
            con.commit()
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        assert len(calls) == 1
        assert "old provisional" in calls[0]["prompt"]
    finally:
        prep.close()


def test_same_source_across_projects_is_enriched_once_per_pipeline(tmp_path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"model": "configured-model", "disable_llm_card_synthesis": False}}
    calls = []
    gpu = SimpleNamespace(ready=lambda: True,
                          generate_many=lambda tasks, **_kw: calls.extend(tasks) or [
                              {"success": True, "model": "configured-model", "data": _enriched_card()}])
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=gpu)
    source = b"shared source\n"
    try:
        digest = hashlib.sha256(source).hexdigest()
        roots = [tmp_path / "one", tmp_path / "two"]
        for root in roots:
            root.mkdir()
            (root / "same.txt").write_bytes(source)
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                ("shared-provisional", digest, "deterministic-stub", PREPROCESS_ANALYZER_VERSION,
                 '{"purpose":"provisional","symbols":[],"dependencies":[],"side_effects":[],"risks":[],"tests":[],"keywords":[]}', 0, 0, 1),
            )
            for root in roots:
                con.execute(
                    "INSERT INTO file_refs(root,path,content_hash,size,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (str(root), "same.txt", digest, len(source), 1, "shared-provisional", 0),
                )
            con.commit()
        for root in roots:
            assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        assert len(calls) == 1
        with closing(prep._connect()) as con:
            linked = con.execute("SELECT COUNT(*) FROM file_refs WHERE card_key=?", (prep._content_card_key(digest),)).fetchone()[0]
        assert linked == 2
    finally:
        prep.close()


def test_changed_source_rejects_late_model_result(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = b"class Thing:\n    pass\n"
    path = root / "thing.py"
    path.write_bytes(source)
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"model": "configured-model", "disable_llm_card_synthesis": False}}
    prep = None

    class _Deterministic:
        def file_card(self, _root, _path):
            return {"success": True, "card": {"purpose": "provisional", "symbols": []}}

    def generate(_tasks, **_kwargs):
        path.write_text("class Changed:\n    pass\n", encoding="utf-8")
        return [{"success": True, "model": "configured-model", "data": _enriched_card()}]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate)
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), deterministic=_Deterministic(), background_gpu=gpu)
    try:
        digest = _card_ref(prep, root, "thing.py", source)
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            assert con.execute(
                "SELECT COUNT(*) FROM content_cards WHERE content_hash=? AND model='configured-model'",
                (digest,),
            ).fetchone()[0] == 0
            linked = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            assert con.execute("SELECT model FROM content_cards WHERE card_key=?", (linked,)).fetchone()[0] == "deterministic"
    finally:
        prep.close()


def test_default_file_card_synthesis_enabled_and_background_gpu_profile_defaults(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for defaults_path in (root / "defaults.toml", root / "src/local_ai_hub/defaults.toml"):
        with defaults_path.open("rb") as handle:
            defaults = tomllib.load(handle)
        assert defaults["preprocessing"]["disable_llm_card_synthesis"] is False
        assert defaults["background_gpu"]["enabled"] is False
    assert PROFILE_OVERRIDES["cpu"]["background_gpu"].get("enabled", True) is True
    assert PROFILE_OVERRIDES["integrated"]["background_gpu"].get("enabled", True) is False

    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    effective = load_config(config_path, probe_hardware=False)
    assert effective["preprocessing"]["disable_llm_card_synthesis"] is False
    assert effective["background_gpu"]["enabled"] is False
    config_path.write_text("[preprocessing]\ndisable_llm_card_synthesis = true\n[background_gpu]\nenabled = false\n", encoding="utf-8")
    override = load_config(config_path, probe_hardware=False)
    assert override["preprocessing"]["disable_llm_card_synthesis"] is True
    assert override["background_gpu"]["enabled"] is False


def _provisional_enrichment_fixture(tmp_path, gpu):
    root = tmp_path / "project"
    root.mkdir()
    source = b"class Existing:\n    pass\n"
    (root / "existing.py").write_bytes(source)
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"model": "configured-model", "disable_llm_card_synthesis": False}}
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=gpu)
    digest = hashlib.sha256(source).hexdigest()
    card_key = "provisional-existing"
    with closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
            (card_key, digest, "deterministic-stub", PREPROCESS_ANALYZER_VERSION,
             '{"purpose":"provisional","symbols":[],"dependencies":[],"side_effects":[],"risks":[],"tests":[],"keywords":[]}', 0, 0, 0),
        )
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?)",
            (str(root), "existing.py", digest, len(source), 1, card_key, 0),
        )
        con.commit()
    return prep, root, digest, card_key


def test_timeout_keeps_provisional_and_records_bounded_retry_state(tmp_path):
    responses = [{"success": False, "error_code": "timeout", "error": "generation timed out"}]
    calls = []
    gpu = SimpleNamespace(ready=lambda: True,
                          generate_many=lambda tasks, **_kw: calls.extend(tasks) or list(responses))
    prep, root, digest, provisional_key = _provisional_enrichment_fixture(tmp_path, gpu)
    try:
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            card_key = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            state = con.execute(
                "SELECT status,attempts,retry_after,last_error FROM file_card_enrichment WHERE content_hash=?",
                (digest,),
            ).fetchone()
        assert card_key == provisional_key
        assert state["status"] == "failed"
        assert state["attempts"] == 1
        assert state["retry_after"] > time.time()
        assert state["last_error"] == "generation timed out"
        assert len(calls) == 1

        with closing(prep._connect()) as con:
            con.execute("UPDATE file_card_enrichment SET retry_after=0 WHERE content_hash=?", (digest,))
            con.commit()
        responses[:] = [{"success": True, "model": "configured-model", "data": _enriched_card()}]
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            state = con.execute(
                "SELECT status,attempts FROM file_card_enrichment WHERE content_hash=?", (digest,)
            ).fetchone()
            linked = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
        assert linked != provisional_key
        assert tuple(state) == ("complete", 2)
    finally:
        prep.close()


def test_preemption_preserves_provisional_and_next_run_resumes(tmp_path):
    responses = [{"success": False, "preempted": True, "error": "foreground work pending"}]
    calls = []
    gpu = SimpleNamespace(ready=lambda: True,
                          generate_many=lambda tasks, **_kw: calls.extend(tasks) or list(responses))
    prep, root, digest, provisional_key = _provisional_enrichment_fixture(tmp_path, gpu)
    try:
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is False
        with closing(prep._connect()) as con:
            card_key = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            state = con.execute(
                "SELECT status,attempts,retry_after,last_error FROM file_card_enrichment WHERE content_hash=?",
                (digest,),
            ).fetchone()
        assert card_key == provisional_key
        assert state["status"] == "pending"
        assert state["attempts"] == 0
        assert state["last_error"] is None
        assert state["retry_after"] <= time.time()

        responses[:] = [{"success": True, "model": "configured-model", "data": _enriched_card()}]
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            state = con.execute(
                "SELECT status,attempts FROM file_card_enrichment WHERE content_hash=?", (digest,)
            ).fetchone()
            linked = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
        assert linked != provisional_key
        assert tuple(state) == ("complete", 1)
        assert len(calls) == 2
    finally:
        prep.close()


def test_completed_project_with_legacy_card_is_scheduled_before_periodic_recheck(tmp_path):
    calls = []
    gpu = SimpleNamespace(
        ready=lambda: True,
        generate_many=lambda tasks, **_kw: calls.extend(tasks) or [
            {"success": True, "model": "configured-model", "data": _enriched_card()}
        ],
    )
    prep, root, _digest, _card_key = _provisional_enrichment_fixture(tmp_path, gpu)
    try:
        snapshot = set_operational_mode(tmp_path / "state", "preprocessing")
        publish_preprocessing_ready(tmp_path / "state", snapshot)
        now = time.time()
        second_root = tmp_path / "second-project"
        second_root.mkdir()
        (second_root / "existing.py").write_bytes((root / "existing.py").read_bytes())
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,"
                "next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "workspace", "complete", "complete", 1, 0, now, now, now + 1800, 0, now, "test"),
            )
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,"
                "next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(second_root), "workspace-2", "complete", "complete", 1, 0, now, now, now + 3600, 0, now, "test"),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,generation,card_key,updated_at) "
                "SELECT ?,path,content_hash,size,generation,card_key,updated_at FROM file_refs WHERE root=?",
                (str(second_root), str(root)),
            )
            con.commit()

        scheduled = prep._next_gpu_project()

        assert scheduled is not None
        assert str(scheduled["root"]) == str(root)
        assert scheduled["phase"] == "file_card_enrichment"
        assert scheduled["status"] == "queued"
        assert scheduled["next_check_at"] == 0

        assert prep._run_project_step(dict(scheduled)) is True
        assert len(calls) == 1
        with closing(prep._connect()) as con:
            model = con.execute(
                "SELECT c.model FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?",
                (str(root),),
            ).fetchone()[0]
        assert model == "configured-model"

        resumed = dict(prep._project_row(str(root)))
        assert prep._run_project_step(resumed) is True
        assert prep._project_row(str(root))["status"] == "complete"

        shared_content = prep._next_gpu_project()
        assert shared_content is not None
        assert str(shared_content["root"]) == str(second_root)
        assert prep._run_project_step(dict(shared_content)) is True
        assert len(calls) == 1  # The second root reuses the content-addressed model card.
        with closing(prep._connect()) as con:
            second_model = con.execute(
                "SELECT c.model FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?",
                (str(second_root),),
            ).fetchone()[0]
        assert second_model == "configured-model"
    finally:
        prep.close()


def test_completed_project_card_enrichment_respects_project_slot_limit(tmp_path):
    gpu = SimpleNamespace(ready=lambda: True, generate_many=lambda tasks, **_kw: [])
    prep, root, _digest, _card_key = _provisional_enrichment_fixture(tmp_path, gpu)
    try:
        prep.max_preprocessing_projects = 1
        now = time.time()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,"
                "next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "workspace", "complete", "complete", 1, 0, now, now, now + 3600, 0, now, "test"),
            )
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,"
                "next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(tmp_path / "occupied"), "occupied", "running", "inventory", 1, 0,
                 now - 1, now - 1, now, 0, now - 1, "test"),
            )
            con.commit()

        assert prep._next_gpu_project() is None
        assert prep._project_row(str(root))["phase"] == "complete"
    finally:
        prep.close()


def test_retryable_background_scheduler_rejection_yields_without_failing():
    def make_preprocessor(error):
        prep = object.__new__(ProjectPreprocessor)
        prep.state_dir = None
        prep.config = {"server": {}}
        prep.cfg = {"background_scheduler_timeout_seconds": 1}
        prep._gpu_yield = lambda: False
        prep.background_gpu = None

        def reject(*_args, **_kwargs):
            raise error

        prep.scheduler = SimpleNamespace(submit=reject)
        return prep

    retryable_error = QueueFullError("scheduler queue limit reached", retryable=True)
    try:
        make_preprocessor(retryable_error)._run_background_generate(
            "configured-model", "prompt", "system", {}, 32, "preprocess:file-card"
        )
    except _RetryablePreprocessingError as exc:
        assert "scheduler queue limit reached" in str(exc)
        assert exc.retry_after_seconds == 30
    else:
        raise AssertionError("retryable scheduler admission must defer preprocessing")

    terminal_error = QueueFullError("GPU admission outcome unknown", retryable=False)
    try:
        make_preprocessor(terminal_error)._run_background_generate(
            "configured-model", "prompt", "system", {}, 32, "preprocess:file-card"
        )
    except QueueFullError as exc:
        assert exc is terminal_error
    else:
        raise AssertionError("terminal GPU admission must remain fail closed")
