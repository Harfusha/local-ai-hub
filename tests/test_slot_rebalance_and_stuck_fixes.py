from __future__ import annotations

import subprocess
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_ai_hub.preprocess import ProjectPreprocessor


def test_rebalance_processing_slots_promotes_preferred_root(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "max_preprocessing_projects": 3},
    }
    mock_rag = MagicMock()
    mock_rag.workspace_id.side_effect = lambda r: f"ws-{Path(r).name}"
    prep = ProjectPreprocessor(
        cfg,
        services=MagicMock(),
        rag=mock_rag,
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    try:
        now = time.time()
        with closing(prep._connect()) as con:
            for idx in range(1, 5):
                p = tmp_path / f"proj{idx}"
                p.mkdir()
                status = "running" if idx <= 3 else "waiting"
                con.execute(
                    "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(p), f"ws-proj{idx}", status, "hash", 0, 0, now, now - (100 - idx), now, 0, now - (100 - idx), "agent"),
                )
            con.commit()

            p4 = str(tmp_path / "proj4")
            prep._rebalance_processing_slots(con, preferred_root=p4)
            con.commit()

            rows = {r["root"]: r["status"] for r in con.execute("SELECT root, status FROM projects").fetchall()}
            assert rows[p4] == "queued"
            active_count = sum(1 for s in rows.values() if s in ("queued", "running"))
            assert active_count == 3
            waiting_count = sum(1 for s in rows.values() if s == "waiting")
            assert waiting_count == 1
    finally:
        prep.close()


def test_repair_registry_resets_orphaned_running_status(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    mock_rag = MagicMock()
    mock_rag.workspace_id.side_effect = lambda r: f"ws-{Path(r).name}"
    prep = ProjectPreprocessor(
        cfg,
        services=MagicMock(),
        rag=mock_rag,
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    try:
        now = time.time()
        p = tmp_path / "proj_running"
        p.mkdir()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(p), "ws-proj_running", "running", "hash", 0, 0, now, now, now, 0, now, "agent"),
            )
            con.commit()

        prep._repair_registry()

        with closing(prep._connect()) as con:
            status = con.execute("SELECT status FROM projects WHERE root=?", (str(p),)).fetchone()[0]
            assert status == "queued"
    finally:
        prep.close()


def test_register_promotes_waiting_project_to_queued(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "max_preprocessing_projects": 3},
    }
    mock_rag = MagicMock()
    mock_rag.workspace_id.side_effect = lambda r: f"ws-{Path(r).name}"
    prep = ProjectPreprocessor(
        cfg,
        services=MagicMock(),
        rag=mock_rag,
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    try:
        prep._paused.set()
        now = time.time()
        p = tmp_path / "proj_waiting"
        p.mkdir()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(p), "ws-proj_waiting", "waiting", "hash", 0, 0, now, now, now, 0, 0, "agent"),
            )
            con.commit()

        res = prep.register(str(p))
        assert res["success"] is True

        with closing(prep._connect()) as con:
            status = con.execute("SELECT status FROM projects WHERE root=?", (str(p),)).fetchone()[0]
            assert status == "queued"
    finally:
        prep.close()


def test_next_cpu_project_selects_diagnostics_phase(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    mock_rag = MagicMock()
    mock_rag.workspace_id.side_effect = lambda r: f"ws-{Path(r).name}"
    prep = ProjectPreprocessor(
        cfg,
        services=MagicMock(),
        rag=mock_rag,
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    try:
        now = time.time()
        p = tmp_path / "proj_diag"
        p.mkdir()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(p), "ws-proj_diag", "queued", "diagnostics", 0, 0, now, now, now, 0, now, "agent"),
            )
            con.commit()

        row = prep._next_cpu_project()
        assert row is not None
        assert row["root"] == str(p)
        assert row["phase"] == "diagnostics"
    finally:
        prep.close()


def test_step_diagnostics_handles_timeout_cleanly(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False, "idle_diagnostics_enabled": True},
    }
    mock_rag = MagicMock()
    mock_rag.workspace_id.side_effect = lambda r: f"ws-{Path(r).name}"
    mock_services = MagicMock()
    # Mock validation command to sleep
    command = ["python", "-c", "import time; time.sleep(30)"]
    mock_services.repo_profile.return_value = {"validation_commands": [{"argv": command}]}
    mock_scheduler = MagicMock()
    mock_scheduler.background_allowed.return_value = True
    mock_scheduler.foreground_busy.return_value = False

    prep = ProjectPreprocessor(
        cfg,
        services=mock_services,
        rag=mock_rag,
        scheduler=mock_scheduler,
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    try:
        now = time.time()
        p = tmp_path / "proj_diag_timeout"
        p.mkdir()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(p), "ws-proj_diag_timeout", "running", "diagnostics", 0, 0, now, now, now, 0, now, "agent"),
            )
            con.commit()

        timeout_error = subprocess.TimeoutExpired(cmd=command, timeout=15.0)
        timeout_error.cleanup_confirmed = True
        with patch("local_ai_hub.process_utils.run_hidden", side_effect=timeout_error) as run_hidden:
            res = prep._step_diagnostics({"root": str(p)})
            assert res is True
        run_hidden.assert_called_once()
        assert run_hidden.call_args.args == (command,)
        assert run_hidden.call_args.kwargs["shell"] is False
        assert run_hidden.call_args.kwargs["timeout"] == 15.0
        assert run_hidden.call_args.kwargs["cwd"] == str(p)

        with closing(prep._connect()) as con:
            row = con.execute("SELECT status, phase FROM projects WHERE root=?", (str(p),)).fetchone()
            assert row["status"] == "complete"
            assert row["phase"] == "complete"
            diag = con.execute("SELECT exit_code, stdout_preview FROM diagnostic_baselines WHERE root=?", (str(p),)).fetchone()
            assert diag is not None
            assert diag["exit_code"] == -1
            assert "timed out" in diag["stdout_preview"]
    finally:
        prep.close()


