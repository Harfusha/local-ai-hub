from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from local_ai_hub.operational_mode import set_operational_mode
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def test_preprocess_cards_uses_draft_model_cascade(tmp_path: Path, monkeypatch) -> None:
    set_operational_mode(tmp_path / "state", "active")
    root = tmp_path / "project"
    root.mkdir()
    source = b"CUSTOM_DATA = 123\n"
    (root / "example.py").write_bytes(source)
    digest = hashlib.sha256(source).hexdigest()

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": True,
            "model": "qwen2.5-coder-prep-v4:3b",
            "draft_model": "qwen2.5-coder-prep-v3:0.5b",
            "disable_llm_card_synthesis": False,
            "prefer_deterministic_cards": False,
        },
    }

    generated_tasks = []

    def fake_generate(prompt, system, schema, max_tokens, source, **kwargs):
        generated_tasks.append({"source": source, "prompt": prompt})
        if source == "preprocess:draft-card":
            return {
                "success": True,
                "data": {
                    "purpose": "fast draft custom data",
                    "symbols": ["CUSTOM_DATA"],
                    "dependencies": [],
                },
            }
        return {"success": False}

    gpu = SimpleNamespace(
        enabled=True,
        ready=lambda: True,
        model="qwen2.5-coder-prep-v4:3b",
        generate=fake_generate,
        generate_many=lambda tasks, **kwargs: [
            {"success": True, "model": "qwen2.5-coder-prep-v4:3b", "data": {"purpose": "final enriched", "symbols": ["CUSTOM_DATA"], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": ["example"], "evidence": []}}
            for _ in tasks
        ],
        cpu_fallback_enabled=False,
    )

    services = SimpleNamespace(
        _generate=lambda model, prompt, system, max_tokens, temp, **kwargs: fake_generate(
            prompt, system, None, max_tokens, kwargs.get("source", "service")
        ),
        _fallback_models=lambda model: (),
    )

    rag = SimpleNamespace(workspace_id=lambda _root: "default_workspace")
    scheduler = SimpleNamespace(background_allowed=lambda: True, foreground_busy=lambda: False)
    prep = ProjectPreprocessor(
        cfg, services, rag, scheduler, None, RepositoryTools(cfg), background_gpu=gpu
    )
    prep.enabled = True
    monkeypatch.setattr(prep, "_yield", lambda: False)
    assert prep.register(str(root))["success"] is True

    resolved_root = prep._root(str(root))
    # Seed file_refs
    digest = hashlib.sha256(source).hexdigest()
    with closing(prep._connect()) as con, con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,card_key,updated_at) VALUES(?,?,?,?,?,?,?)",
            (resolved_root, "example.py", digest, len(source), 1, None, 0),
        )
    prep._step_file_card({"root": resolved_root, "phase": "files"})

    # Verify that the draft model was invoked
    draft_calls = [t for t in generated_tasks if t["source"] == "preprocess:draft-card"]
    assert len(draft_calls) >= 1
    assert "extract facts" in draft_calls[0]["prompt"]

    # Verify that content_cards now holds the stored card
    with closing(prep._connect()) as con:
        cards = con.execute("SELECT * FROM content_cards").fetchall()
        assert len(cards) >= 1


def test_preprocess_cascade_disabled_toggle(tmp_path: Path) -> None:
    cfg = {
        "preprocessing": {
            "model": "qwen2.5-coder-prep-v4:3b",
            "draft_model": "qwen2.5-coder-prep-v3:0.5b",
            "cascade_enabled": False,
        },
    }
    prep = ProjectPreprocessor(cfg, None, None, None, None, RepositoryTools(cfg))
    assert prep._configured_preprocessing_draft_model() == ""


def test_hardware_profiles_enable_cascade_by_default() -> None:
    from local_ai_hub.hardware import PROFILE_OVERRIDES, profile_overrides

    for profile_name in PROFILE_OVERRIDES:
        ov = profile_overrides(profile_name)
        prep = ov.get("preprocessing", {})
        assert prep.get("cascade_enabled") is True, f"cascade_enabled not True in {profile_name}"
        assert prep.get("draft_model") == "qwen2.5-coder-prep-v3:0.5b", f"draft_model mismatch in {profile_name}"
        assert ov.get("models", {}).get("draft_code") == "qwen2.5-coder:0.5b", f"draft_code mismatch in {profile_name}"
        if profile_name in ("cpu", "integrated"):
            assert prep.get("model") == "qwen2.5-coder-prep-v3:1.5b", f"model should be 1.5b in {profile_name}"
            assert prep.get("refiner_model") == "", f"refiner_model should be empty/merged in {profile_name}"
        else:
            assert prep.get("model") == "qwen2.5-coder-prep-v4:3b", f"model should be 3b in {profile_name}"
            assert prep.get("refiner_model") == "qwen2.5-coder-prep-v3:1.5b", f"refiner_model mismatch in {profile_name}"
        if profile_name == "cpu":
            assert ov.get("models", {}).get("reasoning") == "qwen2.5-coder:3b", "cpu reasoning should be 3b"

