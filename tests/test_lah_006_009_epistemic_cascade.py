import difflib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing

import pytest

from local_ai_hub.preprocess import (
    CARD_SCHEMA,
    PREPROCESS_ANALYZER_VERSION,
    ProjectPreprocessor,
)
from local_ai_hub.preprocess_controls import PreprocessRoleGraph
from local_ai_hub.repo_tools import RepositoryTools


class _Noop:
    def __getattr__(self, name):
        if name == "workspace_id":
            return lambda _root: "test-workspace"
        return lambda *args, **kwargs: None


def test_lah_006_adversarial_draft_model_symbols_rejected(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = b"class RealService:\n    def process(self):\n        return True\n"
    file_path = root / "service.py"
    file_path.write_bytes(source)
    content_hash = hashlib.sha256(source).hexdigest()

    draft_model = "test-draft-model"
    target_model = "test-target-model"
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": True,
            "model": target_model,
            "draft_model": draft_model,
            "cascade_enabled": True,
            "disable_llm_card_synthesis": False,
        },
    }

    prep = ProjectPreprocessor(cfg, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        prep.register(str(root))

        # Insert file into file_refs
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO file_refs(root,path,content_hash,size,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (str(root), "service.py", content_hash, len(source), 0, 1, None, 0),
            )
            con.commit()

        # Adversarial draft output claiming symbols and imports not in source
        adversarial_draft = {
            "success": True,
            "data": {
                "purpose": "Adversarial test service",
                "symbols": ["RealService", "FAKE_NOT_IN_SOURCE_SYMBOL"],
                "dependencies": ["fake_nonexistent_import"],
                "side_effects": [],
                "risks": [],
                "tests": [],
                "keywords": ["service"],
            },
        }

        # Mock draft run to return adversarial draft
        prep._run_background_generate = lambda model, *args, **kwargs: adversarial_draft

        # Step file card processing
        row = dict(prep._project_row(str(root)))
        prep._step_file_card(row)

        with closing(prep._connect()) as con:
            # Verify deterministic stub exists
            stub_card = con.execute(
                "SELECT card_key, model, card_json FROM content_cards WHERE content_hash=? AND model='deterministic-stub'",
                (content_hash,),
            ).fetchone()
            assert stub_card is not None
            stub_data = json.loads(stub_card["card_json"])
            assert stub_data["epistemic_class"] == "deterministic_fact"
            assert stub_data["confidence"] == 1.0

            # Verify draft card was stored under draft model, NOT deterministic-stub
            draft_card = con.execute(
                "SELECT card_key, model, card_json FROM content_cards WHERE content_hash=? AND model=?",
                (content_hash, draft_model),
            ).fetchone()
            assert draft_card is not None
            draft_data = json.loads(draft_card["card_json"])
            assert draft_data["epistemic_class"] == "llm_draft"
            assert draft_data["model"] == draft_model
            assert draft_data["confidence"] == 0.5
            # Crucial: FAKE_NOT_IN_SOURCE_SYMBOL and fake_nonexistent_import must be filtered out!
            assert "FAKE_NOT_IN_SOURCE_SYMBOL" not in draft_data["symbols"]
            assert "fake_nonexistent_import" not in draft_data["dependencies"]
            assert "RealService" in draft_data["symbols"]
    finally:
        prep.close()


def test_lah_007_role_graph_derived_immutably_and_disables_roles():
    # Test 1: Cascade enabled, fallback enabled
    cfg_on = {
        "preprocessing": {
            "model": "qwen2.5-coder:3b",
            "draft_model": "qwen2.5-coder:0.5b",
            "refiner_model": "qwen2.5-coder:1.5b",
            "cascade_enabled": True,
        },
        "resilience": {"model_fallback_enabled": True},
        "models": {"fast_code": "qwen2.5-coder:7b"},
    }
    prep_on = ProjectPreprocessor(cfg_on, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_on))
    graph_on = prep_on._role_graph()
    assert graph_on.primary_model == "qwen2.5-coder:3b"
    assert graph_on.cascade_enabled is True
    assert graph_on.draft_model == "qwen2.5-coder:0.5b"
    assert graph_on.refiner_model == "qwen2.5-coder:1.5b"
    assert graph_on.fallback_enabled is True
    assert "qwen2.5-coder:7b" in graph_on.fallback_models
    assert "qwen2.5-coder:1.5b" in graph_on.fallback_models
    assert "qwen2.5-coder:0.5b" in graph_on.fallback_models
    assert graph_on.effective_phases == ("deterministic", "draft", "refiner", "fallback")

    # Test 2: Cascade disabled -> draft & refiner MUST be None and omitted from fallbacks
    cfg_cascade_off = {
        "preprocessing": {
            "model": "qwen2.5-coder:3b",
            "draft_model": "qwen2.5-coder:0.5b",
            "refiner_model": "qwen2.5-coder:1.5b",
            "cascade_enabled": False,
        },
        "resilience": {"model_fallback_enabled": True},
        "models": {"fast_code": "qwen2.5-coder:7b"},
    }
    prep_off = ProjectPreprocessor(cfg_cascade_off, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_cascade_off))
    graph_off = prep_off._role_graph()
    assert graph_off.cascade_enabled is False
    assert graph_off.draft_model is None
    assert graph_off.refiner_model is None
    assert prep_off._configured_preprocessing_draft_model() == ""
    assert "qwen2.5-coder:0.5b" not in graph_off.fallback_models
    assert "qwen2.5-coder:1.5b" not in graph_off.fallback_models
    assert graph_off.effective_phases == ("deterministic", "fallback")

    # Test 3: Model fallback disabled -> fallbacks MUST be empty tuple
    cfg_fb_off = {
        "preprocessing": {"model": "qwen2.5-coder:3b", "cascade_enabled": True},
        "resilience": {"model_fallback_enabled": False},
        "models": {"fast_code": "qwen2.5-coder:7b"},
    }
    prep_fb_off = ProjectPreprocessor(cfg_fb_off, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_fb_off))
    graph_fb_off = prep_fb_off._role_graph()
    assert graph_fb_off.fallback_enabled is False
    assert graph_fb_off.fallback_models == ()
    assert prep_fb_off._file_card_fallbacks("qwen2.5-coder:3b") == ()


