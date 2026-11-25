from contextlib import closing
import hashlib
import json
import sqlite3
import tomllib
import time
from pathlib import Path
from types import SimpleNamespace
import sys
import threading

import pytest

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.operational_mode import publish_preprocessing_ready, set_operational_mode
from local_ai_hub.preprocess import CARD_SCHEMA, PREPROCESS_ANALYZER_VERSION, ProjectPreprocessor, _RetryablePreprocessingError
from local_ai_hub.config import load_config
from local_ai_hub.hardware import PROFILE_OVERRIDES
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.scheduler import QueueFullError


def test_file_card_output_rejects_unbounded_model_fields():
    card = {
        "purpose": "p",
        "symbols": [],
        "dependencies": [],
        "side_effects": [],
        "risks": [],
        "tests": [],
        "keywords": [],
    }
    valid = ProjectPreprocessor._valid_enriched_file_card
    assert valid(card)
    purpose_limit = CARD_SCHEMA["properties"]["purpose"]["maxLength"]
    assert valid({**card, "purpose": "ž" * purpose_limit})
    assert not valid({**card, "purpose": "ž" * purpose_limit + " "})
    assert not valid({**card, "purpose": " "})
    for field, rule in CARD_SCHEMA["properties"].items():
        if rule["type"] == "array" and field != "evidence":
            items_limit = rule["maxItems"]
            item_limit = rule["items"]["maxLength"]
            assert valid({**card, field: ["ž" * item_limit] * items_limit})
            assert not valid({**card, field: ["ž" * (item_limit + 1)]})
            assert not valid({**card, field: ["x"] * (items_limit + 1)})


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


def test_file_card_enrichment_claim_and_finish_use_single_writer(tmp_path, monkeypatch):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"model": "configured-model"},
    }
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False, workspace_id=lambda path: "workspace"), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        def fail_connect():
            raise sqlite3.OperationalError("database is locked")

        with monkeypatch.context() as patch:
            patch.setattr(prep, "_connect", fail_connect)
            claim = prep._claim_file_card_enrichment("source-hash", "configured-model")
            assert claim is not None
            assert prep._finish_file_card_enrichment(claim, success=True)

        with closing(prep._connect()) as con:
            row = con.execute(
                "SELECT status, attempts FROM file_card_enrichment WHERE content_hash=?",
                ("source-hash",),
            ).fetchone()
        assert tuple(row) == ("complete", 1)
    finally:
        prep.close()


def test_file_card_store_uses_single_writer(tmp_path, monkeypatch):
    import sqlite3

    root = tmp_path / "project"
    root.mkdir()
    (root / "notes.md").write_text("A useful explanation of a project component.\n", encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": False, "model": "configured-model", "reject_temp_projects": False,
        },
    }
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False, workspace_id=lambda path: "workspace"), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        assert prep.register(str(root))["success"] is True
        assert prep._step_inventory(dict(prep._project_row(str(root)))) is True
        item = prep._find_next_file(str(root))
        assert item is not None
        source_hash = str(item["content_hash"])

        def fail_connect():
            raise sqlite3.OperationalError("database is locked")

        with monkeypatch.context() as patch:
            patch.setattr(prep, "_connect", fail_connect)
            assert prep._store_file_card(
                str(root), item, "card-key", {"purpose": "test"}, "deterministic-stub", source_hash,
            ) is True

        with closing(prep._connect()) as con:
            row = con.execute("SELECT card_key FROM file_refs WHERE root=? AND path=?", (str(root), item["path"])).fetchone()
            card = con.execute("SELECT content_hash FROM content_cards WHERE card_key=?", ("card-key",)).fetchone()
        assert row[0] == "card-key"
        assert card[0] == source_hash
    finally:
        prep.close()


def test_file_card_cache_updates_use_single_writer(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "notes.md").write_text("A useful explanation of a project component.\n", encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": False, "model": "configured-model", "reject_temp_projects": False,
            "exclusive": {"enrich_stub_cards": True},
        },
    }
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False, workspace_id=lambda path: "workspace"), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        assert prep.register(str(root))["success"] is True
        assert prep._step_inventory(dict(prep._project_row(str(root)))) is True
        item = prep._find_next_file(str(root))
        assert item is not None
        card_key = prep._content_card_key(str(item["content_hash"]))
        assert prep._store_file_card(
            str(root), item, card_key, {"purpose": "cached"}, prep._configured_preprocessing_model(), str(item["content_hash"]),
        ) is True

        monkeypatch.setattr(prep, "_valid_enriched_file_card", lambda _data: True)
        write_calls = []
        write_retry = prep._write_retry
        monkeypatch.setattr(prep, "_write_retry", lambda callback, **kwargs: (write_calls.append(callback), write_retry(callback, **kwargs))[1])
        with closing(prep._connect()) as con:
            cached_item = con.execute("SELECT * FROM file_refs WHERE root=? AND path=?", (str(root), item["path"])).fetchone()
        monkeypatch.setattr(prep, "_find_next_files", lambda _root, _limit: [cached_item])
        row = dict(prep._project_row(str(root)))
        row["phase"] = "files"
        prep._step_file_card(row)
        assert any(callback.__name__ == "update_cache" for callback in write_calls)
    finally:
        prep.close()


