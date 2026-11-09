"""Opt-in isolated CPU inference; never pulls or touches the live Hub's server."""
from contextlib import closing
import os
import socket
from types import SimpleNamespace

import pytest

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.operational_mode import publish_preprocessing_ready, set_operational_mode
from local_ai_hub.preprocess import PREPROCESS_ANALYZER_VERSION, ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


class _IdleScheduler:
    def foreground_busy(self):
        return False

    def foreground_idle_seconds(self):
        return 1000.0

    def release_background_gpu(self):
        return None


class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.mark.skipif(os.environ.get("LOCAL_AI_TEST_PREPROCESS_CPU") != "1", reason="explicit isolated CPU model test required")
def test_real_cpu_model_enriches_existing_stub(tmp_path):
    model = "qwen2.5-coder:3b"
    project = tmp_path / "project"
    project.mkdir()
    content = "The inventory module tracks products and their quantities.\n"
    (project / "inventory.md").write_text(content, encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cfg = {
        "server": {"state_dir": str(tmp_path / "state"), "auto_start_ollama": False},
        "ollama": {"enabled": True},
        "preprocessing": {"enabled": False, "model": model, "prefer_deterministic_cards": False,
                          "disable_llm_card_synthesis": True, "exclusive": {"enrich_stub_cards": True, "model_parallel": 1}},
        "background_gpu": {"enabled": False, "cpu_fallback_enabled": True,
                           "cpu_ollama_url": f"http://127.0.0.1:{port}", "cpu_context_tokens": 4096,
                           "request_timeout_seconds": 150, "file_batch_size": 1},
    }
    scheduler = _IdleScheduler()
    worker = IdleGPUWorker(cfg, scheduler)
    prep = ProjectPreprocessor(cfg, scheduler, SimpleNamespace(index_reset=False), _Noop(), _Noop(),
                               RepositoryTools(cfg), background_gpu=worker)
    try:
        with closing(prep._connect()) as con:
            con.execute("INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?)",
                        ("stub", "test-content", "deterministic-stub", PREPROCESS_ANALYZER_VERSION, "{}", 0, 0, 0))
            con.execute("INSERT INTO file_refs(root,path,content_hash,size,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (str(project), "inventory.md", "test-content", len(content.encode()), 0, 1, "stub", 0))
            con.commit()
        snapshot = set_operational_mode(tmp_path / "state", "preprocessing")
        publish_preprocessing_ready(tmp_path / "state", snapshot)
        assert prep._step_file_card({"root": str(project), "phase": "files"}) is True, worker.status()
        with closing(prep._connect()) as con:
            row = con.execute("SELECT c.model,c.card_json FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=?", (str(project),)).fetchone()
            assert row["model"] == model
            import json
            card = json.loads(row["card_json"])
            assert prep._valid_enriched_file_card(card)
            assert any(term in json.dumps(card).lower() for term in ("invent", "product", "quantit", "stock"))
            assert con.execute("SELECT COUNT(*) FROM content_cards WHERE card_key='stub'").fetchone()[0] == 1
    finally:
        prep.close()
        worker.close()
    assert not worker.cpu_runtime.is_online(), "isolated CPU server did not stop"
