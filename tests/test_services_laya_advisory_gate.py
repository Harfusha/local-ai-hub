from __future__ import annotations

import tomllib
from pathlib import Path

from local_ai_hub.services import LocalAIServices


def test_laya_advisory_accepts_the_default_pinned_huggingface_checkpoint(tmp_path):
    services = LocalAIServices.__new__(LocalAIServices)
    defaults = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "defaults.toml").read_text(encoding="utf-8")
    )
    services.config = defaults
    calls = []
    services.laya_decision_evaluator = lambda operation, **kwargs: (
        calls.append((operation, kwargs))
        or {
            "success": True,
            "decision": {
                "mode": "advisory",
                "status": "success",
                "suggestion": "smart",
            },
        }
    )
    operation = {"decision": {"options": ["fast", "smart"]}}
    baseline = {
        "method": "model_router_classify",
        "suggestion": "fast",
        "evidence_id": "ev-route",
    }

    choice = services.evaluate_laya_advisory(operation, root=str(tmp_path), baseline=baseline)

    assert choice == "smart"
    assert calls == [(operation, {"root": str(tmp_path), "_server_baseline": baseline})]


def test_laya_advisory_rejects_unallowlisted_huggingface_repository(tmp_path):
    services = LocalAIServices.__new__(LocalAIServices)
    defaults = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "defaults.toml").read_text(encoding="utf-8")
    )
    defaults["laya"]["runtime"]["hf_repo_id"] = "untrusted/laya"
    services.config = defaults
    calls = []
    services.laya_decision_evaluator = lambda *args, **kwargs: calls.append((args, kwargs))

    choice = services.evaluate_laya_advisory(
        {"decision": {"options": ["fast", "smart"]}},
        root=str(tmp_path),
        baseline={
            "method": "model_router_classify",
            "suggestion": "fast",
            "evidence_id": "ev-route",
        },
    )

    assert choice is None
    assert calls == []