def test_oversized_file_card_uses_single_writer(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "large.txt").write_text("x" * 100, encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": False, "model": "configured-model", "reject_temp_projects": False,
            "file_card_max_bytes": 50,
        },
    }
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False, workspace_id=lambda path: "workspace"), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        assert prep.register(str(root))["success"] is True
        assert prep._step_inventory(dict(prep._project_row(str(root)))) is True
        with closing(prep._connect()) as con:
            con.execute("UPDATE file_refs SET size=51 WHERE root=?", (str(root),))
            con.commit()
        monkeypatch.setattr(prep, "_find_next_files", lambda _root, _limit: [])
        write_calls = []
        write_retry = prep._write_retry
        monkeypatch.setattr(prep, "_write_retry", lambda callback, **kwargs: (write_calls.append(callback), write_retry(callback, **kwargs))[1])
        row = dict(prep._project_row(str(root)))
        row["phase"] = "files"
        assert prep._step_file_card(row) is True
        assert any(callback.__name__ == "store_oversized" for callback in write_calls)
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
    finally:
        prep.close()


def test_file_selection_skips_blocked_enrichment_claims(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "failed.py").write_text("def failed(): return 1\n", encoding="utf-8")
    (root / "running.py").write_text("def running(): return 2\n", encoding="utf-8")
    (root / "complete.py").write_text("def complete(): return 4\n", encoding="utf-8")
    (root / "available.py").write_text("def available(): return 3\n", encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": False, "model": "configured-model", "reject_temp_projects": False,
            "exclusive": {"enrich_stub_cards": True},
        },
    }
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False, workspace_id=lambda path: "workspace"), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        assert prep.register(str(root))["success"] is True
        assert prep._step_inventory(dict(prep._project_row(str(root)))) is True
        model = prep._configured_preprocessing_model()
        pipeline = prep._file_card_pipeline_version()
        now = time.time()
        with closing(prep._connect()) as con:
            rows = {Path(row["path"]).name: row for row in con.execute("SELECT * FROM file_refs WHERE root=?", (str(root),))}
            for name in ("failed.py", "running.py", "complete.py", "available.py"):
                con.execute("UPDATE file_refs SET content_hash=? WHERE root=? AND path=?", (name, str(root), rows[name]["path"]))
            con.executemany(
                "INSERT INTO file_card_enrichment(content_hash,model,pipeline_version,status,attempts,retry_after,lease_until,last_error,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    ("failed.py", model, pipeline, "failed", 3, 0, 0, "retry limit", now),
                    ("running.py", model, pipeline, "running", 1, 0, now + 900, None, now),
                    ("complete.py", model, pipeline, "complete", 1, 0, 0, None, now),
                ],
            )
            con.commit()

        selected = {Path(row["path"]).name for row in prep._find_next_files(str(root), 64)}
        assert selected == {"available.py", "complete.py"}
        with closing(prep._connect()) as con:
            con.execute("UPDATE file_refs SET size=200000 WHERE path IN ('available.py', 'complete.py')")
            con.commit()
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        with closing(prep._connect()) as con:
            attached_models = dict(con.execute(
                "SELECT f.path,c.model FROM file_refs f LEFT JOIN content_cards c ON f.card_key=c.card_key"
            ).fetchall())
        assert attached_models == {
            "failed.py": None, "running.py": None,
            "available.py": "deterministic-oversized", "complete.py": "deterministic-oversized",
        }
    finally:
        prep.close()


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
        with closing(prep._connect()) as con:
            con.execute("UPDATE projects SET status='complete',phase='complete' WHERE root=?", (str(root),))
            con.commit()
        complete_status = prep.status(str(root))["projects"][0]
        assert complete_status["pending_stub_cards"] == 1
        assert "Index complete" in complete_status["active_detail"]
        assert "awaiting enrichment" in complete_status["active_detail"]
        assert "card enrichments remain" in complete_status["waiting_reason"]
        assert "100% ready" not in complete_status["active_detail"]
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


