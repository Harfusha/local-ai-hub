"""Contract tests for the native desktop controller (no service or display)."""
from unittest.mock import MagicMock, patch

import pytest

from tools import desktop


def test_read_never_autostarts_or_calls_offline_hub():
    with patch.object(desktop, "HubClient") as factory:
        factory.return_value._online.return_value = False
        control = desktop.HubControl("config.toml")
        with pytest.raises(RuntimeError, match="not reachable"):
            control.read("Overview")
        factory.assert_called_once_with(config_path="config.toml", auto_start=False)
        factory.return_value.get.assert_not_called()
        factory.return_value.close.assert_called_once()


def test_scoped_read_requires_explicit_root():
    control = desktop.HubControl()
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="explicit"):
            control.read("Tasks")
        factory.assert_not_called()


def test_scoped_read_encodes_root(tmp_path):
    root = tmp_path / "space & name"
    root.mkdir()
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True, "tasks": []}
        result = desktop.HubControl().read("Tasks", str(root))
        assert result["tasks"] == []
        from urllib.parse import parse_qs, urlsplit
        url = client.get.call_args.args[0]
        assert parse_qs(urlsplit(url).query)["root"] == [str(root.resolve())]
        client.close.assert_called_once()


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_lifecycle_reuses_existing_cli(action):
    control = desktop.HubControl("config.toml")
    with patch.object(control, "_cli", return_value="completed") as cli:
        assert control.lifecycle(action) == "completed"
        cli.assert_called_once_with((action,), timeout=760)


def test_start_when_offline():
    control = desktop.HubControl()
    with patch.object(control, "online", return_value=False), patch.object(
        control, "_cli", return_value="started"
    ) as cli:
        assert control.lifecycle("start") == "started"
        cli.assert_called_once_with(("start",), timeout=760)


def test_start_is_idempotent_if_online():
    control = desktop.HubControl()
    with patch.object(control, "online", return_value=True), patch.object(control, "_cli") as cli:
        assert control.lifecycle("start") == "Hub is already online."
        cli.assert_not_called()


@pytest.mark.parametrize("value", ["command", "start && anything", "--help"])
def test_rejects_unregistered_lifecycle_and_modes(value):
    control = desktop.HubControl()
    with patch.object(control, "_cli") as cli:
        with pytest.raises(ValueError):
            control.lifecycle(value)
        with pytest.raises(ValueError):
            control.mode(value)
        cli.assert_not_called()


def test_cli_uses_fixed_argv_no_shell():
    control = desktop.HubControl("config.toml")
    with patch.object(desktop.subprocess, "run") as run:
        run.return_value = MagicMock(returncode=0, stdout="started", stderr="")
        assert control._cli(("start",), 760) == "started"
        args, kwargs = run.call_args
        assert args[0] == [desktop.sys.executable, str(desktop.ROOT / "tools" / "hubctl.py"), "start"]
        assert not kwargs.get("shell", False)
        assert kwargs["env"]["LOCAL_AI_CONFIG"] == "config.toml"


def test_api_failure_is_not_rendered_as_success():
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": False, "error": "denied"}
        with pytest.raises(RuntimeError, match="denied"):
            desktop.HubControl().read("Overview")
        client.close.assert_called_once()


def test_maintenance_requires_explicit_success():
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.post.return_value = {"success": False, "error": "denied"}
        with pytest.raises(RuntimeError, match="denied"):
            desktop.HubControl().maintenance("Purge expired cache (7 days)")
        assert client.post.call_args.args == ("/api/maintenance/purge_cache", {"days": 7})
        client.close.assert_called_once()


def test_unknown_maintenance_is_rejected_before_transport():
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(KeyError):
            desktop.HubControl().maintenance("arbitrary shell")
        factory.assert_not_called()


def test_bridge_rejects_arbitrary_route_and_shell():
    control = MagicMock()
    for request in (
        {"op": "post", "args": {"route": "/api/command"}},
        {"op": "shell", "args": {"command": "echo no"}},
        {"op": "project", "args": {"action": "arbitrary", "confirmed": True}},
    ):
        with pytest.raises(ValueError):
            desktop.dispatch(control, request)
    control._client.assert_not_called()


@pytest.mark.parametrize("op,args", [
    ("maintenance", {"action": "Purge detailed traces"}),
    ("telemetry", {"mode": "full"}),
    ("config_reset", {}),
    ("task", {"action": "complete", "id": "task_1"}),
    ("project", {"action": "unregister"}),
])
def test_bridge_requires_confirmation(op, args):
    with pytest.raises(ValueError, match="confirmation"):
        desktop.dispatch(MagicMock(), {"op": op, "args": args})