def test_lah_008_pipeline_fingerprint_selective_invalidation():
    cfg_base = {
        "preprocessing": {
            "model": "qwen2.5-coder:3b",
            "draft_model": "qwen2.5-coder:0.5b",
            "cascade_enabled": True,
            "file_card_output_tokens": 3072,
        },
        "resilience": {"model_fallback_enabled": True},
    }
    prep_base = ProjectPreprocessor(cfg_base, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_base))
    fp_base = prep_base._file_card_pipeline_version()

    # Changing cascade_enabled invalidates enrichment pipeline version
    cfg_cascade_off = {**cfg_base, "preprocessing": {**cfg_base["preprocessing"], "cascade_enabled": False}}
    prep_cascade_off = ProjectPreprocessor(cfg_cascade_off, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_cascade_off))
    fp_cascade_off = prep_cascade_off._file_card_pipeline_version()
    assert fp_base != fp_cascade_off

    # Changing sampling tokens invalidates enrichment pipeline version
    cfg_tokens = {**cfg_base, "preprocessing": {**cfg_base["preprocessing"], "file_card_output_tokens": 4096}}
    prep_tokens = ProjectPreprocessor(cfg_tokens, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_tokens))
    fp_tokens = prep_tokens._file_card_pipeline_version()
    assert fp_base != fp_tokens

    # Changing primary model invalidates enrichment pipeline version
    cfg_model = {**cfg_base, "preprocessing": {**cfg_base["preprocessing"], "model": "qwen2.5-coder:7b"}}
    prep_model = ProjectPreprocessor(cfg_model, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg_model))
    fp_model = prep_model._file_card_pipeline_version()
    assert fp_base != fp_model


def test_lah_009_diff_vs_full_prompt_selection_and_previous_card_key(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    initial_text = "\n".join([f"def func_{i}(): return {i}" for i in range(100)])
    (root / "mod.py").write_bytes(initial_text.encode("utf-8"))
    initial_hash = hashlib.sha256(initial_text.encode("utf-8")).hexdigest()

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": True,
            "model": "test-model",
            "cascade_enabled": False,
            "disable_llm_card_synthesis": False,
            "defer_file_card_enrichment": False,
        },
    }
    key = str(Path(root).resolve(strict=True))
    prep = ProjectPreprocessor(cfg, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg))
    try:
        prep.enabled = True
        monkeypatch.setattr(prep, "_background_work_allowed", lambda: True)
        monkeypatch.setattr(prep, "_yield", lambda: False)
        prep.register(key)

        # Seed initial card in content_cards and file_refs
        initial_card_key = "card_v1"
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at) VALUES(?,?,?,?,?,?,?)",
                (initial_card_key, initial_hash, "test-model", PREPROCESS_ANALYZER_VERSION, '{"purpose": "Initial summary"}', 0, 0),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,needs_hash,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (key, "mod.py", initial_hash, len(initial_text), 0, 1, initial_card_key, 0),
            )
            con.execute(
                "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
                (key, "mod.py", initial_hash, initial_text, 0),
            )
            con.commit()

        # Update file slightly: 2 lines changed out of 100 (<15%)
        minor_lines = [f"def func_{i}(): return {i}" for i in range(100)]
        minor_lines[0] = "def func_0(): return 'updated'"
        minor_lines[1] = "def func_1(): return 'updated'"
        minor_text = "\n".join(minor_lines)
        (root / "mod.py").write_bytes(minor_text.encode("utf-8"))

        matcher = difflib.SequenceMatcher(None, initial_text.splitlines(), minor_text.splitlines())
        assert matcher.ratio() >= 0.85  # <15% changed
        minor_hash = hashlib.sha256(minor_text.encode("utf-8")).hexdigest()
        with closing(prep._connect()) as con:
            con.execute(
                "UPDATE file_refs SET content_hash=?, card_key=NULL, size=? WHERE root=? AND path=?",
                (minor_hash, len(minor_text), key, "mod.py"),
            )
            con.commit()

        # Step file processing and capture generated prompt
        captured_prompts = []
        def mock_generate(tasks, **kwargs):
            for t in tasks:
                captured_prompts.append(t["prompt"])
            return [{"success": True, "model": "test-model", "data": {"purpose": "Updated", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": [], "evidence": [{"field": "purpose", "value": "Updated", "quote": "func_0"}]}}]

        gpu = SimpleNamespace(ready=lambda: True, generate_many=mock_generate)
        prep.background_gpu = gpu

        prep._step_file_card(dict(prep._project_row(key)))

        assert len(captured_prompts) == 1
        assert "DIFF (<15% lines changed):" in captured_prompts[0]
        assert "PREVIOUS SUMMARY:" in captured_prompts[0]
    finally:
        prep.close()