@pytest.mark.parametrize(
    "schema_fallback",
    [None, "deferred", "preempted", "cached", "model-fallback", "model-circuit-open", "backend-repeat-limit", "disabled", "outcome-unknown", "truncated", "bounded"],
)
def test_disabled_background_gpu_uses_scheduler_for_stub_enrichment(tmp_path, schema_fallback, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    source = b"A useful explanation of a project component.\n"
    (root / "notes.md").write_bytes(source)
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False, "model": "configured-model", "disable_llm_card_synthesis": False,
                          "prefer_deterministic_cards": False, "exclusive": {"enrich_stub_cards": True}},
        "models": {"fast_code": "fast-model"},
        "background_gpu": {"enabled": False, "file_batch_size": 1},
    }
    if schema_fallback == "disabled":
        cfg["resilience"] = {"model_fallback_enabled": False}
    elif schema_fallback == "bounded":
        cfg["resilience"] = {"max_model_fallbacks": 1}
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

        def successful(model):
            return {"success": True, "model": model, "data": _enriched_card()}

        def fallback(*args, **kwargs):
            fallback_calls.append(args)
            assert args[3] == CARD_SCHEMA
            assert kwargs.get("allow_model_fallback", True) is (args[0] == "configured-model")
            if schema_fallback in {"outcome-unknown", "truncated", "bounded"}:
                return {
                    "success": False, "model": args[0], "error_code": "invalid_preprocess_json",
                    "outcome_unknown": schema_fallback == "outcome-unknown",
                    "output_truncated": schema_fallback == "truncated",
                    "stop_reason": "length" if schema_fallback == "truncated" else "stop",
                }
            if schema_fallback:
                if schema_fallback == "model-fallback":
                    if args[0] == "configured-model":
                        return {"success": False, "model": "schema-model", "error_code": "invalid_preprocess_json"}
                    assert args[0] == "fast-model"
                    return successful("fast-model")
                if schema_fallback == "model-circuit-open":
                    if args[0] == "configured-model":
                        return {"success": False, "model": "configured-model", "error_code": "invalid_preprocess_json"}
                    if args[0] == "schema-model":
                        raise _RetryablePreprocessingError(
                            "preprocessing model circuit is open: schema-model",
                            retry_after_seconds=60,
                            error_code="model_circuit_open",
                        )
                    assert args[0] == "fast-model"
                    return successful("fast-model")
                if schema_fallback == "backend-repeat-limit":
                    if args[0] == "configured-model":
                        return {"success": False, "model": "configured-model", "error_code": "invalid_preprocess_json"}
                    if args[0] == "schema-model":
                        return {
                            "success": False,
                            "model": "schema-model",
                            "error": "HTTP 500: prediction aborted, token repeat limit reached",
                            "retryable": True,
                        }
                    assert args[0] == "fast-model"
                    return successful("fast-model")
                if args[0] == "configured-model":
                    card = _enriched_card()
                    card["purpose"] = "x" * (CARD_SCHEMA["properties"]["purpose"]["maxLength"] + 1)
                    return {"success": True, "model": "configured-model", "data": card}
                assert args[0] == "schema-model"
                if schema_fallback == "deferred":
                    raise _RetryablePreprocessingError("schema fallback deferred", retry_after_seconds=5)
                if schema_fallback == "cached":
                    return successful("schema-model")
                return {"success": False, "preempted": True}
            return successful("configured-model")

        prep._run_background_generate = fallback
        if schema_fallback:
            prep.services = SimpleNamespace(_fallback_models=lambda _model: ["schema-model"])
        if schema_fallback in {"disabled", "outcome-unknown", "truncated", "bounded"}:
            prep._step_file_card({"root": str(root), "phase": "files"})
            expected = ["configured-model", "schema-model"] if schema_fallback == "bounded" else ["configured-model"]
            assert [call[0] for call in fallback_calls] == expected
            with closing(prep._connect()) as con:
                assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == "stub"
            return
        if schema_fallback == "cached":
            assert prep._claim_file_card_enrichment(digest, "configured-model")
            with closing(prep._connect()) as con:
                con.execute("UPDATE file_card_enrichment SET status='pending', attempts=2")
                con.commit()
            assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
            second = tmp_path / "other-worktree"
            second.mkdir()
            (second / "notes.md").write_bytes(source)
            _card_ref(prep, second, "notes.md", source)
            write = prep._write_retry

            def rollback_then_retry(operation, **kwargs):
                with closing(prep._connect()) as con:
                    con.execute("BEGIN")
                    operation(con)
                    con.rollback()
                return write(operation, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(prep, "_write_retry", rollback_then_retry)
                assert prep._step_file_card({"root": str(second), "phase": "files"}) is True
            with closing(prep._connect()) as con:
                rows = con.execute(
                    "SELECT f.card_key,c.model,c.hits FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key"
                ).fetchall()
                assert [tuple(row) for row in rows] == [(prep._content_card_key(digest), "schema-model", 1)] * 2
            assert [call[0] for call in fallback_calls] == ["configured-model", "schema-model"]

            (second / "stale.md").write_bytes(source)
            _card_ref(prep, second, "stale.md", source)
            select = prep._find_next_files

            def select_then_change(root_key, limit):
                selected = select(root_key, limit)
                updated_source = b"A new revision.\n"
                (second / "stale.md").write_bytes(updated_source)
                with closing(prep._connect()) as con:
                    con.execute("UPDATE file_refs SET content_hash=? WHERE root=? AND path='stale.md'",
                                (hashlib.sha256(updated_source).hexdigest(), root_key))
                    con.commit()
                return selected

            with monkeypatch.context() as patch:
                patch.setattr(prep, "_find_next_files", select_then_change)
                assert prep._step_file_card({"root": str(second), "phase": "files"}) is False
            with closing(prep._connect()) as con:
                assert con.execute("SELECT card_key FROM file_refs WHERE path='stale.md'").fetchone()[0] is None

            prep.services._fallback_models = lambda _model: []
            prep._run_background_generate = lambda model, *_args: successful(model)
            (second / "copy.md").write_bytes(source)
            _card_ref(prep, second, "copy.md", source)
            assert prep._step_file_card({"root": str(second), "phase": "files"}) is True
            with closing(prep._connect()) as con:
                assert con.execute(
                    "SELECT c.model FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.path='copy.md'"
                ).fetchone()[0] == "configured-model"
            return
        if schema_fallback in {"model-fallback", "model-circuit-open", "backend-repeat-limit"}:
            assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
            expected = (
                ["configured-model", "schema-model", "fast-model"]
                if schema_fallback in {"model-circuit-open", "backend-repeat-limit"}
                else ["configured-model", "fast-model"]
            )
            assert [call[0] for call in fallback_calls] == expected
            with closing(prep._connect()) as con:
                row = con.execute(
                    "SELECT c.model FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?",
                    (str(root),),
                ).fetchone()
            assert row[0] == "fast-model"
            return
        if schema_fallback:
            before = time.time()
            if schema_fallback == "deferred":
                with pytest.raises(_RetryablePreprocessingError, match="schema fallback deferred"):
                    prep._step_file_card({"root": str(root), "phase": "files"})
            else:
                prep._step_file_card({"root": str(root), "phase": "files"})
            assert len(fallback_calls) == 2
            with closing(prep._connect()) as con:
                row = con.execute(
                    "SELECT status, attempts, lease_until, retry_after FROM file_card_enrichment WHERE content_hash=?",
                    (digest,),
                ).fetchone()
            assert tuple(row[:3]) == ("pending", 0, 0)
            delay = 5 if schema_fallback == "deferred" else 0
            assert before + delay <= row["retry_after"] <= time.time() + delay
            return
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


@pytest.mark.parametrize("stop_reason", ["stop", "length"])
def test_disabled_background_gpu_generation_uses_foreground_scheduler(tmp_path, monkeypatch, stop_reason):
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
            return {
                "response": json.dumps(_enriched_card()), "done": True, "done_reason": stop_reason,
            }

    gpu = SimpleNamespace(
        enabled=False,
        generate=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("disabled GPU worker used")),
    )
    services = SimpleNamespace(model_policy=Policy())
    prep = ProjectPreprocessor(cfg, services, _Noop(), Scheduler(), Runtime(), RepositoryTools(cfg), background_gpu=gpu)
    try:
        prep._gpu_yield = lambda: False
        import local_ai_hub.operational_mode as operational_mode
        monkeypatch.setattr(
            operational_mode,
            "load_operational_mode",
            lambda _state_dir: SimpleNamespace(mode="active", degraded=False),
        )
        monkeypatch.setattr(operational_mode, "preprocessing_mode_ready", lambda *_args: True)
        monkeypatch.setattr(operational_mode, "operational_mode_gate_error", lambda *_args: None)
        result = prep._run_background_generate("configured-model", "prompt", "system", {"type": "object"}, 32, "preprocess:file-card")
        assert result["success"] is (stop_reason == "stop"), result
        assert result["model"] == "configured-model"
        if stop_reason == "length":
            assert result["error_code"] == "model_output_truncated"
            assert result["terminal"] is True
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


