from __future__ import annotations

import subprocess
import os
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.process_utils import ProcessCancelledError, ProcessCleanupUnverifiedError


@pytest.mark.parametrize("timeout_failure", [False, True])
def test_diagnostic_cleanup_uncertainty_is_recorded_and_not_completed(
    tmp_path: Path, timeout_failure: bool
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    command = ["python", "-c", "print('žluťoučký')"]
    services = MagicMock()
    services.repo_profile.return_value = {"validation_commands": [{"argv": command}]}
    scheduler = MagicMock()
    scheduler.background_allowed.return_value = True
    scheduler.foreground_busy.return_value = False
    prep = ProjectPreprocessor(
        {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": False, "idle_diagnostics_enabled": True}},
        services=services,
        rag=MagicMock(),
        scheduler=scheduler,
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    process = MagicMock()
    if timeout_failure:
        cleanup_error = subprocess.TimeoutExpired(
            command, 15.0, output="partial stdout", stderr="partial stderr"
        )
        cleanup_error.cleanup_confirmed = False
    else:
        cleanup_error = ProcessCleanupUnverifiedError(
            command,
            process=process,
            tree_termination_confirmed=False,
            output="partial stdout",
            stderr="partial stderr",
        )
    now = time.time()
    try:
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "ws-repo", "running", "diagnostics", 0, 0, now, now, now, 0, now, "agent"),
            )
            con.commit()

        with patch("local_ai_hub.process_utils.run_hidden", side_effect=cleanup_error) as run_hidden:
            with pytest.raises(type(cleanup_error)):
                prep._step_diagnostics({"root": str(root)})

        run_hidden.assert_called_once()
        assert run_hidden.call_args.args == (command,)
        assert run_hidden.call_args.kwargs["timeout"] == 15.0
        assert run_hidden.call_args.kwargs["shell"] is False
        assert run_hidden.call_args.kwargs["cwd"] == str(root)
        with closing(prep._connect()) as con:
            project = con.execute(
                "SELECT status, phase FROM projects WHERE root=?", (str(root),)
            ).fetchone()
            baseline = con.execute(
                "SELECT command, exit_code, error_count, stdout_preview FROM diagnostic_baselines WHERE root=?",
                (str(root),),
            ).fetchone()
        assert (project["status"], project["phase"]) == ("running", "diagnostics")
        assert baseline["command"]
        assert baseline["exit_code"] == -1
        assert baseline["error_count"] == 1
        assert "cleanup could not be verified" in baseline["stdout_preview"]
        assert "partial stderr" in baseline["stdout_preview"]
    finally:
        prep.close()


def test_idle_diagnostics_default_is_opt_out(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    services = MagicMock()
    prep = ProjectPreprocessor(
        {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": False}},
        services=services,
        rag=MagicMock(),
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    try:
        with patch("local_ai_hub.process_utils.run_hidden") as run_hidden:
            assert prep._step_diagnostics({"root": str(root)}) is True
        services.repo_profile.assert_not_called()
        run_hidden.assert_not_called()
    finally:
        prep.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch executable boundary")
def test_windows_batch_validation_executable_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    services = MagicMock()
    services.repo_profile.return_value = {
        "validation_commands": [{"argv": ["validate.CMD", "--quiet"]}]
    }
    scheduler = MagicMock()
    scheduler.background_allowed.return_value = True
    scheduler.foreground_busy.return_value = False
    prep = ProjectPreprocessor(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "preprocessing": {"enabled": False, "idle_diagnostics_enabled": True},
        },
        services=services,
        rag=MagicMock(),
        scheduler=scheduler,
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    now = time.time()
    try:
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "ws-repo", "running", "diagnostics", 0, 0, now, now, now, 0, now, "agent"),
            )
            con.commit()

        with patch("local_ai_hub.process_utils.run_hidden") as run_hidden:
            assert prep._step_diagnostics({"root": str(root)}) is True
        run_hidden.assert_not_called()
        with closing(prep._connect()) as con:
            baseline = con.execute(
                "SELECT exit_code, stdout_preview FROM diagnostic_baselines WHERE root=?",
                (str(root),),
            ).fetchone()
        assert baseline["exit_code"] == -1
        assert "Windows batch files are not permitted" in baseline["stdout_preview"]
    finally:
        prep.close()


def test_diagnostic_stop_before_launch_defers_without_profile_lookup(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    services = MagicMock()
    scheduler = MagicMock()
    prep = ProjectPreprocessor(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "preprocessing": {"enabled": False, "idle_diagnostics_enabled": True},
        },
        services=services,
        rag=MagicMock(),
        scheduler=scheduler,
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    prep._stop.set()
    try:
        with patch("local_ai_hub.process_utils.run_hidden") as run_hidden:
            assert prep._step_diagnostics({"root": str(root)}) is False
        services.repo_profile.assert_not_called()
        run_hidden.assert_not_called()
    finally:
        prep.close()


def test_diagnostic_run_hidden_cancellation_defers_without_failure_baseline(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    command = ["python", "-c", "import time; time.sleep(30)"]
    services = MagicMock()
    services.repo_profile.return_value = {"validation_commands": [{"argv": command}]}
    scheduler = MagicMock()
    scheduler.background_allowed.return_value = True
    scheduler.foreground_busy.return_value = False
    prep = ProjectPreprocessor(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "preprocessing": {"enabled": False, "idle_diagnostics_enabled": True},
        },
        services=services,
        rag=MagicMock(),
        scheduler=scheduler,
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    now = time.time()
    try:
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root, workspace, status, phase, generation, force_refresh, registered_at, updated_at, next_check_at, paused, last_requested_at, registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "ws-repo", "running", "diagnostics", 0, 0, now, now, now, 0, now, "agent"),
            )
            con.commit()

        def cancel_during_run(argv, **kwargs):
            cancel_event = kwargs["cancel_event"]
            prep._stop.set()
            assert cancel_event.is_set() is True
            error = ProcessCancelledError(argv)
            error.cleanup_confirmed = True
            raise error

        with patch(
            "local_ai_hub.process_utils.run_hidden", side_effect=cancel_during_run
        ) as run_hidden:
            assert prep._step_diagnostics({"root": str(root)}) is False

        assert run_hidden.call_args.args == (command,)
        assert "cancel_event" in run_hidden.call_args.kwargs
        with closing(prep._connect()) as con:
            project = con.execute(
                "SELECT status, phase FROM projects WHERE root=?", (str(root),)
            ).fetchone()
            baseline = con.execute(
                "SELECT 1 FROM diagnostic_baselines WHERE root=?", (str(root),)
            ).fetchone()
        assert (project["status"], project["phase"]) == ("running", "diagnostics")
        assert baseline is None
    finally:
        prep.close()
