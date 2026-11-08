"""Regression test suite for Audit Round 1 findings (P0-1 through P1-6).
Documented in docs/AUDIT_6.0.0_FINDINGS_AND_ACTION_PLAN_2026-11-08.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.search_modes import classify_query, prefers_lexical_precision


def test_t1_01_ci_pyflakes_clean():
    """T1-01 (P0-1): pyflakes checks on src and tools pass with exit code 0."""
    res = subprocess.run(
        [sys.executable, "-m", "pyflakes", "src", "tools"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert res.returncode == 0, f"pyflakes failed with output:\n{res.stdout}\n{res.stderr}"


def test_t1_02_owned_model_timeout_includes_bounded_stderr():
    """T1-02 (P0-2): OwnedModelProcess timeout includes captured worker stderr."""
    from local_ai_hub.owned_model import _ModelProcess

    script = (
        "import sys, time; "
        "sys.stdin.readline(); "
        "sys.stderr.write('predict still running worker stderr output'); "
        "sys.stderr.flush(); "
        "time.sleep(5)"
    )
    process = _ModelProcess([sys.executable, "-u", "-c", script])
    try:
        with pytest.raises(TimeoutError, match="model operation timed out") as raised:
            process.request({"operation": "predict"}, timeout=0.1)
        assert "predict still running worker stderr output" in str(raised.value)
    finally:
        process.close()


def test_t1_03_upgrade_contract_consistency(tmp_path: Path):
    """T1-03 (P0-3): RELEASE.json version is 6.0.0 and state lifecycle requires valid version."""
    root = Path(__file__).resolve().parent.parent
    release_json = root / "RELEASE.json"
    assert release_json.exists()
    data = json.loads(release_json.read_text(encoding="utf-8"))
    assert data.get("version") == "6.0.0"

    from local_ai_hub.state_lifecycle import ensure_state_version
    tmp_state = tmp_path / "test_state_compat"
    tmp_state.mkdir(parents=True, exist_ok=True)
    version_file = tmp_state / "state_version.json"
    version_file.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="State version 999 is newer than supported version"):
        ensure_state_version(tmp_state)


def test_t1_04_feature_defaults_in_defaults_toml():
    """T1-04 (P1-1): defaults.toml features match expected baseline."""
    root = Path(__file__).resolve().parent.parent
    defaults_file = root / "src" / "local_ai_hub" / "defaults.toml"
    assert defaults_file.exists()
    content = defaults_file.read_text(encoding="utf-8")
    assert "enriched_search = true" in content
    assert "batch_replacement = true" in content
    assert "diagnostic_artifacts = true" in content


def test_t1_05_lexical_search_fingerprint_ttl_caching(tmp_path: Path):
    """T1-05 (P1-2): LocalAIServices._repo_search_lexical respects fingerprint TTL."""
    from local_ai_hub.services import LocalAIServices

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file.txt").write_text("hello world\n", encoding="utf-8")

    mock_repo_state = MagicMock()
    mock_repo_state.fingerprint.return_value = {
        "fingerprint": "mock_revision_123",
        "stale": False,
        "degraded": False,
    }
    mock_repo_tools = MagicMock()
    mock_repo_tools.search.return_value = {
        "success": True,
        "results": [{"path": "file.txt", "text": "hello world"}],
        "total_matches": 1,
        "count_exact": True,
        "has_more": False,
    }

    services = LocalAIServices(
        config={"server": {"state_dir": str(tmp_path / "state")}},
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=mock_repo_tools,
        repo_state=mock_repo_state,
    )
    res = services._repo_search_lexical(str(repo_dir), "hello")
    assert res.get("success") is True
    assert mock_repo_state.fingerprint.called
    for call in mock_repo_state.fingerprint.call_args_list:
        args, kwargs = call
        assert kwargs.get("force") is not True, f"fingerprint was called with force=True: {call}"


def test_t1_06_query_classification_precision():
    """T1-06 (P1-3): classify_query accurately classifies query intents."""
    assert classify_query("repo_search") == "exact_symbol"
    assert classify_query("src/local_ai_hub/services.py") == "file_path"
    assert classify_query("how to configure database") == "natural_language"
    assert classify_query("Python 3.13") == "mixed"

    assert prefers_lexical_precision("how to configure database") is False
    assert prefers_lexical_precision("repo_search") is True


def test_t1_07_rag_embedding_model_instantiation(tmp_path: Path):
    """T1-07 (P1-4): EmbeddingModel initializes cleanly with configured backend and device."""
    from local_ai_hub.embeddings import EmbeddingModel

    config = {
        "models": {"embedding": "qwen3-embedding:0.6b", "embedding_device": "cpu"},
        "server": {"state_dir": str(tmp_path / "state")},
    }
    model = EmbeddingModel(config)
    assert model.model_name == "qwen3-embedding:0.6b"
    assert model.device == "cpu"


def test_t1_08_gpu_admission_model_policy():
    """T1-08 (P1-6): ModelExecutionPolicy correctly identifies small vs heavy model profiles."""
    from local_ai_hub.model_policy import ModelExecutionPolicy

    policy = ModelExecutionPolicy({})
    assert policy._is_small_model("qwen2.5-coder:1.5b") is True
    assert policy._is_small_model("qwen2.5-coder:3b") is True
    assert policy._is_small_model("qwen2.5-coder:7b") is False
    assert policy._is_small_model("qwen2.5:14b") is False