@pytest.mark.parametrize("phase", ["inventory", "hash"])
@pytest.mark.parametrize("damage", ["pruned", "malformed", "wrong-shape", "wrong-model", "valid"])
def test_completed_enrichment_recovers_unusable_cached_card(tmp_path, monkeypatch, damage, phase):
    root = tmp_path / "project"
    root.mkdir()
    source = b"class Thing:\n    pass\n"
    (root / "thing.py").write_bytes(source)
    model = "configured-model"
    cfg = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"model": model}}
    calls = []

    def generate(tasks, **_kwargs):
        calls.extend(tasks)
        assert not prep._claim_file_card_enrichment(digest, model)
        return [{"success": True, "model": model, "data": _enriched_card()}]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate)
    prep = ProjectPreprocessor(cfg, _Noop(), SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=gpu)
    try:
        digest = _card_ref(prep, root, "thing.py", source)
        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        card_key = prep._content_card_key(digest)
        with closing(prep._connect()) as con:
            attached = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            assert attached == card_key
        assert not prep._claim_file_card_enrichment(digest, model)
        with closing(prep._connect()) as con:
            con.execute("UPDATE file_card_enrichment SET attempts=3 WHERE content_hash=?", (digest,))
            con.execute("DELETE FROM file_refs WHERE root=?", (str(root),))
            if damage == "pruned":
                con.execute("UPDATE content_cards SET accessed_at=0 WHERE card_key=?", (card_key,))
            elif damage == "malformed":
                con.execute("UPDATE content_cards SET card_json='{' WHERE card_key=?", (card_key,))
            elif damage == "wrong-shape":
                con.execute("UPDATE content_cards SET card_json='{}' WHERE card_key=?", (card_key,))
            elif damage == "wrong-model":
                con.execute("UPDATE content_cards SET model='unapproved-model' WHERE card_key=?", (card_key,))
            if damage in {"malformed", "wrong-shape", "wrong-model"}:
                con.execute("DELETE FROM content_cards WHERE model='deterministic-stub'")
            con.commit()
        if damage == "pruned":
            prep._last_db_maintenance = 0
            monkeypatch.setattr(prep, "_yield", lambda: False)
            monkeypatch.setattr(prep, "cleanup_deleted_projects", lambda: None)
            monkeypatch.setattr(prep, "cleanup_orphaned_indexes", lambda: None)
            assert prep._run_idle_database_maintenance()
            with closing(prep._connect()) as con:
                assert con.execute("SELECT 1 FROM content_cards WHERE card_key=?", (card_key,)).fetchone() is None

        _card_ref(prep, root, "thing.py", source)
        if damage == "valid":
            prep.cfg["disable_llm_card_synthesis"] = True
        if phase == "inventory":
            prep._link_content_reuse(str(root))
        else:
            with closing(prep._connect()) as con:
                con.execute("UPDATE file_refs SET content_hash='',needs_hash=1 WHERE root=?", (str(root),))
                con.commit()
            assert prep._step_hash({"root": str(root)}) is True
        with closing(prep._connect()) as con:
            early = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
        if damage == "valid":
            assert early == card_key
        else:
            assert early != card_key
            assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        assert len(calls) == (1 if damage == "valid" else 2)
        with closing(prep._connect()) as con:
            attached = con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0]
            state = con.execute("SELECT status,attempts FROM file_card_enrichment WHERE content_hash=?", (digest,)).fetchone()
        assert attached == card_key
        assert tuple(state) == ("complete", 3 if damage == "valid" else 1)
    finally:
        prep.close()


