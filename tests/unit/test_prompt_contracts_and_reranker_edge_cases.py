from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub import prompt_contracts
from local_ai_hub.reranker import Reranker


def test_prompt_contracts_string_iterable_and_limits():
    # Single string criterion or evidence should not iterate over characters
    pkg = prompt_contracts.build_prompt(
        operation="delegate",
        model="qwen2.5-coder:7b",
        task="Check single string handling",
        acceptance_criteria="Single Acceptance Criterion",  # type: ignore
        evidence_ids="single_ev_id",  # type: ignore
        changed_paths="single/file.py",  # type: ignore
    )
    assert "- Single Acceptance Criterion" in pkg.user
    assert "- single_ev_id" in pkg.user
    assert "- single/file.py" in pkg.user

    # _lines with boolean or invalid limit
    lines_bool = prompt_contracts._lines(["a", "b"], limit=True)  # type: ignore
    assert "- none supplied" in lines_bool or "- a" in lines_bool

    # _clip with boolean or invalid limit
    assert prompt_contracts._clip("hello", limit=True) == ""  # type: ignore
    assert prompt_contracts._clip("hello", limit=-1) == ""

    # cannot_model_perform
    assert prompt_contracts.cannot_model_perform("qwen2.5-coder:7b", "apply_changes") is True
    assert prompt_contracts.cannot_model_perform("qwen2.5-coder:7b", "root_cause") is False
    assert prompt_contracts.cannot_model_perform(None, "anything") is True  # type: ignore

    # list_supported_models
    models = prompt_contracts.list_supported_models()
    assert "qwen2.5-coder:7b" in models
    assert "qwen3.5:9b" in models


def test_reranker_init_with_invalid_configs(tmp_path: Path):
    # None or non-dict config
    r1 = Reranker(None)  # type: ignore
    assert r1.is_enabled() is True
    assert r1.is_loaded() is False
    assert r1.batch_size == 16
    assert r1.max_length == 1024
    assert r1.active_model_name() == "BAAI/bge-reranker-base"

    # NaN / Inf / bool values in config
    r2 = Reranker({
        "server": {"state_dir": str(tmp_path / "state")},
        "models": {
            "reranker": "custom/model\x00bad",
            "reranker_device": "cpu\x00bad",
            "reranker_backend": "torch\x00bad",
        },
        "features": {"reranker": False},
        "cpu_retrieval": {
            "reranker_batch_size": float("nan"),
            "reranker_max_length": float("inf"),
            "foreground_priority": True,
        },
        "cache": {
            "reranker": True,
            "reranker_ttl_seconds": float("nan"),
            "reranker_max_entries": True,
            "l1_reranker_entries": float("inf"),
            "l1_reranker_ttl_seconds": -5.0,
        },
    })
    assert r2.is_enabled() is False
    assert "\x00" not in r2.active_model_name()
    assert "\x00" not in r2.device
    assert "\x00" not in r2.backend
    assert r2.batch_size >= 1
    assert r2.max_length >= 128


def test_reranker_rerank_edge_cases():
    r = Reranker({"features": {"reranker": False}})
    # Empty documents
    res_empty = r.rerank("query", [])
    assert res_empty["success"] is True
    assert res_empty["results"] == []

    # Non-list documents
    res_none = r.rerank("query", None)  # type: ignore
    assert res_none["success"] is True
    assert res_none["results"] == []

    # Disabled reranker
    res_disabled = r.rerank("query", ["doc1", "doc2"])
    assert res_disabled["success"] is False
    assert "disabled" in res_disabled["error"]
