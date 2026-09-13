from __future__ import annotations

import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.external_tools import ExternalCodeIntelligence
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.services import LocalAIServices


def test_revision_scoped_error_markers() -> None:
    # 1. ExternalCodeIntelligence
    assert ExternalCodeIntelligence._is_revision_scoped_index_error("index", "codegraph index exited 1: No configuration file found. Using defaults.")
    assert ExternalCodeIntelligence._is_revision_scoped_index_error("index", "codegraph index exited 1: Loaded configuration from: C:/project/.env")
    assert ExternalCodeIntelligence._is_revision_scoped_index_error("index", "indexing exceeded 120s")
    assert not ExternalCodeIntelligence._is_revision_scoped_index_error("query", "No configuration file found")

    # 2. ProjectPreprocessor
    assert ProjectPreprocessor._external_error_is_revision_scoped("No configuration file found. Using defaults.")
    assert ProjectPreprocessor._external_error_is_revision_scoped("indexing exceeded 120s")
    assert ProjectPreprocessor._external_error_is_revision_scoped("codegraph index exited 1: Loaded configuration from: C:/project/.env")
    assert ProjectPreprocessor._external_error_is_revision_scoped("no module named 'codegraphcontext'")


def test_command_broker_rejects_nonexistent_cwd(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    bad_cwd = tmp_path / "does_not_exist_dir"
    res = broker.run("pytest -q", cwd=str(bad_cwd), tenant="test")
    assert res["success"] is False
    assert res["preflight"] is True
    assert res["terminal"] is True
    assert "working directory does not exist" in res["error"]


def test_services_embed_defaults_background_on_low_priority() -> None:
    mock_scheduler = MagicMock()
    mock_scheduler.submit.return_value = {"success": True, "embeddings": [[0.1, 0.2]]}
    mock_runtime = MagicMock()
    mock_runtime.request.return_value = {"embeddings": [[0.1, 0.2]]}

    svc = object.__new__(LocalAIServices)
    svc.config = {"models": {"embedding_backend": "ollama", "embedding": "test-embed"}}
    svc.scheduler = mock_scheduler
    svc.runtime = mock_runtime

    # Priority 0 -> should default background=True
    svc.embed(["test text"], tenant="test", priority=0)
    args, kwargs = mock_scheduler.submit.call_args
    assert kwargs.get("background") is True
    assert kwargs.get("priority") == 0

    # Priority 3 -> should default background=False
    svc.embed(["test text"], tenant="test", priority=3)
    args, kwargs = mock_scheduler.submit.call_args
    assert kwargs.get("background") is False
    assert kwargs.get("priority") == 3

    # Explicit background=True with priority 5
    svc.embed(["test text"], tenant="test", priority=5, background=True)
    args, kwargs = mock_scheduler.submit.call_args
    assert kwargs.get("background") is True


def test_preprocessor_external_index_degrades_and_skips_on_revision_error(tmp_path: Path) -> None:
    proj_dir = tmp_path / "sample_project"
    proj_dir.mkdir()
    (proj_dir / "app.py").write_text("print('hello')", encoding="utf-8")

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
        "code_intelligence": {"preprocess_codegraph": True},
    }

    mock_scheduler = MagicMock()
    mock_scheduler.background_allowed.return_value = True
    mock_scheduler.foreground_busy.return_value = False

    mock_ext = MagicMock()
    mock_ext.backend_available.return_value = False
    mock_ext.index.return_value = {
        "success": False,
        "backend": "codegraph",
        "error": "No configuration file found. Using defaults.",
    }

    prep = ProjectPreprocessor(
        cfg,
        services=MagicMock(),
        rag=MagicMock(),
        scheduler=mock_scheduler,
        runtime=MagicMock(),
        repo_tools=MagicMock(),
        external_tools=mock_ext,
    )

    try:
        row = {"root": str(proj_dir), "workspace": "test-ws", "phase": "codegraph", "force_refresh": False}

        # 1. First step should execute external_tools.index, record explicit unavailability, advance to next_phase
        res1 = prep._step_external_index(row, "codegraph", "lexical")
        assert res1 is True
        assert mock_ext.index.call_count == 1

        # 2. Subsequent step for same revision should be skipped immediately without calling external_tools.index again!
        res2 = prep._step_external_index(row, "codegraph", "lexical")
        assert res2 is True
        assert mock_ext.index.call_count == 1  # Not called again!
        with closing(prep._connect()) as con:
            state = con.execute(
                "SELECT status,error FROM external_index_state WHERE root=? AND backend=?",
                (str(proj_dir), "codegraph"),
            ).fetchone()
        assert state[0] == "unavailable"
        assert "No configuration file found" in state[1]

    finally:
        prep.close()


def test_preprocessor_status_cache_invalidation(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    mock_repo_tools = MagicMock()
    mock_rag = MagicMock()
    mock_rag.workspace_id.return_value = "ws-test"
    prep = ProjectPreprocessor(
        cfg,
        services=MagicMock(),
        rag=mock_rag,
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=mock_repo_tools,
    )
    try:
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        prep._paused.set()
        prep.register(str(proj_dir))

        # 1. Fetch status - populates cache
        st1 = prep.status()
        assert st1["success"] is True
        assert "__all__" in prep._status_cache

        # 2. Update project via _set_project -> should invalidate status cache
        prep._set_project(str(proj_dir), phase="files")
        assert len(prep._status_cache) == 0

        # 3. Next status call sees the updated phase immediately
        st2 = prep.status()
        proj_entry = next(p for p in st2["projects"] if p["root"] == str(proj_dir))
        assert proj_entry["phase"] == "files"
    finally:
        prep.close()