def test_idle_maintenance_recovers_attached_corrupt_cards(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    model = "configured-model"
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"model": model, "reject_temp_projects": False}}
    calls = []

    def generate(tasks, **_kwargs):
        calls.extend(tasks)
        return [{"success": True, "model": model, "data": _enriched_card()} for _ in tasks]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate)
    rag = SimpleNamespace(index_reset=False, workspace_id=lambda _root: "workspace")
    prep = ProjectPreprocessor(cfg, _Noop(), rag, _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=gpu)
    try:
        assert prep.register(str(root))["success"] is True
        prep._set_project(str(root), phase="complete", status="complete")
        attached = {}
        valid = json.dumps(_enriched_card())
        records = {
            "malformed": "{", "non-object": "[]", "wrong-shape": "{}",
            "dangling": None, "wrong-content": valid, "current": valid,
            "legacy": json.dumps({"purpose": "Older card still readable", "symbols": ["x" * 180]}),
        }
        for name, payload in records.items():
            path = f"{name}.py"
            source = f"NAME = {name!r}\n".encode()
            (root / path).write_bytes(source)
            digest = hashlib.sha256(source).hexdigest()
            key = prep._content_card_key(digest) if name in {"current", "wrong-shape"} else name
            attached[path] = key
            _card_ref(prep, root, path, source, key)
            if payload is not None:
                with closing(prep._connect()) as con:
                    con.execute(
                        "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at) VALUES(?,?,?,?,?,0,?)",
                        (key, "other-content" if name == "wrong-content" else digest,
                         model, PREPROCESS_ANALYZER_VERSION, payload, time.time()),
                    )
                    con.commit()
            if name == "wrong-shape":
                claim = prep._claim_file_card_enrichment(digest, model)
                assert claim is not None
                assert prep._finish_file_card_enrichment(claim, success=True)

        prep._last_db_maintenance = 0
        monkeypatch.setattr(prep, "_yield", lambda: False)
        monkeypatch.setattr(prep, "cleanup_deleted_projects", lambda: None)
        monkeypatch.setattr(prep, "cleanup_orphaned_indexes", lambda: None)
        assert prep._run_idle_database_maintenance()
        with closing(prep._connect()) as con:
            linked = dict(con.execute("SELECT path,card_key FROM file_refs WHERE root=?", (str(root),)))
        kept = {path: key for path, key in attached.items() if path in {"current.py", "legacy.py"}}
        assert {path: key for path, key in linked.items() if key is not None} == kept
        state = prep._project_row(str(root))
        assert (state["phase"], state["status"]) == ("files", "queued")
        assert prep._step_file_card(dict(state)) is True
        assert len(calls) == 5
        with closing(prep._connect()) as con:
            infos = dict(con.execute("SELECT path,card_key FROM file_refs WHERE root=?", (str(root),)))
        assert all(infos.values())
        assert {path: infos[path] for path in kept} == kept

        prep._set_project(str(root), phase="complete", status="complete", paused=1)
        with closing(prep._connect()) as con:
            con.execute("UPDATE file_refs SET card_key='missing' WHERE root=? AND path='dangling.py'", (str(root),))
            con.commit()
        prep._last_db_maintenance = 0
        assert prep._run_idle_database_maintenance()
        with closing(prep._connect()) as con:
            assert con.execute("SELECT card_key FROM file_refs WHERE root=? AND path='dangling.py'", (str(root),)).fetchone()[0] == "missing"
        assert prep._project_row(str(root))["paused"] == 1
    finally:
        prep.close()


@pytest.mark.parametrize("mode", ["normal", "deferred", "deferred-disabled"])
def test_file_card_enrichment_refreshes_module_and_project_cards(tmp_path, monkeypatch, mode):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    source = b"class Example:\n    pass\n"
    (root / "src" / "example.py").write_bytes(source)
    model = "configured-model"
    cfg = {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {
        "enabled": False, "model": model, "reject_temp_projects": False, "disable_llm_card_synthesis": True,
    }}
    calls = []

    def generate(tasks, **_kwargs):
        calls.extend(tasks)
        return [{"success": True, "model": model, "data": _enriched_card()} for _ in tasks]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate)
    services = SimpleNamespace(repo_profile=lambda _root: {}, repo_map=lambda *_args: {})
    deterministic = SimpleNamespace(
        module_card=lambda _root, _module, cards: {
            "success": True, "confidence": 1, "card": {"purpose": cards[0]["card"]["purpose"]},
        },
        project_card=lambda _root, _profile, _map, modules: {
            "success": True, "confidence": 1, "card": {"summary": modules[0]["purpose"]},
        },
    )
    rag = SimpleNamespace(index_reset=False, workspace_id=lambda _root: "workspace")
    prep = ProjectPreprocessor(cfg, services, rag, _Noop(), _Noop(), RepositoryTools(cfg),
                               background_gpu=gpu)
    try:
        key = str(root)
        prep.enabled = True
        assert prep.register(key)["success"] is True
        prep.deterministic = deterministic
        monkeypatch.setattr(prep, "_yield", lambda: False)
        digest = _card_ref(prep, root, "src/example.py", source)
        assert prep._step_file_card({"root": key, "phase": "files"})
        assert prep._step_module({"root": key, "phase": "modules"})
        assert prep._step_project({"root": key, "phase": "project"})
        with closing(prep._connect()) as con:
            old_project = con.execute("SELECT revision_hash,card_json FROM project_cards WHERE root=?", (key,)).fetchone()
        assert json.loads(old_project["card_json"])["summary"] == "source file (.py)"
        assert prep.lookup(key, "example")["project"]["summary"] == "source file (.py)"

        prep.cfg["disable_llm_card_synthesis"] = False
        phase = "files" if mode == "normal" else "file_card_enrichment"
        prep._set_project(key, phase=phase, status="queued")
        assert prep._step(dict(prep._project_row(key)))
        if mode == "deferred-disabled":
            prep.cfg["disable_llm_card_synthesis"] = True
        visited = []
        for _ in range(8):
            row = dict(prep._project_row(key))
            visited.append(row["phase"])
            if row["phase"] in {"hot_queries", "complete"}:
                break
            assert prep._step(row)
        assert visited[-1] == ("hot_queries" if mode == "normal" else "complete")
        assert "diagnostics" not in visited
        assert len(calls) == 1
        assert prep.lookup(key, "example")["project"]["summary"] == _enriched_card()["purpose"]
        with closing(prep._connect()) as con:
            project = con.execute("SELECT revision_hash,card_json FROM project_cards WHERE root=?", (key,)).fetchone()
            assert json.loads(project["card_json"])["summary"] == _enriched_card()["purpose"]
            assert project["revision_hash"] != old_project["revision_hash"]
            card_key = prep._content_card_key(digest)
            current_card_json = con.execute("SELECT card_json FROM content_cards WHERE card_key=?", (card_key,)).fetchone()[0]
            current_card = json.loads(current_card_json)
            con.execute("UPDATE content_cards SET card_json=? WHERE card_key=?",
                        (json.dumps(current_card, indent=2, sort_keys=True), card_key))
            con.commit()
        assert prep._modules_needing_card(key) == []
        with closing(prep._connect()) as con:
            changed_card = {**_enriched_card(), "purpose": "Corrected source summary"}
            con.execute("UPDATE content_cards SET card_json=? WHERE card_key=?", (json.dumps(changed_card), card_key))
            con.commit()
        assert [module for module, _, _ in prep._modules_needing_card(key)] == ["src"]
    finally:
        prep.close()