def test_plan_board_requires_explicit_scope():
    with pytest.raises(ValueError, match="explicit"):
        desktop.dispatch(MagicMock(), {"op": "plan_board", "args": {"id": "plan_1"}})


def test_project_unregister_keeps_data(tmp_path):
    control = MagicMock()
    with patch.object(desktop, "checked_post", return_value={"success": True}) as post:
        desktop.dispatch(control, {"op": "project", "args": {
            "root": str(tmp_path), "action": "unregister", "confirmed": True}})
        post.assert_called_once_with(control, "/api/preprocess", {
            "root": str(tmp_path.resolve()), "action": "unregister", "purge_data": False})


def test_bridge_never_imports_tkinter():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(desktop.__file__).read_text(encoding="utf-8"))
    imports = [a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names]
    assert "tkinter" not in imports
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "tkinter"
                   for node in ast.walk(tree))


@pytest.mark.parametrize("path", ["/", "/dashboard", "/dashboard/", "/favicon.ico"])
def test_http_web_ui_route_is_retired(path):
    from local_ai_hub.http_api_get import HttpGetMixin
    handler = MagicMock()
    handler.path = path
    handler._reject_identity_fields.return_value = True
    HttpGetMixin.do_GET(handler)
    handler._send.assert_called_once_with(
        404, {"success": False, "error": "Web UI removed; use Local AI Hub Desktop."}
    )


def test_trace_identifier_cannot_select_another_route():
    control = MagicMock()
    with pytest.raises(ValueError, match="Invalid trace identifier"):
        desktop.dispatch(control, {"op": "trace_detail", "args": {"id": "../config"}})
    control._client.assert_not_called()


def test_plan_edit_requires_current_revision(tmp_path):
    control = MagicMock()
    with pytest.raises(ValueError, match="revision"):
        desktop.dispatch(control, {"op": "plan_update", "args": {
            "root": str(tmp_path), "id": "plan_1", "title": "new", "confirmed": True}})
    control._client.assert_not_called()


@pytest.mark.parametrize("operation", ["bundle_import", "bundle_export", "diagnostics_export"])
def test_binary_transfer_requires_confirmation(operation):
    control = MagicMock()
    with pytest.raises(ValueError, match="confirmation"):
        desktop.dispatch(control, {"op": operation, "args": {"file": "test.zip"}})
    control._client.assert_not_called()


def test_native_setting_rejects_retired_web_flags():
    control = MagicMock()
    with pytest.raises(ValueError, match="retired"):
        desktop.dispatch(control, {"op": "setting", "args": {
            "key": "features.dashboard", "value": True, "confirmed": True}})
    control._client.assert_not_called()


def test_native_plan_move_cannot_claim_done(tmp_path):
    control = MagicMock()
    with pytest.raises(ValueError, match="completion"):
        desktop.dispatch(control, {"op": "plan_task_move", "args": {
            "root": str(tmp_path), "id": "plan_1", "revision": "rev", "task_id": "task_1",
            "status": "done", "confirmed": True}})
    control._client.assert_not_called()


def test_vision_rejects_non_image_before_transport(tmp_path):
    image = tmp_path / "not-image.png"
    image.write_bytes(b"not an image")
    control = MagicMock()
    with pytest.raises(ValueError, match="Unsupported image"):
        desktop.dispatch(control, {"op": "vision_review", "args": {
            "file": str(image), "prompt": "Describe", "confirmed": True}})
    control._client.assert_not_called()


def test_native_event_stream_requires_repository_and_stream():
    with pytest.raises(ValueError, match="explicit"):
        desktop.dispatch(MagicMock(), {"op": "event_stream", "args": {"stream": "task_1"}})


def test_native_update_install_requires_confirmation():
    control = MagicMock()
    with pytest.raises(ValueError, match="confirmation"):
        desktop.dispatch(control, {"op": "update_install", "args": {"version": "1.0.0"}})
    control._client.assert_not_called()