def test_hot_query_capsule_uses_current_module_summaries(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    key = str(root)
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"enabled": False, "hot_queries": ["navigation"]}}
    revision = ["unchanged-rag"]
    rag = SimpleNamespace(index_reset=False, revision=lambda **_kwargs: revision[0])
    prep = ProjectPreprocessor(cfg, None, rag, None, None, RepositoryTools(cfg))
    generated = []

    def deterministic_query(_root, query, **_kwargs):
        generated.append(query)
        return {"direct_answer": True, "confidence": 1}

    prep.deterministic = SimpleNamespace(query=deterministic_query, related_paths=lambda *_args: ["src/example.py"])
    monkeypatch.setattr(prep, "_yield", lambda: False)
    old_module = {"module": "src", "purpose": "old navigation"}
    capsule = {"intent": "navigation", "paths": ["src/example.py"], "modules": [old_module]}
    try:
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,'running','hot_queries',1,1)",
                (key, "workspace"),
            )
            con.execute("INSERT INTO hot_query_state(root,query,revision_hash,updated_at) VALUES(?,'navigation',?,1)",
                        (key, revision[0]))
            con.execute(
                "INSERT INTO task_capsules(root,query,revision_hash,capsule_json,updated_at) VALUES(?,'navigation',?,?,1)",
                (key, revision[0], json.dumps(capsule)),
            )
            con.commit()
        prep._store_module_card(key, "src", "old-module", {"purpose": old_module["purpose"]})
        before = prep.lookup(key, "navigation")
        assert before["capsules"][0]["modules"] == [old_module]

        prep._store_module_card(key, "src", "new-module", {"purpose": "unrelated implementation"})
        prep._store_module_card(key, "docs", "new-docs", {"purpose": "new navigation"})
        after = prep.lookup(key, "navigation")
        assert after["context_revision"] != before["context_revision"]
        assert after["capsules"][0]["paths"] == capsule["paths"]
        assert after["capsules"][0]["modules"] == [{"module": "docs", "purpose": "new navigation"}]
        assert prep._step_hot_query(dict(prep._project_row(key))) is True
        assert generated == []

        revision[0] = "new-rag"
        assert prep._step_hot_query(dict(prep._project_row(key))) is True
        assert generated == ["navigation"]
        with closing(prep._connect()) as con:
            persisted = con.execute("SELECT capsule_json FROM task_capsules WHERE root=?", (key,)).fetchone()[0]
        assert "modules" not in json.loads(persisted)
        assert prep.lookup(key, "navigation")["capsules"][0]["modules"] == after["capsules"][0]["modules"]
    finally:
        prep.close()


@pytest.mark.parametrize("modules_allowed", [True, False])
def test_removed_module_disappears_from_project_and_capsule(tmp_path, monkeypatch, modules_allowed):
    root = tmp_path / "project"
    key = str(root)
    cfg = {"server": {"state_dir": str(tmp_path / "state")},
           "preprocessing": {"enabled": False, "reject_temp_projects": False}}
    services = SimpleNamespace(repo_profile=lambda _root: {}, repo_map=lambda *_args: {})
    rag = SimpleNamespace(index_reset=False, workspace_id=lambda _root: "workspace")
    prep = ProjectPreprocessor(cfg, services, rag, _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        source = b"value = 1\n"
        for module in ("gone", "pending"):
            path = root / module / "source.py"
            path.parent.mkdir(parents=True)
            path.write_bytes(source)
        prep.enabled = True
        assert prep.register(key)["success"] is True
        monkeypatch.setattr(prep, "_yield", lambda: False)
        gone_summary = {"module": "gone", "purpose": "navigation for removed source"}
        for module in ("gone", "pending"):
            _card_ref(prep, root, f"{module}/source.py", source)
            prep._store_module_card(key, module, f"rev-{module}", {"purpose": f"navigation for {module}"})
        other_root = str(tmp_path / "other-worktree")
        prep._store_module_card(other_root, "gone", "other-rev", {"purpose": "other navigation"})
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO project_cards(root,revision_hash,card_json,updated_at) VALUES(?,'old-project',?,1)",
                (key, json.dumps({"summary": "gone, pending"})),
            )
            con.execute(
                "INSERT INTO task_capsules(root,query,revision_hash,capsule_json,updated_at) VALUES(?,'navigation','rag',?,1)",
                (key, json.dumps({"intent": "navigation", "modules": [gone_summary]})),
            )
            con.commit()
        before = prep.lookup(key, "navigation")
        assert {item["module"] for item in before["capsules"][0]["modules"]} == {"gone", "pending"}

        (root / "gone" / "source.py").unlink()
        assert prep._step_inventory(dict(prep._project_row(key)))
        prep._set_project(key, phase="modules", status="running")
        prep.deterministic = SimpleNamespace(project_card=lambda _root, _profile, _map, modules: {
            "success": True, "confidence": 1,
            "card": {"summary": ", ".join(item["module"] for item in modules)},
        })
        monkeypatch.setattr(prep, "_project_phase_allowed", lambda _root, phase: phase != "modules" or modules_allowed)
        assert prep._step(dict(prep._project_row(key)))
        assert prep._project_row(key)["phase"] == "project"

        with monkeypatch.context() as patch:
            patch.setattr(prep, "deterministic", None)
            patch.setattr(prep, "_gpu_yield", lambda: False)
            patch.setattr(prep, "_run_background_generate", lambda *_args: {"preempted": True})
            assert prep._step(dict(prep._project_row(key))) is False
        assert prep.lookup(key, "navigation")["project"]["summary"] == "gone, pending"
        assert {item["module"] for item in prep.lookup(key, "navigation")["modules"]} == {"gone", "pending"}

        render = prep.deterministic.project_card

        def restore_before_publish(*args):
            _card_ref(prep, root, "gone/source.py", source)
            return render(*args)

        with monkeypatch.context() as patch:
            patch.setattr(prep.deterministic, "project_card", restore_before_publish)
            assert prep._step(dict(prep._project_row(key))) is False
        assert prep.lookup(key, "navigation")["project"]["summary"] == "gone, pending"
        with closing(prep._connect()) as con:
            con.execute("DELETE FROM file_refs WHERE root=? AND path='gone/source.py'", (key,))
            con.commit()

        assert prep._step(dict(prep._project_row(key)))
        after = prep.lookup(key, "navigation")
        assert [item["module"] for item in after["modules"]] == ["pending"]
        assert [item["module"] for item in after["capsules"][0]["modules"]] == ["pending"]
        assert after["project"]["summary"] == "pending"
        with closing(prep._connect()) as con:
            assert con.execute("SELECT revision_hash FROM module_cards WHERE root=? AND module='gone'", (other_root,)).fetchone()[0] == "other-rev"
    finally:
        prep.close()


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
    config_path.write_text("[local_ai_hub]\nconfig_schema_version = 1\n", encoding="utf-8")
    effective = load_config(config_path, probe_hardware=False)
    assert effective["preprocessing"]["disable_llm_card_synthesis"] is False
    assert effective["background_gpu"]["enabled"] is False
    config_path.write_text("[local_ai_hub]\nconfig_schema_version = 1\n[preprocessing]\ndisable_llm_card_synthesis = true\n[background_gpu]\nenabled = false\n", encoding="utf-8")
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


@pytest.mark.parametrize("extra", [{}, {"preempted": True, "outcome_unknown": True}])
def test_timeout_keeps_provisional_and_records_bounded_retry_state(tmp_path, extra):
    responses = [{"success": False, "error_code": "timeout", "error": "generation timed out", **extra}]
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


@pytest.mark.parametrize("late_result", [
    {"success": False, "preempted": True},
    {"success": False, "error": "late model failure"},
    {"success": True, "model": "configured-model", "data": _enriched_card()},
])
def test_expired_enrichment_result_cannot_overwrite_successor(tmp_path, late_result):
    gpu = SimpleNamespace(ready=lambda: True)
    prep, root, digest, provisional_key = _provisional_enrichment_fixture(tmp_path, gpu)
    successor = None
    try:
        def generate_late(_tasks, **_kwargs):
            nonlocal successor
            with closing(prep._connect()) as con, con:
                con.execute("UPDATE file_card_enrichment SET lease_until=0 WHERE content_hash=?", (digest,))
            successor = prep._claim_file_card_enrichment(digest, "configured-model")
            assert successor is not None
            return [late_result]

        gpu.generate_many = generate_late
        prep._step_file_card({"root": str(root), "phase": "files"})

        with closing(prep._connect()) as con:
            state = con.execute(
                "SELECT status,attempts,lease_until,claim_id FROM file_card_enrichment WHERE content_hash=?", (digest,),
            ).fetchone()
            assert tuple(state[:2]) == ("running", 2)
            assert state["lease_until"] > time.time()
            assert state["claim_id"] == successor.claim_id
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == provisional_key
            assert con.execute("SELECT COUNT(*) FROM content_cards").fetchone()[0] == 1
    finally:
        prep.close()


def test_card_publication_and_claim_completion_roll_back_together(tmp_path):
    prep, root, digest, provisional_key = _provisional_enrichment_fixture(tmp_path, None)
    try:
        claim = prep._claim_file_card_enrichment(digest, "configured-model")
        assert claim is not None
        key = prep._content_card_key(digest)
        with closing(prep._connect()) as con, con:
            item = con.execute("SELECT * FROM file_refs WHERE root=?", (str(root),)).fetchone()
            con.execute("""CREATE TRIGGER fail_card_publication BEFORE INSERT ON content_cards
                BEGIN SELECT RAISE(ABORT,'blocked card publication'); END""")

        with pytest.raises(sqlite3.IntegrityError, match="blocked card publication"):
            prep._store_file_card(str(root), item, key, _enriched_card(), "configured-model", enrichment_claim=claim)
        with closing(prep._connect()) as con, con:
            assert tuple(con.execute(
                "SELECT status,claim_id FROM file_card_enrichment WHERE content_hash=?", (digest,),
            ).fetchone()) == ("running", claim.claim_id)
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == provisional_key
            con.execute("DROP TRIGGER fail_card_publication")
            con.execute("UPDATE file_card_enrichment SET lease_until=0 WHERE content_hash=?", (digest,))

        assert prep._store_file_card(str(root), item, key, _enriched_card(), "configured-model", enrichment_claim=claim)
        assert not prep._finish_file_card_enrichment(claim, success=False, preempted=True)
        with closing(prep._connect()) as con:
            assert tuple(con.execute(
                "SELECT status,lease_until,claim_id FROM file_card_enrichment WHERE content_hash=?", (digest,),
            ).fetchone()) == ("complete", 0, None)
            assert con.execute("SELECT card_key FROM file_refs WHERE root=?", (str(root),)).fetchone()[0] == key
    finally:
        prep.close()