def test_change_plan_bridge_is_read_only_and_scoped(tmp_path):
    control = MagicMock()
    with patch.object(desktop, "checked_post", return_value={"success": True}) as post:
        desktop.dispatch(control, {"op": "change_plan", "args": {
            "root": str(tmp_path), "mode": "summary", "offset": 4,
            "expected_revision": "abc",
        }})
        assert post.call_args.args == (
            control, "/api/repo/split_changes",
            {"root": str(tmp_path.resolve()), "mode": "summary", "offset": 4,
             "limit": 4, "expected_revision": "abc"},
        )
        with pytest.raises(ValueError):
            desktop.dispatch(control, {"op": "change_plan", "args": {
                "root": str(tmp_path), "mode": "apply",
            }})


def test_change_transaction_rejects_unconfirmed_or_unknown_actions(tmp_path):
    control = MagicMock()
    for action in ("stage-apply", "commit-staged", "annotate", "sequence-apply", "sequence-verify", "arbitrary-command"):
        with pytest.raises(ValueError):
            desktop.dispatch(control, {"op": "change_transaction", "args": {
                "action": action, "root": str(tmp_path), "confirmed": False,
            }})


def test_local_stage_preview_bridge(tmp_path):
    control = MagicMock()
    with patch("local_ai_hub.config.load_config", return_value={}), \
         patch("local_ai_hub.deterministic.DeterministicEngine"), \
         patch("local_ai_hub.leases.ScopeLeaseStore"), \
         patch("local_ai_hub.state_paths.configured_state_dir", return_value=tmp_path / "state"), \
         patch("local_ai_hub.change_stage_execution.stage_selection", return_value={"success": True}) as stage:
        result = desktop.dispatch(control, {"op": "change_transaction", "args": {
            "action": "stage-preview", "root": str(tmp_path), "paths": ["a.py"],
            "expected_revision": "a" * 64,
        }})
        assert result["success"]
        assert stage.call_args.kwargs["apply"] is False
        assert stage.call_args.kwargs["paths"] == ["a.py"]


def test_desktop_sequence_requires_existing_receipts_and_exact_preview(tmp_path):
    control = MagicMock()
    common = {"root": str(tmp_path), "paths": ["a.py"], "expected_revision": "a" * 64,
              "expected_tree": "b" * 40, "sequence": [{"paths": ["a.py"], "message": "fix: a"}]}
    with patch("local_ai_hub.config.load_config", return_value={}), \
         patch("local_ai_hub.deterministic.DeterministicEngine"), \
         patch("local_ai_hub.leases.ScopeLeaseStore"), \
         patch("local_ai_hub.state_paths.configured_state_dir", return_value=tmp_path / "state"), \
         patch("local_ai_hub.change_commit_journal.CommitJournal"), \
         patch("local_ai_hub.change_commit_execution.execute_staged_commit", return_value={"success": True}) as execute:
        desktop.change_transaction(control, {**common, "action": "sequence-preview"})
        assert execute.call_args.kwargs["preview_only"] is True
        assert execute.call_args.kwargs["approved"] is False
        execute.reset_mock()
        with pytest.raises(ValueError, match="receipts"):
            desktop.change_transaction(control, {**common, "action": "sequence-apply", "confirmed": True})
        execute.assert_not_called()
        manifest = {"environment_id": "c" * 64, "commands": [["/trusted/python", "-m", "pytest"]]}
        desktop.change_transaction(control, {**common, "action": "sequence-apply", "confirmed": True,
                                             "preview_digest": "d" * 64, "verification_manifest": manifest})
        assert execute.call_args.kwargs["verification_manifest"] == manifest
        assert execute.call_args.kwargs["preview_digest"] == "d" * 64
        assert execute.call_args.kwargs["approved"] is True


def test_desktop_annotation_reobserves_exact_root(tmp_path):
    control = MagicMock()
    record = {"atom_ids": ["a" * 64], "actor": "operator", "task_id": "task", "status": "reviewed"}
    with patch("local_ai_hub.config.load_config", return_value={}), \
         patch("local_ai_hub.deterministic.DeterministicEngine") as engine, \
         patch("local_ai_hub.state_paths.configured_state_dir", return_value=tmp_path / "state"), \
         patch("local_ai_hub.change_ledger.ChangeLedger") as ledger:
        desktop.change_transaction(control, {"root": str(tmp_path), "action": "annotate",
                                             "expected_revision": "b" * 64, "record": record, "confirmed": True})
        engine.return_value.split_changes.assert_called_once_with(str(tmp_path.resolve()), None)
        ledger.return_value.annotate.assert_called_once_with(engine.return_value.split_changes.return_value,
                                                             expected_revision="b" * 64, record=record)