def test_legacy_enrichment_rows_keep_existing_attempts_and_retry(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as con, con:
        con.execute("""CREATE TABLE file_card_enrichment (
            content_hash TEXT NOT NULL, model TEXT NOT NULL, pipeline_version TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL, retry_after REAL NOT NULL,
            lease_until REAL NOT NULL, last_error TEXT, updated_at REAL NOT NULL,
            PRIMARY KEY(content_hash,model,pipeline_version)
        )""")
        con.execute("""INSERT INTO file_card_enrichment VALUES
            ('running-hash','configured-model','legacy-test','running',1,0,?,NULL,0),
            ('failed-hash','configured-model','legacy-test','failed',2,?,0,'timeout',0)""",
            (time.time() + 120, time.time() + 120),
        )
    config = {"server": {"state_dir": str(state)}, "preprocessing": {"enabled": False}}
    prep = ProjectPreprocessor(config, None, None, None, None, RepositoryTools(config))
    try:
        monkeypatch.setattr(prep, "_file_card_pipeline_version", lambda: "legacy-test")
        assert prep._claim_file_card_enrichment("running-hash", "configured-model") is None
        assert prep._claim_file_card_enrichment("failed-hash", "configured-model") is None
        with closing(prep._connect()) as con, con:
            assert tuple(con.execute("""SELECT status,attempts,last_error,claim_id FROM file_card_enrichment
                WHERE content_hash='failed-hash'""").fetchone()) == ("failed", 2, "timeout", None)
            con.execute("UPDATE file_card_enrichment SET lease_until=0 WHERE content_hash='running-hash'")
        claim = prep._claim_file_card_enrichment("running-hash", "configured-model")
        assert claim is not None
        with closing(prep._connect()) as con:
            assert tuple(con.execute("""SELECT status,attempts,claim_id FROM file_card_enrichment
                WHERE content_hash='running-hash'""").fetchone()) == ("running", 2, claim.claim_id)
    finally:
        prep.close()


@pytest.mark.parametrize(("response", "delay"), [
    ({"preempted": True, "error": "foreground work pending"}, 0),
    ({"preempted": True, "retry_after_seconds": 12}, 12),
    ({"retryable": True, "last_admission_state": "rejected"}, 60),
    ({"last_admission_state": "rejected", "last_admission_reason": "target_vram_estimate_unavailable"}, 300),
])
def test_preemption_preserves_provisional_and_next_run_resumes(tmp_path, response, delay):
    responses = [{"success": False, **response}]
    calls = []
    gpu = SimpleNamespace(ready=lambda: True,
                          generate_many=lambda tasks, **_kw: calls.extend(tasks) or list(responses))
    prep, root, digest, provisional_key = _provisional_enrichment_fixture(tmp_path, gpu)
    try:
        before = time.time()
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
        assert before + delay <= state["retry_after"] <= time.time() + delay

        responses[:] = [{"success": True, "model": "configured-model", "data": _enriched_card()}]
        if delay:
            assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
            assert len(calls) == 1
            with closing(prep._connect()) as con, con:
                con.execute("UPDATE file_card_enrichment SET retry_after=0 WHERE content_hash=?", (digest,))
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


def test_scheduler_deferral_preserves_completed_prefix_of_card_batch(tmp_path):
    prep, root, _, _ = _provisional_enrichment_fixture(tmp_path, None)
    calls = []
    try:
        for stem in ("Second", "Third"):
            path = stem.lower() + ".py"
            source = f"class {stem}:\n    pass\n".encode()
            (root / path).write_bytes(source)
            _card_ref(prep, root, path, source)

        def generate(model, prompt, *_args):
            calls.append(prompt.splitlines()[0].removeprefix("FILE: "))
            if len(calls) == 2:
                raise _RetryablePreprocessingError("scheduler busy", retry_after_seconds=30)
            return {"success": True, "model": model, "data": _enriched_card()}

        prep._run_background_generate = generate
        before = time.time()
        with pytest.raises(_RetryablePreprocessingError, match="scheduler busy"):
            prep._step_file_card({"root": str(root), "phase": "files"})
        with closing(prep._connect()) as con, con:
            rows = {row[0]: tuple(row[1:]) for row in con.execute(
                """SELECT f.path,e.status,e.attempts,e.retry_after,c.model
                   FROM file_refs f JOIN file_card_enrichment e ON e.content_hash=f.content_hash
                   JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?""", (str(root),),
            )}
            assert rows.pop(calls[0]) == ("complete", 1, 0, "configured-model")
            assert len(rows) == 2
            for status, attempts, retry_after, model in rows.values():
                assert (status, attempts, model) == ("pending", 0, "deterministic-stub")
                assert before + 30 <= retry_after <= time.time() + 30
            con.execute("UPDATE file_card_enrichment SET retry_after=0 WHERE status='pending'")

        assert prep._step_file_card({"root": str(root), "phase": "files"}) is True
        assert len(calls) == 4
        assert set(calls[2:]) == set(rows)
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

        prep.deterministic = SimpleNamespace(
            module_card=lambda *_args: {"success": True, "confidence": 1, "card": {}},
            project_card=lambda *_args: {"success": True, "confidence": 1, "card": {}},
        )
        resumed = dict(prep._project_row(str(root)))
        assert prep._run_project_step(resumed) is True
        assert prep._project_row(str(root))["phase"] == "file_card_enrichment"
        assert prep._run_project_step(dict(prep._project_row(str(root)))) is True
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


def test_retryable_preprocessing_error_keeps_structured_error_code():
    error = _RetryablePreprocessingError(
        "GPU admission is unavailable", error_code="gpu_reserved",
    )

    assert str(error) == "GPU admission is unavailable"
    assert error.error_code == "gpu_reserved"
    assert error.retryable is True
